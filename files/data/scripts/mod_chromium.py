#!/usr/bin/env python3
"""
Chromium browser, with control
"""
from __future__ import annotations

import sys
import os
import time
import stat
import json
import asyncio
import signal
import platform
import subprocess
import threading
import tempfile
import shutil

from datetime import datetime
from pathlib import Path
from typing import Callable, Union, Any, Awaitable, TYPE_CHECKING

import requests
import websockets

from mod_common import ModService

if TYPE_CHECKING:
    from log_manager import LogManager
    from config import Config


class Chromium(ModService):
    """Launch and interact with a Chromium instance"""
    crdp_port = 9222  # Chromium remote debugging protocol port
    timeout = 10  # seconds, how long to wait for crdp requests
    retry_wait = 2  # how long to wait before crdp connection retry
    launch_on_dev: bool = False  # if true, will launch chromium when development environment is detected (macOS)
    forward_console_to_local: bool = False  # if true, will forward js console messages to local logger. will always go to file
    profile_dir = '/config/chromium_profile'

    def __init__(self, config: Config, logger: LogManager) -> None:
        self.config = config
        self.log = logger
        self.log.debug('Initializing Chromium Manager')
        self.req_id = 1  # incremented for every request we send to CRDP

        self.binary = '/usr/bin/chromium-browser'
        if platform.system() == 'Darwin':
            self.binary = '/Applications/Chromium.app/Contents/MacOS/Chromium'
        if not Path(self.binary).exists():
            self.binary = '/usr/bin/chromium'
            if not Path(self.binary).exists():
                self.log.error('Could not find chromium binary!')
                self.log.error('checked: /usr/bin/chromium and /usr/bin/chromium-browser')
                sys.exit()
        self.temp_dir = Path(tempfile.NamedTemporaryFile(delete=False).name)  # do not user mkdtemp() to avoid creating at this time
        self.temp_dir.unlink()  # have to remove the file because we're using it as a folder
        self.stop_signal = threading.Event()
        self.thread_browser: Union[threading.Thread, None] = None
        self.thread_console: Union[threading.Thread, None] = None
        self.console_log: list[dict[str, Any]] = []
        self.clog_lock: threading.Lock = threading.Lock()

    def start(self):
        """Start the Chromium threads"""
        self.temp_dir.mkdir()
        self.stop_signal.clear()
        cs_script = Path('/scripts/setup_display.sh')
        if cs_script.is_file():
            subprocess.run(cs_script, check=False)

        self.log.debug(f'Using temp_dir: {self.temp_dir.absolute()}')
        url: str = self.config.get('url')
        scale: float = float(self.config.get('browser_scale'))
        if platform.system() == 'Darwin':
            if not self.launch_on_dev:
                self.log.warning('Skipping launch of Chromium browser and console logging threads on development environment (macOS)')
                return

        self.log.info('Starting Chromium browser thread')
        self.thread_browser = threading.Thread(target=self.run_chromium, args=[url, scale, self.profile_dir], daemon=False)
        self.thread_browser.start()

        self.log.info('Starting Chromium console logging thread')
        self.thread_console = threading.Thread(target=self.monitor_console, args=[self.stop_signal,], daemon=False)
        self.thread_console.start()

    def stop(self):
        """Stop Chromium threads"""
        if self.thread_browser is not None:
            self.log.info('Stopping Chromium...')
            self.stop_signal.set()
            time.sleep(0.5)
            self.kill_process()
            time.sleep(0.5)

    def cleanup(self):
        """Cleanup temporary stuff"""
        if not platform.system() == 'Darwin':
            self.log.info('Clearing the display')
            cs_script = Path('/scripts/clear_display.sh')
            if cs_script.is_file():
                subprocess.run(cs_script, check=False)
        self.log.debug(f'Cleaning up temp dir: {self.temp_dir}')
        shutil.rmtree(self.temp_dir)
        self.thread_browser = None
        self.thread_console = None
        self.req_id = 1

    def clear_data(self):
        """Clear browser data"""
        self.log.info('Clearing browser data')
        self.stop()
        time.sleep(0.5)
        self.cleanup()
        if platform.system() != 'Linux':
            self.log.warning(f'NOT clearing browser data on platform: {platform.system()}')
        else:
            shutil.rmtree(self.profile_dir)
            Path(self.profile_dir).mkdir()
        self.start()

    def kill_process(self) -> None:
        """Find and kill the Chromium process"""
        # NOTE here we nuke Xorg to take all the chromium processes with it
        self.log.debug('Forcibly killing Xorg process')
        try:
            process_name = '/usr/lib/xorg/Xorg'
            if platform.system() == 'Darwin':
                process_name = self.binary
            running_procs = os.popen("ps ax | grep " + process_name + " | grep -v grep")

            proc_count = 0
            pids: list[int] = []
            for line in running_procs:
                try:
                    pid = line.split()[0]
                    if pid.strip() != '':
                        pidint = int(pid)
                        pids.append(pidint)
                        proc_count += 1
                except Exception:
                    pass

            self.log.debug(f'Found {proc_count} processes matching: {process_name}')
            for pid in pids:
                self.log.debug(f'Killing pid: {pid}')
                os.kill(pid, signal.SIGKILL)
        except Exception as ex:
            self.log.warning(f'Failed to kill Chromium: {ex}')

    def get_display_resolution(self) -> str:
        """Figure out display resolution a x,y string, ie: 1920,1080"""
        # here we detect resolution by briefly starting X11 and then parsing output of xrandr
        #       this is simpler and more reliable than parsing xorg.conf
        #       by avoiding a hardcoded resolution here, we only need to make changes in xorg.conf if we want to change resolution or rotate

        # NOTE MUST run as root
        # TODO this should be do-able without writing a temporary file

        if platform.system() == 'Darwin':
            return '1920,1080'

        scr = r"""#!/bin/bash
        /usr/bin/xinit /usr/bin/xrandr 2>/dev/null|grep "\*"|awk '{print $1}'|tr 'x' ','
        """

        # strip leading whitespace so we can indent above without affecting output
        newscr = ''
        for line in scr.splitlines():
            newscr += line.lstrip() + '\n'

        temp_file = self.temp_dir.joinpath('get_display_rez.sh')

        with open(temp_file, 'wt', encoding='utf-8') as tf:
            tf.write(newscr)

        cur_bits = os.stat(temp_file)
        os.chmod(temp_file, cur_bits.st_mode | stat.S_IEXEC)
        result = subprocess.run(temp_file, capture_output=True, text=True, check=True, timeout=10)

        # cleanup temp file
        temp_file.unlink()
        rez = result.stdout.strip()
        return rez

    def adjust_resolution_for_scale(self, rez: str, scale: float) -> str:
        """Adjust the given resolution string "width,height" to account for given scale"""
        width = int(rez.split(',')[0])
        height = int(rez.split(',')[1])
        new_width = int(width * (1 / scale))
        new_height = int(height * (1 / scale))
        return f'{new_width},{new_height}'

    def run_chromium(self, url: str, display_scale: float = 1.0, user_data_dir: Path = Path('/config'), disk_cache_dir: Path = Path('/dev/null'), chr_args: str = '', x_args: str = '-nocursor'):
        """Start X with just Chromium browser
            fullscreen, kiosk mode, tweaked for touchscreen, with given url, and remote debugging enabled

            need to install first:
                sudo apt-get install chromium-browser
        """
        self.log.info(f'Launching Chromium with url: {url}')

        # we need to get display resolution so we can match it
        #       if you don't set --window-size, Chromium will go almost-fullscreen, about 10px shy on all sides
        #       if you don't set --window-position, Chromium will start at about 10,10 instead of 0,0
        #       why does Chromium do this??!?!

        # if you have issues where SCALE (--force-device-scale-factor) is not working as expected
        #       try removing --window-size and --window-position arguments completely, and see if Chromium will go fullscreen-enough for your use-case

        # the _correct_ solution it seems, is to adjust the window size arguments to account for the desired scale

        display_resolution = self.get_display_resolution()
        self.log.debug(f'Detected resolution: {display_resolution}')
        display_resolution = self.adjust_resolution_for_scale(display_resolution, display_scale)
        self.log.debug(f'Scaled resolution ({display_scale}): {display_resolution}')

        display_args = [
            '--no-gpu',
            '--disable-gpu',
            f'--window-size={display_resolution}',
            '--window-position=0,0',
            f'--force-device-scale-factor={display_scale}',
        ]

        performance_args = [
            '--disable-smooth-scrolling',
            '--fast',
            '--fast-start',
        ]

        security_args = [
            '--no-sandbox',
            '--autoplay-policy=no-user-gesture-required',
            '--use-fake-ui-for-media-stream',
            '--use-fake-device-for-media-stream',
            '--disable-sync',
            '--password-store=basic',

        ]

        input_args = [
            '--pull-to-refresh=1',
            '--disable-pinch',
            '--touch-events=enabled',
        ]

        interface_args = [
            '--disable-login-animations',
            '--disable-modal-animations',
            '--noerrdialogs',
            '--no-first-run',
            '--disable-infobars',
            '--overscroll-history-navigation=0',
            '--disable-translate',
            '--hide-scrollbars',
            '--disable-overlay-scrollbar',
            '--disable-features=OverlayScrollbar',
            '--disable-features=TranslateUI',
            '--ignore-certificate-errors',
        ]

        debugging_args = [
            '--remote-allow-origins=*',
            f'--remote-debugging-port={self.crdp_port}',
        ]

        if platform.system() == 'Darwin':
            disk_cache_dir = self.temp_dir.joinpath('chromium_cache')
            user_data_dir = self.temp_dir.joinpath('chromium_userdata')
            chromium_args = display_args + performance_args + security_args + input_args + interface_args + debugging_args + [
                f'--disk-cache-dir={disk_cache_dir}',
                f'--user-data-dir={user_data_dir}',
                f'{url}',
            ]
        else:
            chromium_args = display_args + performance_args + security_args + input_args + interface_args + debugging_args + [
                f'--disk-cache-dir={disk_cache_dir}',
                f'--user-data-dir={user_data_dir}',
                f'--kiosk {chr_args}',
                f'--app={url}',
            ]

        # does not get cleaned up properly after previous exit
        try:
            singleton_lock = Path(user_data_dir).joinpath('SingletonLock')
            if singleton_lock.exists():
                singleton_lock.unlink()
        except Exception:
            pass

        if platform.system() == 'Darwin':
            # just open Chromium, dont do anything else
            try:
                with open(self.log.log_chromium, 'wt', encoding='utf-8') as clf:
                    subprocess.run([self.binary] + chromium_args, check=True, stdout=clf, stderr=clf)
            except subprocess.CalledProcessError as ex:
                self.log.warning(f'Chromium process threw an exception: {ex}')
            except Exception as ex:
                self.log.exception(f'Unexpected exception when running chromium: {ex}')

        else:
            # build the whole Chromium command
            chromium_command = self.binary
            for arg in chromium_args:
                chromium_command += f' {arg}'

            self.log.debug(f'Chromium command line: {chromium_command}')

            # build xinitrc content
            allow_sleep: bool = self.config.get('screen_sleep_allow')
            if allow_sleep:
                xi_content = f"""# Generated by marquee service
                echo "Chromium command line: {chromium_command}"
                echo "running Chromium..."
                {chromium_command}
                """
            else:
                xi_content = f"""# Generated by marquee service
                echo "running: xset -dpms"
                xset -dpms
                echo "running: set s off"
                xset s off
                echo "running: set s noblank"
                xset s noblank
                echo "Chromium command line: {chromium_command}"
                echo "running Chromium..."
                {chromium_command}
                """
            # strip leading whitespace so we can indent above without affecting output
            xi_content_stripped = ''
            for line in xi_content.splitlines():
                xi_content_stripped += line.lstrip() + '\n'

            # write temporary xinitrc file
            temp_xinitrc = self.temp_dir.joinpath('chromium_xinitrc')
            with open(temp_xinitrc, 'wt', encoding='utf-8') as xi:
                xi.write(xi_content_stripped)

            # build actual command line to run
            cmd = ['xinit', str(temp_xinitrc), '--', f'{x_args}']

            # finally, run the command
            try:
                with open(self.log.log_chromium, 'wt', encoding='utf-8') as clf:
                    subprocess.run(cmd, check=True, stdout=clf, stderr=clf)
            except subprocess.CalledProcessError as ex:
                self.log.warning(f'Chromium process threw an exception: {ex}')
            except Exception as ex:
                self.log.exception(f'Unexpected exception when running chromium: {ex}')

    def get_tab_debug_url(self) -> Union[str, None]:
        """Get the Chromium remote debugging url for the first open tab"""
        resp = requests.get(url=f'http://localhost:{self.crdp_port}/json', timeout=self.timeout)
        top_level = resp.json()
        if len(top_level) == 0:
            self.log.error('There appears to be no tab open in Chromium')
            return None
        this_tab = top_level[0]
        if 'webSocketDebuggerUrl' not in this_tab:
            self.log.error('Could not find webSocketDebuggerUrl in first Chromium tab info')
            return None
        debug_url = this_tab['webSocketDebuggerUrl']
        return debug_url

    async def async_crdp_send(self, message: dict[str, Any]):
        """ASYNC: send a message to Chromium remote debugging and return the response
            automatically handles id
        """

        self.req_id += 2
        debug_url = self.get_tab_debug_url()
        if debug_url is None:
            return {'error': 'Failed to get debug url'}
        message['id'] = self.req_id
        async with websockets.connect(debug_url) as ws:
            await ws.send(json.dumps({'id': self.req_id - 1, 'method': 'Network.enable'}))
            _resp = await ws.recv()
            await ws.send(json.dumps(message))
            response = await ws.recv()
        return response

    def chromium_send(self, message: dict[str, Any]) -> Any:
        """Send a message to Chromium remote debugging and return response"""
        response = asyncio.run(self.async_crdp_send(message))
        return json.loads(response)  # type: ignore

    def chromium_navigate(self, url: str):
        """Tell Chromium to navigate to a url"""
        resp = self.chromium_send({
            'method': 'Page.navigate',
            'params': {
                'url': url,
            }
        })
        return resp

    async def async_crdp_monitor(self, callback: Callable[[dict[str, Any]], Awaitable[None]], enable: list[str], methods: list[str], stop_sig: threading.Event):
        """ASYNC: Enable a list of events, and then send ones matching given methods to callback
            will retry connection until connected, but NOT reconnect if disconnected after that
        """
        self.req_id += 1

        retry_count = 0
        connected = False
        while not stop_sig.is_set() and not connected:
            retry_count += 1
            try:
                debug_url = self.get_tab_debug_url()
                if debug_url is None:
                    raise TimeoutError('Failed to get debug url')
                async with websockets.connect(debug_url) as ws:
                    self.log.info('Successfully connected to Chromium instance for javascript console streaming')
                    connected = True
                    retry_count = 0
                    for en_meth in enable:
                        self.log.debug(f'Enabling events for: {en_meth}')
                        await ws.send(json.dumps({'id': self.req_id, 'method': en_meth}))
                        _resp = await ws.recv()
                        self.req_id += 1
                    self.log.debug(f'Listening for event messages for methods: {",".join(methods)}')
                    while not stop_sig.is_set():
                        response = await ws.recv()
                        parsed_msg = json.loads(response)
                        # print(json.dumps(parsed_msg, indent=4))
                        if 'method' in parsed_msg and 'params' in parsed_msg:
                            if parsed_msg['method'] in methods:
                                await callback(parsed_msg)
            except Exception as ex:
                # backoff for a second on any failure
                if not connected:
                    self.log.warning(f'Could not reach Chromium instance, will retry in {self.retry_wait} seconds (attempt {retry_count})')
                    await asyncio.sleep(self.retry_wait)
                else:
                    self.log.warning(f'Disconnected from Chromium instance: {ex}')

    async def handle_console_msg(self, parsed_msg: dict[str, Any]):
        """ASYNC: Handle console messages, by listening for CRDP Event: Runtime.consoleAPICalled (console log messages)
            by formatting and writing them to file, or forward to the local log
        """
        # HACK HACK HACK this is a very janky and naive way to do this, and it misses some messages
        #   we started implementing something better in a separate project: chromium_console_renderer
        #   however, the intent for this project is to discard this, and get DevTools via 9222 working correctly in an iframe

        # https://chromedevtools.github.io/devtools-protocol/tot/Runtime/#event-consoleAPICalled
        # TODO right now we fake the script file name using the url, instead we should lookup scriptId
        params = parsed_msg['params']
        log_level: str = params['type']
        content_type = params['args'][0]['type']
        if content_type not in ['string', 'object']:
            self.log.warning(f'Do not know how to handle Chromium console message content type: {content_type}')
        else:
            with self.clog_lock:
                self.console_log.append(params)

            log_timestamp: str = params['timestamp']
            # func_name: str = params['stackTrace']['callFrames'][0]['functionName']
            # if func_name.strip() == '':
            #     func_name = '__unknown__'
            # script_id: str = params['stackTrace']['callFrames'][0]['scriptId']
            trace_lineno: int = int(params['stackTrace']['callFrames'][0]['lineNumber'])
            # col_num: str = params['stackTrace']['callFrames'][0]['columnNumber']
            trace_file: str = params['stackTrace']['callFrames'][0]['url'].split('/')[-1]
            trace_file = trace_file.split('?')[0]  # remove url params from filename

            # TODO missing some messages because an entry can have multiple entries in "args"
            #   if an entry contains any instances of "%c", that means N subsequent entries are actually CSS styling
            #       where N is how many instances of "%c"
            #   we need to walk thru all entries and discard the styling, but keep everything else
            log_text: str = ''
            if content_type == 'string':
                log_text = params['args'][0]['value']
            elif content_type == 'object':
                log_text = 'Object: ' + json.dumps(params['args'][0])

            # remove stuff we dont want to print
            log_text = log_text.replace('\n', ' ')  # sometimes have newlines, remove them
            log_text = log_text.replace('%c', '')  # part of styling messages in the console, discard it
            # print(json.dumps(params, indent=4))

            # Format the message to match formatting used for python logging
            # TODO for error messages, print the stack trace (right now we only grab first frame info)

            log_level = log_level.upper()
            time_formatted = datetime.fromtimestamp(float(log_timestamp) / 1000.0, tz=datetime.now().astimezone().tzinfo).strftime('%Y-%m-%d %I:%M:%S %p %z')

            # write full formatted message to log file
            message_formatted = f'{log_level:>7} {time_formatted:18} [{trace_file:>12}:{trace_lineno}] {log_text}'
            with open(self.log.log_chromium_console, 'at', encoding='utf-8') as clf:
                clf.write(message_formatted + '\n')

            if self.forward_console_to_local:
                # forward message to the local logger
                message_formatted = f'JS: [{trace_file:>10}:{trace_lineno}] {log_text}'
                if log_level == 'DEBUG':
                    self.log.debug(message_formatted)
                elif log_level == 'INFO':
                    self.log.info(message_formatted)
                elif log_level == 'WARNING':
                    self.log.warning(message_formatted)
                elif log_level == 'ERROR':
                    self.log.error(message_formatted)
                elif log_level == 'LOG':
                    self.log.debug(message_formatted)
                else:
                    self.log.info(message_formatted)

    def monitor_console(self, stop_sig: threading.Event):
        """Start an asyncio process to write console log messages to file"""
        self.log.debug('Starting console msg monitor')
        try:
            asyncio.run(self.async_crdp_monitor(self.handle_console_msg, ['Runtime.enable'], ['Runtime.consoleAPICalled'], stop_sig))
        except RuntimeError:
            # Dont care if task is cancelled abruptly
            pass
