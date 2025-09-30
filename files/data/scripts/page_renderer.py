#!/usr/bin/env python3
"""
Webserver Page Renderer
"""
from __future__ import annotations


import os
import subprocess
import platform


from urllib.parse import urlencode
from typing import TYPE_CHECKING, Union
from pathlib import Path

import psutil
from aiohttp import web
from yattag import Doc

from mod_common import get_version

if TYPE_CHECKING:
    from config import Config
    from log_manager import LogManager
    from mod_webserver import WebServer


def get_command_output(cmd: list[str], pipe_input: Union[str, None] = None) -> str:
    if pipe_input is not None:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, input=pipe_input, encoding='utf-8', universal_newlines=True)
    else:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, universal_newlines=True)
    return proc.stdout


class PageRenderer:
    """Render web pages"""

    def __init__(self, logger: LogManager, config: Config, port: int, webserver: WebServer) -> None:
        self.log = logger
        self.config = config
        self.base_dir = Path(os.path.realpath(__file__)).parent
        self.config = config
        self.port = port
        self.webserver = webserver
        self.version = get_version()
        self.log.debug('Initializing Page Renderer')
        self.js_content = None
        self.js_file = self.base_dir.joinpath('kiosk.js')
        self.novncjs_file = self.base_dir.joinpath('novnc.js')
        self.css_file = self.base_dir.joinpath('kiosk.css')
        self.icon_file = self.base_dir.joinpath('favicon.png')
        self.css_content = None
        self.reload_time = 8
        if platform.system() == 'Darwin':
            self.reload_time = 2

    # #### Content helpers

    def colorize_content(self, orig_content: str) -> str:
        """Colorize lines of content based on presence of "DEBUG", "WARN", "ERROR", or "LOG" in first 200 chars of each line
            returns lines wrapped in <span> tags, with color in style
        """
        colorized_content = '\n'
        first_n_chars = 200
        for line in orig_content.splitlines():
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

    def get_content_novncscript(self) -> str:
        """Render the novnc js module import"""
        # NOTE based on this: https://github.com/novnc/noVNC/blob/master/vnc_lite.html
        vnc_pass: str = self.config.get("vnc_password")
        if platform.system() == 'Darwin':
            vnc_host = '"wallthing-4"'
        else:
            vnc_host = 'window.location.hostname'

        with open(self.novncjs_file, 'rt', encoding='utf-8') as jsf:
            js_content = jsf.read()

        newcontent: list[str] = ['<script type="module" crossorigin="anonymous">']
        for line in js_content.splitlines():
            if line.startswith('const VNC_PASSWORD'):
                newcontent.append(f'    const VNC_PASSWORD = "{vnc_pass}";  // rewritten by PageRenderer.get_content_novncscript()')
            elif line.startswith('const VNC_HOST'):
                newcontent.append(f'    const VNC_HOST = {vnc_host};  // rewritten by PageRenderer.get_content_novncscript()')
            else:
                newcontent.append('    ' + line)
        newcontent.append('</script>')

        js_content = '\n'.join(newcontent)
        return js_content

    def get_content_log(self, service: str) -> str:
        """Get content of given log"""
        try:
            if service == 'Kiosk':
                with open(self.log.log_script, 'rt', encoding='utf-8') as kscrl:
                    content = kscrl.read()
            elif service == 'Browser Process':
                with open(self.log.log_chromium, 'rt', encoding='utf-8') as chrfc:
                    content = chrfc.read()
            elif service == 'Running Processes':
                raminfo = psutil.virtual_memory()
                cpu_usage = int(psutil.cpu_percent(interval=0.5))
                ram_usage = int(raminfo.percent)
                ram_used = int(raminfo.used / (1024 * 1024))
                ram_total = int(raminfo.total / (1024 * 1024))
                content = f'CPU Usage: {cpu_usage}%\n'
                content += f'RAM Usage: {ram_usage}%\n'
                content += f'RAM Used : {ram_used}MB / {ram_total}MB\n'
                content += '\n'
                content += 'Processes: \n'
                if platform.system() == 'Darwin':
                    content += get_command_output(['ps', 'aux', '-r'])  # macos is a special unicorn
                else:
                    content += get_command_output(['ps', 'aux', '--sort=-pcpu'])
            else:
                service = service.lower()
                if not service.endswith('.service'):
                    service += '.service'
                content = get_command_output(['journalctl', '--no-tail', '-u', service])

        except Exception as ex:
            content = f'ERROR: Could not get log for {service}: {ex}\n'
            self.log.error(f'Could not get log for {service}: {ex}')

        return content

    # #### Rendering helpers

    def render_pagelinks(self) -> str:
        """Render the shortcuts for each page"""
        static_links = {
            '/': 'Home',
            '/devtools': 'Browser DevTools'
        }
        log_names = ['Kiosk', 'Browser Process', 'Backlight', 'USBGadget', 'VNC', 'Websockify', 'Running Processes']
        doc, tag, text = Doc().tagtext()
        with tag('div'):
            for key, value in static_links.items():
                with tag('div', klass='nav_button', onclick=f'window.location.href="{key}";'):
                    text(value)
                doc.stag('br')
            doc.stag('br')
            with tag('h3'):
                text('Logs:')
            for svc in log_names:
                param = urlencode({
                    'service': svc
                })
                with tag('div', klass='nav_button', onclick=f'window.location.href="/logs?{param}";'):
                    text(svc)
                doc.stag('br')

        return doc.getvalue()

    def render_full_page(self, body_content: str, entrypoint: str = '') -> str:
        """Render a full page, including all the static stuff, putting given content in the body
            optionally provide an entrypoint (snippet of js to run after page is loaded)
                ex: entrypoint='main();'
        """
        if entrypoint == '':
            entrypoint = 'console.log("No entrypoint specified");'

        doc, tag, text = Doc().tagtext()
        doc.asis('<!DOCTYPE html>')
        with tag('html'):
            with tag('head'):
                with tag('link', rel='stylesheet', href='/style.css', type='text/css'):
                    pass
            with tag('body'):
                with tag('h1', id="device_name"):
                    text('Device:')
                pagelinks = self.render_pagelinks()
                with tag('div', klass='float-container'):
                    with tag('div', klass='float-child', id='body_navbar'):
                        doc.asis(pagelinks)
                    with tag('div', klass='float-child', id='body_content'):
                        doc.asis(body_content)
            with tag('label', id='version_label'):
                text('Version: unknown')
            with tag('div', id='page_overlay'):
                with tag('div', id='page_overlay_container'):
                    with tag('h1', id='page_overlay_title'):
                        text('Loading...')
                    with tag('label', id='page_overlay_text'):
                        text('Please be patient')
            with tag('script', src='/script.js'):
                pass
            with tag('script'):
                doc.asis(entrypoint)

        return doc.getvalue()

    # #### Request handlers

    # /script.js
    def get_web_js(self, _request: web.Request) -> web.Response:
        """Read, adjust, and return the javascript, rewriting WEBSERVER_PORT"""
        with open(self.js_file, 'rt', encoding='utf-8') as jsf:
            js_content = jsf.read()
        newcontent: list[str] = []
        for line in js_content.splitlines():
            if line.startswith('const WEBSERVER_PORT'):
                newcontent.append(f'const WEBSERVER_PORT = {self.port};  // rewritten by PageRenderer.get_web_js()')
            elif line.startswith('const RELOAD_TIME'):
                newcontent.append(f'const RELOAD_TIME = {self.reload_time};  // rewritten by PageRenderer.get_web_js()')
            elif line.startswith('const VERSION'):
                newcontent.append(f'const VERSION = "{self.version}";  // rewritten by PageRenderer.get_web_js()')
            else:
                newcontent.append(line)
        js_content = '\n'.join(newcontent)
        return web.Response(text=js_content, status=200, content_type='text/javascript')

    # /style.css
    def get_web_css(self, _request: web.Request) -> web.Response:
        """Read and return the style sheet"""
        with open(self.css_file, 'rt', encoding='utf-8') as jsf:
            css_content = jsf.read()
        return web.Response(text=css_content, status=200, content_type='text/css')

    # /favicon.ico
    def get_web_favicon(self, _request: web.Request) -> web.Response:
        """Read and return the favicon"""
        with open(self.icon_file, 'rb') as jsf:
            css_content = jsf.read()
        return web.Response(body=css_content, status=200, content_type='image/png')

    # /
    def get_web_home(self, _request: web.Request) -> web.Response:
        """Render and return the home page"""
        configform = self.config.renderer.render_form()
        doc, tag, text = Doc().tagtext()
        with tag('div'):
            with tag('h2'):
                text('Device Screen')

            bignum = 600
            smallnum = bignum * 0.6

            vnc_style = f'height: {bignum}px; width: {smallnum}px'
            if self.config.get('screen_rotate') in ['CW', 'CCW']:
                vnc_style = f'height: {smallnum}px; width: {bignum}px'

            with tag('div', id='vnc_client_screen', style=vnc_style):
                pass
            with tag('h2'):
                text('Simulate Buttons')
            with tag('div'):
                with tag('div', klass='buttons_group'):
                    with tag('div'):
                        buttons = {
                            'Button': 'ESC',
                            'Knob Left': 'LEFT',
                            'Knob Click': 'ENTER',
                            'Knob Right': 'RIGHT'
                        }
                        for name, key in buttons.items():
                            with tag('button', type='button', klass='device_button', onclick=f'simulate_key("{key}");'):
                                text(name)
                    with tag('div'):
                        buttons = {
                            '1': '1',
                            '2': '2',
                            '3': '3',
                            '4': '4',
                            '5': 'm'
                        }
                        for name, key in buttons.items():
                            with tag('button', type='button', klass='device_button', onclick=f'simulate_key("{key}");'):
                                text(name)

            doc.stag('br')
            with tag('h2'):
                text('Configuration')
            with tag('div'):
                with tag('label', id='config_status_label'):
                    text('Status: Ready')
                with tag('div'):
                    doc.asis(configform)
            with tag('h2'):
                text('Maintenance')
            with tag('div'):
                for action in ['Reboot Superbird', 'Clear Browser Data', 'Restart Kiosk Service']:
                    with tag('button', type='button', klass='maint_button', onclick=f'maint_action("{action}");'):
                        text(action)
                with tag('button', type='button', klass='maint_button', onclick='window.open(window.location.protocol + "//" + window.location.hostname + ":9090" + "/");'):
                    text('Host Maintenance')
            doc.stag('br')
            with tag('div'):
                doc.asis('&nbsp')
        doc.asis(self.get_content_novncscript())
        body_content = doc.getvalue()
        content = self.render_full_page(body_content, entrypoint='config_entrypoint();')
        return web.Response(text=content, status=200, content_type='text/html')

    # /logs
    def get_web_logs(self, request: web.Request) -> web.Response:
        """Render and return the logs page"""
        if 'service' not in request.rel_url.query:
            return web.Response(status=400, reason='Missing required url parameter: service')
        service = request.rel_url.query['service']

        log_content = self.get_content_log(service)
        log_content = self.colorize_content(log_content)

        doc, tag, text = Doc().tagtext()
        with tag('h2'):
            text(f'Logs: {service}')
        with tag('div', klass='log_content', id='log_content'):
            doc.asis(log_content)
        body_content = doc.getvalue()

        content = self.render_full_page(body_content, entrypoint='logs_entrypoint();')
        return web.Response(text=content, status=200, content_type='text/html')

    # /devtools
    def get_web_devtools(self, _request: web.Request) -> web.Response:
        """Get the chromium devtools page"""
        doc, tag, text = Doc().tagtext()
        with tag('div'):
            with tag('h2'):
                text('Browser DevTools')
            with tag('div', id="browser_devtools"):
                pass
            with tag('div'):
                doc.asis('&nbsp')
        body_content = doc.getvalue()
        content = self.render_full_page(body_content, entrypoint='devtools_entrypoint();')
        return web.Response(text=content, status=200, content_type='text/html')
