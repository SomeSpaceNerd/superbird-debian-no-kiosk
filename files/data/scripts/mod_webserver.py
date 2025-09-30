#!/usr/bin/env python3
"""
Webserver and API
"""
from __future__ import annotations

import os
import time
import sys
import json
import asyncio
import subprocess
import platform

from pathlib import Path
from threading import Thread
from typing import Any, Union, TYPE_CHECKING
from aiohttp import web


from mod_common import ModService, kill_event_loop
from page_renderer import PageRenderer
from xorg_renderer import XorgRenderer

from config import Config

if TYPE_CHECKING:
    from log_manager import LogManager
    from mod_buttons import Buttons
    from mod_chromium import Chromium


class WebServer(ModService):
    """Webserver and API"""
    log_requests: bool = False  # for debugging; if true, will log all requests

    def __init__(self, logger: LogManager, config: Config, buttons: Buttons, chromium: Chromium) -> None:
        self.log = logger
        self.config = config
        self.buttons = buttons
        self.chromium = chromium
        self.bind_ip = '0.0.0.0'
        self.port = 80
        if platform.system() == 'Darwin':
            self.novnc_path = Path().cwd().joinpath('novnc')
        else:
            self.novnc_path = Path('/scripts').joinpath('novnc')
        self.log.debug('Initializing Webserver')
        self.loop = asyncio.new_event_loop()
        self.page_renderer = PageRenderer(logger=self.log, config=self.config, port=self.port, webserver=self)
        self.xorg = XorgRenderer(logger=self.log, config=self.config)
        self.messages: list[dict[str, Any]] = []  # holds any messages destined for the frontend, newest last
        self.thread: Thread = None  # pyright: ignore[reportAttributeAccessIssue]
        self.webapp: web.Application = None  # pyright: ignore[reportAttributeAccessIssue]

    def handle_loop_exception(self, _loop: asyncio.EventLoop, context: dict[str, Union[Exception, str]]):
        exc: Exception = context['exception']  # pyright: ignore[reportAssignmentType]
        msg: str = context['message']  # pyright: ignore[reportAssignmentType]
        self.log.exception(f'Exception encountered in webserver asyncio loop: {msg}', exc_info=exc)

    # Mod lifecycle

    def start(self):
        """Start the webserver thread
        """
        try:
            self.log.info('Starting Webserver')
            self.loop.set_debug(True)
            self.loop.set_exception_handler(self.handle_loop_exception)  # pyright: ignore[reportArgumentType]

            self.webapp = web.Application()
            self.setup_routes(self.webapp)

            # access_log can be set to logging.Logger instance, or None to mute logging
            #   NOTE: you must use self.log.log so that you point it to a real logger instance
            if self.log_requests:
                runner = web.AppRunner(self.webapp, access_log=self.log.log)
            else:
                runner = web.AppRunner(self.webapp, access_log=None)

            self.loop.run_until_complete(runner.setup())
            site = web.TCPSite(runner, host=self.bind_ip, port=self.port)
            self.loop.run_until_complete(site.start())
        except Exception:
            self.log.exception('Unexpected Exception while setting up Webserver')
            try:
                self.loop.stop()
            except BaseException:
                pass
            sys.exit(1)

        try:
            self.thread = Thread(target=self.loop.run_forever, daemon=True)
            self.thread.start()
            self.log.info(f'Webserver is ready at: http://{self.bind_ip}:{self.port}')
        except Exception:
            self.log.exception('Unexpected Exception while starting Webserver thread')
            try:
                self.loop.stop()
            except BaseException:
                pass
            sys.exit(1)

    def stop(self):
        """Stop webserver"""
        # NOTE: "the right way" to do this is to cancel all pending asyncio tasks, then stop the loop
        #   but do NOT call sys.exit(), just let loop.stop() do it's thing and run_forever() will un-block
        self.log.info('Stopping webserver...')
        kill_event_loop(self.loop)
        self.log.debug('Webserver shutdown complete')

    def cleanup(self):
        """Perform cleanup tasks"""
        self.thread = None  # pyright: ignore[reportAttributeAccessIssue]
        self.webapp = None  # pyright: ignore[reportAttributeAccessIssue]
        self.messages = []
        self.loop = asyncio.new_event_loop()

    # Webserver paths

    def setup_routes(self, app: web.Application):
        """Setup webserver routes"""
        app.add_routes([
            web.get('/', self.page_renderer.get_web_home),  # pyright: ignore[reportArgumentType]
            web.get('/favicon.ico', self.page_renderer.get_web_favicon),  # pyright: ignore[reportArgumentType]
            web.get('/logs', self.page_renderer.get_web_logs),  # pyright: ignore[reportArgumentType]
            web.get('/script.js', self.page_renderer.get_web_js),  # pyright: ignore[reportArgumentType]
            web.get('/style.css', self.page_renderer.get_web_css),  # pyright: ignore[reportArgumentType]
            web.get('/getconfig', self.get_web_getconfig),  # pyright: ignore[reportArgumentType]
            web.post('/setconfig', self.post_web_setconfig),  # pyright: ignore[reportArgumentType]
            web.get('/simulatekey', self.get_web_simulatekey),  # pyright: ignore[reportArgumentType]
            web.get('/maintenance', self.get_web_maintenance),  # pyright: ignore[reportArgumentType]
            web.get('/novnc/{tail:.*}', self.get_novnc_files),  # pyright: ignore[reportArgumentType]
            web.get('/devtools', self.page_renderer.get_web_devtools),  # pyright: ignore[reportArgumentType]
        ])

    # Handle Requests - Configuration
    def get_novnc_files(self, request: web.Request) -> web.Response:
        """Get static files needed for noVNC client"""
        content_types: dict[str, str] = {
            '.css': 'text/css',
            '.html': 'text/html',
            '.ico': 'image/vnd.microsoft.icon',
            '.js': 'text/javascript',
            '.json': 'application/json',
            '.png': 'image/png',
            '.svg': 'image/svg+xml',
            '.ttf': 'font/ttf',
            '.woff': 'font/woff',
        }
        tail = request.match_info['tail']
        local_file = self.novnc_path.joinpath(tail)
        if not local_file.is_file():
            return web.Response(text=f'Not found: {local_file.absolute()}', status=404)
        content = 'Not Implemented'
        content_type = 'text/plain'
        if local_file.suffix not in content_types:
            return web.Response(text=f'Unexpected content suffix: {local_file.name}', status=500)
        content_type = content_types[local_file.suffix]
        if local_file.suffix in ['.css', '.html', '.js', 'json']:
            with open(local_file, 'rt', encoding='utf-8') as lf:
                content = lf.read()
        else:
            with open(local_file, 'rb') as lf:
                content = lf.read()
        return web.Response(body=content, status=200, content_type=content_type)

    def get_web_getconfig(self, _request: web.Request) -> web.Response:
        """Get config as JSON config"""
        content = self.config.to_json()
        if platform.system() == 'Darwin':
            self.log.debug(json.dumps(json.loads(content), indent=4))
        return web.Response(text=content, status=200, content_type='text/json')

    def _restart_services(self, changed_params: list[str]):
        """Restart any services impacted by any changed config parameters"""
        time.sleep(0.2)
        self.log.info('Restarting services')

        if len(changed_params) == 0:
            self.log.debug('No config parameters were changed, no restarts are needed')
            return
        self.log.debug(f'Changed config parameters: {",".join(changed_params)}')

        # Buttons
        restart_needed = False
        restart_if_changed = ['ha_server', 'ha_token', 'room_light', 'level_increment', 'esc_scene']
        for keyname in changed_params:
            if keyname in restart_if_changed:
                self.log.debug(f'Config param "{keyname}" changed')
                restart_needed = True
                break
            if 'room_scene_' in keyname:
                self.log.debug(f'Config param "{keyname}" changed')
                restart_needed = True
                break
        if restart_needed:
            self.log.info('A restart is required for buttons')
            self.buttons.restart()

        # Browser
        restart_needed = False
        restart_if_changed = ['browser_scale', 'screen_sleep_allow', 'screen_sleep_time', 'screen_rotate']
        for keyname in restart_if_changed:
            if keyname in changed_params:
                self.log.debug(f'Config param "{keyname}" changed')
                restart_needed = True
                break

        if restart_needed:
            self.log.info('A restart is required for chromium')
            self.chromium.restart()
        else:
            if 'url' in changed_params:
                self.log.info('Applying URL update without restarting chromium')
                self.chromium.chromium_navigate(self.config.get('url'))

        # VNC
        if 'vnc_password' in changed_params:
            if platform.system() != 'Darwin':
                self.log.info('Config parameter "vnc_password" changed, restarting vnc and websockify services')
                subprocess.run(['systemctl', 'restart', 'vnc'], check=False)
                subprocess.run(['systemctl', 'restart', 'websockify'], check=False)

        # Screen Brightness (does not require restart of xorg)
        if 'screen_brightness' in changed_params:
            if platform.system() != 'Darwin':
                self.log.info('Config parameter "screen_brightness" changed, restarting backlight service')
                subprocess.run(['systemctl', 'restart', 'backlight'], check=False)

    def schedule_restart_services(self, changed_params: list[str]):
        """Schedule services to restart in 1 second on another thread, so this one can continue"""
        thr = Thread(target=self._restart_services, args=[changed_params,])
        thr.start()

    async def post_web_setconfig(self, request: web.Request) -> web.Response:
        """Set config from html form submit"""
        payload = await request.text()
        payload_json = self.config.config_urlquery_to_json(payload)

        if platform.system() == 'Darwin':
            self.log.debug(json.dumps(json.loads(payload_json), indent=4))

        try:
            newconfig = Config(self.log)
            newconfig.from_json(payload_json)
        except Exception:
            self.log.exception('Exception occured while updating config')
            return web.Response(status=302, headers={'location': '/?result=failed'})

        self.config.clear_changes()
        self.config.from_json(payload_json)
        changed_params = self.config.get_changes()
        self.config.clear_changes()
        self.config.save()

        need_xorg_write = False
        for param in changed_params:
            if param in ['screen_sleep_allow', 'screen_sleep_time', 'screen_rotate']:
                self.log.info(f'Config param "{param}" changed, rewriting /etc/X11/xorg.conf')
                need_xorg_write = True
        if need_xorg_write:
            self.xorg.write()

        if 'vnc_password' in changed_params:
            if platform.system() != 'Darwin':
                vnc_password = self.config.get('vnc_password')
                with open('/tmp/doit.sh', 'wt', encoding='utf-8') as df:
                    df.write(f'vncpasswd -f <<<"{vnc_password}" > /etc/vnc/vnc_passwd\n')
                subprocess.run(['bash', '/tmp/doit.sh'], check=False)

        if 'screen_brightness' in changed_params:
            # NOTE: brightness value is strange so we must translate
            #   0 = off
            #   1 = 100% brightness
            #   255 = 0% brightness
            new_brightness = int(self.config.get('screen_brightness'))
            if new_brightness != 0:
                new_brightness = 256 - new_brightness

            new_brightness = max(new_brightness, 0)
            new_brightness = min(new_brightness, 255)

            # TODO right now there is only one script that uses this config file, but in the future we may need to render many values instead of just the one
            with open(self.config.config_script_file, 'wt', encoding='utf-8') as csf:
                csf.write(f'BRIGHTNESS="{new_brightness}"\n')

        if platform.system() == 'Darwin':
            self.log.debug(json.dumps(json.loads(self.config.to_json()), indent=4))

        self.schedule_restart_services(changed_params)

        return web.Response(status=302, headers={'location': '/?result=success'})

    def get_web_simulatekey(self, request: web.Request) -> web.Response:
        """Simulate a key press"""
        if 'key' not in request.rel_url.query:
            return web.Response(status=400, reason='Missing required url parameter: key')
        key = request.rel_url.query['key']
        self.buttons.listener.submit_fake(key)
        return web.Response(status=200)

    def get_web_maintenance(self, request: web.Request) -> web.Response:
        """Perform a maintenance action"""
        if 'action' not in request.rel_url.query:
            return web.Response(status=400, reason='Missing required url parameter: action')
        action = request.rel_url.query['action']

        if action == 'Reboot Superbird':
            if platform.system() != 'Linux':
                self.log.warning(f'NOT rebooting on platform: {platform.system()}')
            else:
                self.log.info('Rebooting superbird')
                os.system('reboot')

        elif action == 'Clear Browser Data':
            self.log.info('Clearing browser data (cookies, cache, etc)')
            if platform.system() != 'Linux':
                self.log.warning(f'Not clearing browser data on platform: {platform.system()}')
            else:
                self.chromium.clear_data()

        elif action == 'Restart Kiosk Service':
            self.log.info('Restarting kiosk service')
            if platform.system() != 'Linux':
                self.log.warning(f'Not restarting kiosk service on platform: {platform.system()}')
            else:
                os.system('systemctl restart kiosk')

        else:
            self.log.warning(f'Unknown maintenance action: {action}')
            return web.Response(status=404, text=f'Unknown maintenance action: {action}')

        return web.Response(status=200)
