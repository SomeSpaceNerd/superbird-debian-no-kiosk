#!/usr/bin/env python3
"""
Server component of Chromium Kiosk
"""
import os
import time
import sys
import signal
import threading
import logging
import argparse

from log_manager import LogManager
from mod_chromium import Chromium
from mod_webserver import WebServer
from mod_buttons import Buttons

from config import Config


class App:
    """Top level application"""
    max_signals = 2  # max number of signals received before we just kill it
    shutdown_timeout = 4  # seconds allowed for graceful shutdown of kiosk service, after which shutdown will be forced

    def __init__(self, logger: LogManager) -> None:
        self.log = logger
        self.log.info('Initializing Kiosk')
        self.config = Config(self.log)

        self.chromium: Chromium = None  # pyright: ignore[reportAttributeAccessIssue]
        self.buttons: Buttons = None  # pyright: ignore[reportAttributeAccessIssue]
        self.webserver: WebServer = None  # pyright: ignore[reportAttributeAccessIssue]

        self.shutdown_pending = threading.Event()
        self.shutdown_complete = threading.Event()
        self.signal_count = 0

        signal.signal(signal.SIGTERM, self.handle_signal)  # type: ignore
        signal.signal(signal.SIGINT, self.handle_signal)  # type: ignore

    def start(self):
        """Start the application"""
        try:
            self.log.info('Starting Kiosk')

            self.buttons = Buttons(config=self.config, logger=self.log)
            self.buttons.start()

            self.chromium = Chromium(config=self.config, logger=self.log)
            self.chromium.start()

            self.webserver = WebServer(config=self.config, logger=self.log, buttons=self.buttons, chromium=self.chromium)
            self.webserver.start()

            # now loop forever, letting all the threads do their work
            while not self.shutdown_pending.is_set():
                time.sleep(1)

            # loop exited, clean up
            self.shutdown_complete.set()
            self.cleanup()

            self.log.info('Kiosk shutdown successfully')
            sys.exit(0)
        except Exception as ex:
            self.log.exception('Exception in app.start()', exc_info=ex)
            self.cleanup()
            sys.exit(1)

    def handle_signal(self, this_signal: int, _frame):  # type: ignore
        """Callback for when a signal is caught, so we can clean things up before exiting"""
        self.signal_count += 1
        if not self.shutdown_pending.is_set():
            self.log.info(f'  Caught signal: {this_signal}, stopping things and cleaning up')
            self.ensure_shutdown()
            self.shutdown()
        else:
            self.log.info(f'  Caught signal: {this_signal} [{self.signal_count} of {self.max_signals}], shutdown/cleanup already in progress')
            if self.signal_count > self.max_signals:
                self.log.info(f'  Caught more than {self.max_signals} signals, exiting immediately')
                self.cleanup()
                sys.exit(1)

    def ensure_shutdown(self):
        """Ensure shutdown by forcing cleanup and exit after timeout"""
        self.log.debug(f'Kicking off ensure_shutdown thread with timeout of {self.shutdown_timeout} seconds')
        esthread = threading.Thread(target=self._ensure_shutdown, daemon=False)
        esthread.start()

    def _ensure_shutdown(self):
        """Ensure shutdown: runner, inside the thread"""
        time_waited = 0
        time_increment = 0.2
        while not self.shutdown_complete.is_set():
            time.sleep(time_increment)
            time_waited += time_increment
            if time_waited > self.shutdown_timeout:
                self.log.warning(f'  Graceful shutdown took longer than {self.shutdown_timeout} seconds, terminating immediately')
                self.cleanup()
                # os._exit() lets us exit the main thread, from within this thread
                os._exit(1)

    def shutdown(self):
        """Shut things down properly"""
        self.shutdown_pending.set()
        self.chromium.stop()
        self.webserver.stop()
        self.buttons.stop()
        self.log.stop()

    def cleanup(self):
        """Perform cleanup tasks"""
        self.log.debug('Cleaning up')
        try:
            self.chromium.cleanup()
            self.webserver.cleanup()
            self.buttons.cleanup()
        except Exception:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Superbird Kiosk')
    parser.add_argument('-v', '--verbose', action='store_true', help='enable additional logging')
    args = parser.parse_args(sys.argv[1:])  # the sys.argv bit makes it work with pyinstaller

    _level = logging.INFO
    if args.verbose:
        _level = logging.DEBUG
    applog = LogManager(level=_level)
    applog.start()
    try:
        app = App(applog)
    except Exception as ex:
        applog.exception(f'Unexpected exception encountered while creating app: {ex}')
        sys.exit(1)

    try:
        app.start()
    except Exception as ex:
        applog.exception(f'Unexpected exception encountered while running app: {ex}')
        try:
            app.shutdown()
        except Exception:
            pass
        sys.exit(1)
