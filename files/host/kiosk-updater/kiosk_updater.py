#!/usr/bin/env python3
"""
Kiosk Updater
    This runs on the host raspberry pi and provides ability to perform maintenance tasks, such as updating to the latest version (both host and superbird), or restarting either device
"""

import os
import sys
import time
import asyncio
import logging
import subprocess
import platform
import signal

from pathlib import Path
from queue import Queue
from tempfile import NamedTemporaryFile
from threading import Thread, Event
from typing import Union, Callable, Any
from urllib.parse import urlencode

import requests

from packaging.version import Version
from multidict import MultiDictProxy
from aiohttp import web

# #### Repo Configuration

DEV_REPO = True  # Enable to use development repo

if DEV_REPO:
    REPO = 'https://git.bishopdynamics.com/james/superbird-debian'
    REPO_VERSION = 'https://git.bishopdynamics.com/james/superbird-debian/-/raw/main/VERSION'
else:
    REPO = 'https://github.com/bishopdynamics/superbird-debian-kiosk'  # pyright: ignore[reportConstantRedefinition]
    REPO_VERSION = 'https://raw.githubusercontent.com/bishopdynamics/superbird-debian-kiosk/refs/heads/main/VERSION'  # pyright: ignore[reportConstantRedefinition]


# #### Logging configuration

LOG_FILE = '/tmp/kiosk-updater.log'
LOG_LEVEL = logging.INFO
DATE_FORMAT = '%Y-%m-%d %I:%M:%S %p %z'
LOG_FORMAT = '%(levelname)7s %(asctime)s [%(module)16s:%(lineno)4d -> %(funcName)22s()] %(message)s'

WEBSERVER_PORT = 9090


class Colors:
    grey = "\x1b[0;37m"
    green = "\x1b[1;32m"
    yellow = "\x1b[1;33m"
    red = "\x1b[1;31m"
    purple = "\x1b[1;35m"
    blue = "\x1b[1;34m"
    light_blue = "\x1b[1;36m"
    reset = "\x1b[0m"
    blink_red = "\x1b[5m\x1b[1;31m"


class CustomFormatter(logging.Formatter):
    """Logging Formatter to add colors and count warning / errors"""

    def __init__(self):
        super().__init__(datefmt=DATE_FORMAT)
        self.FORMATS = self.define_format()

    def define_format(self) -> dict[int, str]:
        return {
            logging.DEBUG: Colors.blue + LOG_FORMAT + Colors.reset,
            logging.INFO: Colors.grey + LOG_FORMAT + Colors.reset,
            logging.WARNING: Colors.yellow + LOG_FORMAT + Colors.reset,
            logging.ERROR: Colors.red + LOG_FORMAT + Colors.reset,
            logging.CRITICAL: Colors.blink_red + LOG_FORMAT + Colors.reset
        }

    def format(self, record: logging.LogRecord):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


def _get_log(level: int = logging.INFO):
    """Get logger instance; not meant for direct use, import log instead"""
    mylog = logging.getLogger(__name__)
    mylog.setLevel(level)
    plain_formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    color_formatter = CustomFormatter()

    # log to console
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(color_formatter)
    mylog.addHandler(handler)

    # log to file
    with open(LOG_FILE, 'wt', encoding='utf-8') as lf:
        lf.write('')
    fh = logging.FileHandler(LOG_FILE)
    fh.setLevel(LOG_LEVEL)
    fh.setFormatter(plain_formatter)
    mylog.addHandler(fh)

    return mylog


log = _get_log(LOG_LEVEL)


def print_log_line(line: str):
    """Write a line from another logger to ours, using correct level if found"""
    line = f'    {line}'
    if 'DEBUG' in line:
        log.debug(line)
    if 'ERROR' in line:
        log.error(line)
    if 'WARN' in line:
        log.warning(line)
    else:
        log.info(line)


def print_log_lines(lines: str):
    """Write a bunch of lines from another logger to our logger, using correct levels if found"""
    for line in lines.splitlines():
        print_log_line(line)


def _print_bash_result(script: str, result: subprocess.CompletedProcess[str]):
    """Print the input and output of a bash invocation"""

    log.info('Input:')
    for line in script.splitlines():
        log.info(line)
    log.info(f'Return code: {result.returncode}')

    if result.stdout.strip() != '':
        log.info('stdout:')
        for line in result.stdout.strip().splitlines():
            print_log_line(line)

    if result.stderr.strip() != '':
        log.info('stderr:')
        for line in result.stderr.strip().splitlines():
            print_log_line(line)


def run_bash(script: str, print_output: bool = False) -> str:
    """Run a snippet of bash and return stdout. If error, returns empty string"""
    with NamedTemporaryFile('wt', encoding='utf-8') as tempfile:
        tempfile.write(script)
        tempfile.flush()
        result = subprocess.run(['bash', tempfile.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, universal_newlines=True)
    if result.returncode == 0:
        output = result.stdout.strip()
    else:
        output = ''
    if print_output:
        _print_bash_result(script, result)
    return output


ParamsDict = dict[str, str]
"""Request URL parameters, a string dict"""
ParamsType = Union[ParamsDict, None]
"""Parameters passed to an api effector function, potentiall None"""
APIEFunc = Callable[[ParamsDict], None]
"""A function which handles an action for the api"""
APIMapping = dict[str, APIEFunc]
"""A map between an action and the function which handles that action for the api"""


def proxy_to_dict(thing: MultiDictProxy[str]) -> ParamsDict:
    """Convert a MultiDictProxy into a ParamsDict aka dict[str, str]"""
    thing_dict: dict[Any, Any] = {}
    for key, value in thing.items():
        thing_dict[key] = value
    return thing_dict


def truncate_file(file: str, content: str = ''):
    with open(file, 'wt', encoding='utf-8') as ufl:
        ufl.write(content)


class APIEffector():
    """Implementation of actions for API"""
    safe_actions: list[str] = ['Check for Update']  # actions that are OK to do even on dev system
    upgrade_log = '/upgrade.log'  # when update to latest version is called, this is where it will be logged

    def __init__(self) -> None:
        self.allow_update = False
        self.local_version = Version('0.0.0')
        self.remote_version = Version('0.0.0')
        self.update_in_progress = False
        self.update_complete = False
        # ensure the logfile exists
        if platform.system() == 'Linux':
            if not Path(self.upgrade_log).is_file():
                with open(self.upgrade_log, 'wt', encoding='utf-8') as ulf:
                    ulf.write('')

    def get_map(self) -> APIMapping:
        """Get the map of action -> functions for handling api calls"""
        return {
            'Reboot Host': self.reboot_host,
            'Reboot Superbird': self.reboot_superbird,
            'Check for Update': self.check_version,
            'Update to Latest': self.update_latest,
            'Restart Updater Service': self.restart_updater_service,
        }

    def reboot_host(self, _params: ParamsType = None):
        """Reboot the host device (this device)"""
        os.system('reboot')

    def reboot_superbird(self, _params: ParamsType = None):
        """Reboot the superbird device"""
        # TODO hardcoded username here
        log.info('Instructing superbird to reboot via ssh')
        run_bash('ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null -i "/home/superbird/.ssh/id_rsa" superbird@superbird "sudo reboot"')

    def check_version(self, _params: ParamsType = None):
        """Check if there is a newer version in git repo"""
        # HACK when this service starts at boot time, DNS is not working yet so it will fail to fetch version
        #   so we will retry forever until we have a value. Once we have any value other than 0.0.0, we will NOT retry on failure
        retry_after = 4  # seconds, how long to wait between retries
        content = '0.0.0'
        if self.remote_version != Version('0.0.0'):
            self.remote_version = Version('0.0.0')

        while self.remote_version == Version('0.0.0'):
            try:
                response = requests.get(REPO_VERSION, timeout=2.0)
                content = response.content.decode()
                self.remote_version = Version(content)
            except Exception as ex:
                log.debug(f'Exception while fetching remote version: {ex}')
                if self.remote_version == Version('0.0.0'):
                    log.error(f'Failed to get remote version, will retry in {retry_after} seconds')
                    time.sleep(retry_after)
                else:
                    log.error('Failed to get remote version, but we have a stale value so will NOT retry')

        if platform.system() == 'Linux':
            with open('/repo/VERSION', 'rt', encoding='utf-8') as lvf:
                local_version = lvf.read()
        else:
            local_version = '9999.9999.9999'  # never allow update if we cant actually read local version
        self.local_version = Version(local_version)

        # log.info(f'Local: v{self.local_version}, Remote: v{self.remote_version}')
        if self.remote_version > self.local_version:
            log.info('The remote version is newer, you should update!')
            self.allow_update = True
        elif self.remote_version == self.local_version:
            log.info('The remote version is the same. If you wish, you can "update" to reinstall the same version')
            self.allow_update = True
        else:
            log.info('The remote version is OLDER, you cannot update.')
            self.allow_update = False

    def update_latest(self, _params: ParamsType = None):
        """Update to the newest version from git repo"""
        self.check_version()
        if not self.allow_update:
            log.warning('The remote version is OLDER, you cannot update.')
        else:
            # NOTE this is why we had to standardize repo location on host to: /repo
            log.info('Performing update, calling: /repo/upgrade.sh')
            log.info(f'  you can follow progress in {self.upgrade_log}')
            self.update_in_progress = True
            script_content = f'#!/usr/bin/bash\n /repo/upgrade.sh > {self.upgrade_log} 2>&1\n'
            run_bash(script_content)
            self.check_version()
            self.update_in_progress = False
            self.update_complete = True
            log.info('Update completed')

    def restart_updater_service(self, _params: ParamsType = None):
        """Restart this service"""
        log.info('Restarting this service')
        run_bash('systemctl restart kiosk-updater')


class Webserver():
    """Webserver to receive commands via http requests"""
    max_signals = 2
    log_requests: bool = False  # for debugging; if true, will log all requests

    def __init__(self) -> None:
        log.debug('Initializing Webserver')
        self.bind_ip = '0.0.0.0'
        self.port = WEBSERVER_PORT
        self.loop = asyncio.new_event_loop()
        self.thread: Thread = None  # pyright: ignore[reportAttributeAccessIssue]
        self.api_thread: Thread = None  # pyright: ignore[reportAttributeAccessIssue]
        self.api_q: Queue[tuple[str, ParamsDict]] = Queue(maxsize=10)
        self.webapp: web.Application = None  # pyright: ignore[reportAttributeAccessIssue]
        self.api = APIEffector()
        self.api_map = self.api.get_map()
        self.shutdown_pending = Event()
        self.signal_count = 0
        self.api_q.put(('Check for Update', {}))

        signal.signal(signal.SIGTERM, self.handle_signal)  # type: ignore
        signal.signal(signal.SIGINT, self.handle_signal)  # type: ignore

    # ### Deal with errors and signals

    def handle_loop_exception(self, _loop: Any, context: dict[str, Union[Exception, str]]):
        exc: Exception = context['exception']  # pyright: ignore[reportAssignmentType]
        msg: str = context['message']  # pyright: ignore[reportAssignmentType]
        log.exception(f'Exception encountered in webserver asyncio loop: {msg}', exc_info=exc)

    def handle_signal(self, this_signal: int, _frame):  # type: ignore
        """Callback for when a signal is caught, so we can clean things up before exiting"""
        self.signal_count += 1
        if not self.shutdown_pending.is_set():
            log.info(f'  Caught signal: {this_signal}, stopping things and cleaning up')
            self.stop()
        else:
            log.info(f'  Caught signal: {this_signal} [{self.signal_count} of {self.max_signals}], shutdown/cleanup already in progress')
            if self.signal_count > self.max_signals:
                log.info(f'  Caught more than {self.max_signals} signals, exiting immediately')
                sys.exit(1)

    # ### Webserver Lifecycle

    def start(self):
        """Start the webserver thread
        """
        # Prepare
        try:
            log.info('Starting Webserver')
            self.loop.set_debug(True)
            self.loop.set_exception_handler(self.handle_loop_exception)  # pyright: ignore[reportArgumentType]

            self.webapp = web.Application()
            self.setup_routes(self.webapp)

            # access_log can be set to logging.Logger instance, or None to mute logging
            if self.log_requests:
                runner = web.AppRunner(self.webapp, access_log=log)
            else:
                runner = web.AppRunner(self.webapp, access_log=None)

            self.loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, host=self.bind_ip, port=self.port)
            self.loop.run_until_complete(site.start())
        except Exception:
            log.exception('Unexpected Exception while setting up Webserver')
            try:
                self.loop.stop()
            except BaseException:
                pass
            sys.exit(1)

        # Kick off the threads and loop forever
        try:
            # This thread handles API calls, which are placed into a queue by the other thread
            self.api_thread = Thread(target=self.handle_api, daemon=True)
            self.api_thread.start()
            log.info('API Handler is ready')

            # This thread is the actual webserver
            self.thread = Thread(target=self.loop.run_forever, daemon=True)
            self.thread.start()
            log.info(f'Webserver is ready at: http://{self.bind_ip}:{self.port}')
            # now loop forever, letting the threads do their work
            while not self.shutdown_pending.is_set():
                time.sleep(1)
        except Exception:
            log.exception('Unexpected Exception while starting Webserver thread')
            try:
                self.loop.stop()
            except BaseException:
                pass
            sys.exit(1)

    def stop(self):
        """Stop webserver"""
        # NOTE: "the right way" to do this is to cancel all pending asyncio tasks, then stop the loop
        #   but do NOT call sys.exit(), just let loop.stop() do it's thing and run_forever() will un-block
        log.info('Stopping webserver...')
        self.shutdown_pending.set()
        tasks = asyncio.all_tasks(loop=self.loop)
        log.debug(f'Cancelling {len(tasks)} asyncio tasks')
        for task in tasks:
            log.debug(f'Cancelling task: {task.get_name()}')
            try:
                task.cancel()
            except Exception:
                pass
        self.loop.stop()
        # self.thread.join()
        log.debug('Webserver shutdown complete')

    # ### Configure the webserver

    def setup_routes(self, app: web.Application):
        """Setup webserver routes"""
        app.add_routes([
            web.get('/', self.get_web_home),  # pyright: ignore[reportArgumentType]
            web.get('/api', self.get_web_api),  # pyright: ignore[reportArgumentType]
        ])

    # ### Handle API calls

    def handle_api(self):
        """Runs in thread: process api calls from queue"""
        while not self.shutdown_pending.is_set():
            time.sleep(0.05)
            while not self.api_q.empty():
                action, params = self.api_q.get()

                # Skip execution on dev platform for most actions
                if platform.system() != 'Linux' and action not in self.api.safe_actions:
                    log.warning(f'Will not perform action "{action}" on platform: {platform.system()}')
                    continue

                log.info(f'Handling API action: "{action}"')
                action_func = self.api_map[action]
                try:
                    action_func(params)
                except Exception as ex:
                    msg = f'Unexpected exception while handling api action: {action}: {ex}'
                    log.exception(msg)

    def validate_api(self, action: str, _params: ParamsDict):
        """Validate this action + params combo, raising KeyError if any issues. This should be done before queueing an action"""
        # NOTE we dont currently use any params
        if action not in self.api_map:
            raise KeyError(f'Unknown api action: {action}')

    # ### Handle HTTP requests

    def colorize_content(self, orig_content: str) -> str:
        """Colorize lines of content based on presence of "DEBUG", "WARN", "ERROR", or "LOG" in first 200 chars of each line
            returns lines wrapped in <span> tags, with color in style
        """
        colorized_content = '\n'
        first_n_chars = 200
        for line in orig_content.splitlines():

            # first remove any terminal color codes
            color_names = [a for a in dir(Colors) if not a.startswith('__')]
            for color in color_names:
                code = Colors.__dict__[color]
                if code in line:
                    line = line.replace(code, '')

            # HACK: colorize based on presence of errorlevel text near start of line
            #   this has worked fine for our use case, but is not "the right way"
            this_color = 'white'
            if 'DEBUG' in line[:first_n_chars]:
                this_color = 'cornflowerblue'
            elif 'WARN' in line[:first_n_chars]:
                this_color = 'yellow'
            elif 'ERROR' in line[:first_n_chars]:
                this_color = 'red'
            elif 'LOG' in line[:first_n_chars]:
                this_color = '#707070'
            colorized_content += f'<span style="color: {this_color};">{line}</span>\n'
        return colorized_content

    def get_logs(self, file: str) -> str:
        """Get the content of the log file as a string, as colorized html content"""
        try:
            with open(file, 'rt', encoding='utf-8') as lf:
                content = lf.read()
        except Exception as ex:
            content = ''
            log.error(f'Failed to read log file: {file}, {ex}')

        html_content = self.colorize_content(content)

        return html_content

    def get_js(self) -> str:
        """Get javascript content"""
        with open(Path(__file__).parent.joinpath('kiosk_updater.js'), 'rt', encoding='utf-8') as jsf:
            content = jsf.read()
        return content

    def get_web_home(self, _request: web.Request) -> web.Response:
        """Render the admin page"""

        update_msg = 'No newer version available'
        if self.api.update_complete:
            update_msg = 'Update complete, a host reboot is required'
        elif self.api.update_in_progress:
            update_msg = 'Update in progress, please be patient. You can monitor the update in the log below. Page will refresh every second until complete'
        elif self.api.remote_version > self.api.local_version:
            update_msg = 'A newer version is available, please update'
        elif self.api.remote_version == self.api.local_version:
            update_msg = 'The remote version is the same. You can "update" to reinstall the same version'
        elif self.api.remote_version < self.api.local_version:
            update_msg = 'The remote version is OLDER, you cannot update'

        buttons_content = '\n'
        for action in self.api_map:
            state = ''
            if action == 'Update to Latest' and not self.api.allow_update:
                state = 'disabled'
            encoded_query = urlencode({'action': action})
            buttons_content += f'                <button onclick="window.location.href=\'/api?{encoded_query}\';" {state}>{action}</button>\n'

        script_js = self.get_js()

        page_js = 'scroll_log_to_latest(); handle_refresh();'
        if self.api.update_in_progress:
            page_js += 'wait_for_update();'

        log_content_style = 'left:0; width:100%; padding: 0; margin: 0;'
        log_content_style += ' overflow:scroll; -ms-overflow-style: none; scrollbar-width: none; font-family: \'Courier New\', monospace; font-size: 12px;'
        log_content_style += ' background-color: darkslategrey; white-space: pre-wrap; border-radius: 10px;'

        content = f"""
        <!DOCTYPE html>
        <html>
            <body>
                <div>
                    <h1>Kiosk Host Maintenance Center</h1>
                </div>
                <div>
                <button onclick="navigate_superbird();">Kiosk Superbird Config</button>
                </div>
                <br>

                <div>
                    <label>Repo: {REPO}</label>
                </div>
                <div>
                    <label>Installed: v{self.api.local_version}</label>
                    &nbsp
                    <label>Available: v{self.api.remote_version}</label>
                </div>
                <div>
                    <label>Status: {update_msg}</label>
                </div>

                <h3>Actions</h3>
                <div>
                    {buttons_content}
                </div>

                <h3 style="position:absolute; top: 250px;">Updater Service log:</h3>
                <div id="service_log_content" style="{log_content_style} position:absolute; top: 300px; height: 300px;">
                    {self.get_logs(LOG_FILE)}
                </div>

                <h3 style="position:absolute; top: 600px;">Most recent update log:</h3>
                <div id="upgrade_log_content" style="{log_content_style} position:absolute; top: 650px; bottom: 0px;">
                    {self.get_logs(self.api.upgrade_log)}
                </div>
            </body>
            <script>
                {script_js}
                {page_js}
            </script>
        </html>
        """

        return web.Response(text=content, status=200, content_type='text/html')

    def get_web_api(self, request: web.Request) -> web.Response:
        """Handle API calls"""
        if 'action' not in request.rel_url.query:
            return web.Response(status=400, reason='Missing required url parameter: action')
        action = request.rel_url.query['action']

        log.debug(f'Validating API action: "{action}"')
        try:
            params = proxy_to_dict(request.rel_url.query)
            self.validate_api(action, params)
        except Exception as ex:
            msg = f'Exception while validating api action: {action}: {ex}'
            log.exception(msg)
            return web.Response(status=404, text=msg)

        log.debug(f'Queuing API action: "{action}"')
        self.api_q.put((action, params))

        # HACK clear the updater log now so it will by empty when client refreshes next
        if action == 'Update to Latest':
            truncate_file(self.api.upgrade_log, content='Preparing to update...')

        # HACK we instruct the frontend to refresh after a few seconds, so that the log might show the output of the action we just queued
        refresh_time = 2
        if action == 'Restart Updater Service':
            refresh_time = 5  # give service time to restart
        return web.Response(status=302, headers={'location': f'/?refresh={refresh_time}'})


if __name__ == '__main__':
    try:
        wsrv = Webserver()
    except Exception as ex:
        log.exception(f'Unexpected exception encountered while creating webserver: {ex}')
        sys.exit(1)

    try:
        wsrv.start()  # will block until signal is caught
    except Exception as ex:
        log.exception(f'Unexpected exception encountered while running webserver: {ex}')
        try:
            wsrv.stop()
        except Exception:
            pass
        sys.exit(1)
