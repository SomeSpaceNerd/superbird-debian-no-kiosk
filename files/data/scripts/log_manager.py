#!/usr/bin/env python3
"""
Logging Manager
"""

from __future__ import annotations

import time
import logging
import platform
import shutil
import subprocess

from threading import Thread
from threading import Event as ThreadEvent
from typing import Union
from pathlib import Path

import coloredlogs  # pyright: ignore[reportMissingTypeStubs]


class LogManager:
    """Manage all the logging"""
    systemd_logs_max_days = 14  # days, max days to keep systemd logs
    systemd_logs_max_size = 24  # MB, max size of systemd logs
    logs_check_time = 15  # minutes, how often to check logs size and potentially truncate

    def __init__(self, max_lines: int = 10000, level: int = logging.DEBUG, name: str = __name__) -> None:
        self.max_lines = max_lines
        self.level = level
        self.name = name
        self.log = logging.getLogger(self.name)
        self.log.propagate = False  # otherwise you get duplicate messages on stdout, with different formatters
        self.log.setLevel(self.level)
        self.log_format = '%(levelname)7s %(asctime)s [%(module)16s:%(lineno)4d -> %(funcName)22s()] %(message)s'
        self.date_format = '%Y-%m-%d %I:%M:%S %p %z'
        self.coloredlogging_style: dict[str, dict[str, Union[str, bool]]] = {
            'spam': {'color': 'blue', 'faint': True},  # not used
            'debug': {'color': 'blue'},
            'verbose': {'color': 'blue'},  # not used
            'info': {},
            'notice': {'color': 'magenta'},  # not used
            'warning': {'color': 'yellow'},
            'success': {'color': 'green', 'bold': True},  # not used
            'error': {'color': 'red'},
            'critical': {'color': 'red', 'bold': True},
        }
        self.formatter = logging.Formatter(self.log_format, datefmt=self.date_format)
        # default logs path is on tmpfs (in ram, not on disk), try not to thrash our sdcard!
        # NOTE: on Raspberry Pi OS, it seems that /tmp is NOT tmpfs by default
        #   instead of requiring edits to /etc/fstab, we just use /run instead
        self.logs_dir = Path('/run/kiosk')
        if platform.system() == 'Darwin':
            self.logs_dir = Path('/tmp/kiosk')
        if self.logs_dir.is_dir():
            shutil.rmtree(self.logs_dir)
        self.logs_dir.mkdir(exist_ok=True)
        self.log_script = self.logs_dir.joinpath('backend.log')
        """log for backend + chromium console"""
        self.log_chromium = self.logs_dir.joinpath('chromium.log')
        """log for chromium process"""
        self.log_chromium_console = self.logs_dir.joinpath('chromium_console.log')
        """log for chromium javascript console"""
        self.all_log_files = [self.log_script, self.log_chromium, self.log_chromium_console]
        self.clear('Log cleared at startup')

        self.stopper = ThreadEvent()
        self.monitor: Thread = None  # pyright: ignore[reportAttributeAccessIssue]

        # bind all the logging methods
        self.info = self.log.info
        self.warning = self.log.warning
        self.debug = self.log.debug
        self.error = self.log.error
        self.critical = self.log.critical
        self.exception = self.log.exception

        self.log.debug(f'LogManager Intialized, logs are in: {self.logs_dir}')

    def start(self):
        """Start"""
        self.log.debug('Starting LogManager')
        self.setup_file()
        self.setup_terminal()
        self.stopper.clear()
        self.monitor = Thread(target=self._monitor_log_size, daemon=True)
        self.monitor.start()

    def stop(self):
        """Stop"""
        self.log.debug('Stopping LogManager')
        self.stopper.set()

    def clear(self, message: str):
        """Clear all log files, leaving the given message"""
        self.log.debug('Clearing logs')
        for this_log in self.all_log_files:
            with open(this_log, 'wt', encoding='utf-8') as lf:
                lf.write(f'{message}\n')
        self.clear_systemd_logs()

    def setup_file(self):
        """output logging to file"""
        fh = logging.FileHandler(self.log_script)
        fh.setLevel(self.level)
        fh.setFormatter(self.formatter)
        self.log.addHandler(fh)

    def setup_terminal(self):
        """also log to the terminal"""
        sh = logging.StreamHandler()
        sh.setFormatter(self.formatter)
        sh.setLevel(self.level)
        self.log.addHandler(sh)
        coloredlogs.install(  # pyright: ignore[reportUnknownMemberType]
            level=self.level, logger=self.log,
            fmt=self.log_format, datefmt=self.date_format,
            level_styles=self.coloredlogging_style
        )

    def _monitor_log_size(self):
        """To run in separate thread"""
        while not self.stopper.is_set():
            time.sleep(self.logs_check_time * 60)
            if self.stopper.is_set():
                break
            self.check_log_size()

    def check_log_size(self):
        """Check and truncate log if exceeds max lines"""
        self.log.debug('Checking log sizes')
        for this_lf in self.all_log_files:
            with open(this_lf, "rb") as lfb:
                num_lines = sum(1 for _ in lfb)
            if num_lines > self.max_lines:
                print(f'Clearing log after exceeding {self.max_lines} lines, file: {this_lf}')
                with open(this_lf, 'wt', encoding='utf-8') as lfa:
                    lfa.write(f'Log cleared after exceeding {self.max_lines} lines\n')
                if this_lf == self.log_script:
                    # HACK: any time the main script log is cleared, also clear systemd logs
                    #   there is undoubtely a more correct way to do this but I am lazy
                    self.clear_systemd_logs()

    def clear_systemd_logs(self):
        """Clear all systemd logs beyond configured limits"""
        if not platform.system() == 'Darwin':
            self.log.info(f'Clearing systemd logs older than {self.systemd_logs_max_days} days, and to occupy {self.systemd_logs_max_size} MB max on disk')
            subprocess.run(['journalctl', '--rotate'], check=True)
            subprocess.run(['journalctl', f'--vacuum-time={self.systemd_logs_max_days}d', f'--vacuum-size={self.systemd_logs_max_size}M'], check=True)
