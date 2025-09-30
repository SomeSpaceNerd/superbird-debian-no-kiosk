#!/usr/bin/env python3
"""
Render /etc/X11/xorg.conf
"""
from __future__ import annotations

import platform

from typing import Literal, TYPE_CHECKING
from pathlib import Path


if TYPE_CHECKING:
    from config import Config
    from log_manager import LogManager


class XorgRenderer:
    """Render an xorg.conf"""
    rotate_values: dict[str, dict[str, str]] = {
        'CW': {
            'display': 'Clockwise 90deg (Right)',
            'transform': '0 1 0 -1 0 1 0 0 1',
        },
        'CCW': {
            'display': 'Counter-Clockwise 90deg (Left)',
            'transform': '0 -1 1 1 0 0 0 0 1',
        },
        'UD': {
            'display': '180deg (Upside-Down)',
            'transform': '-1 0 1 0 -1 1 0 0 1',
        },
        'None': {
            'display': 'Normal',
            'transform': '',
        },
    }

    def __init__(self, logger: LogManager, config: Config) -> None:
        self.log = logger
        self.config = config
        self.screen_sleep_allow: bool = False
        self.screen_sleep_time: int = 10
        self.screen_rotate: Literal['None', 'CW', 'CCW', 'UD'] = 'None'
        self.file = Path('/etc/X11/xorg.conf')
        if platform.system() == 'Darwin':
            self.file = Path('/tmp/xorg.conf')
        self.reload_config()

    def write(self):
        """Write xorg.conf file from current config"""
        self.log.info(f'Writing xorg.conf: {self.file.absolute()}')
        self.reload_config()
        content = self.render()
        if platform.system() == 'Darwin':
            self.log.debug(content)
        with open(self.file, 'wt', encoding='utf-8') as xf:
            xf.write(content)

    def reload_config(self):
        """Reload values from config"""
        self.screen_sleep_allow: bool = self.config.get('screen_sleep_allow')
        self.screen_sleep_time: int = self.config.get('screen_sleep_time')
        self.screen_rotate: Literal['None', 'CW', 'CCW', 'UD'] = self.config.get('screen_rotate')

    def render(self) -> str:
        """Render the file"""
        if not self.screen_sleep_allow:
            self.screen_sleep_time = 0

        comment = self.rotate_values[self.screen_rotate]['display'].strip()
        transform = self.rotate_values[self.screen_rotate]['transform'].strip()

        transform_line = '# no transform'
        if transform != '':
            transform_line = f'Option      "TransformationMatrix"  "{transform}"  # {comment}'

        rotate_line = '# no rotation'
        if self.screen_rotate != 'None':
            rotate_line = f'Option          "Rotate"    "{self.screen_rotate}"  # {comment}'

        content = f"""
        # Xorg.conf for superbird, rendered automatically by kiosk webserver
        # Portrait orientation (buttons on the right side)

        Section "ServerFlags"
            Option      "BlankTime"     "{self.screen_sleep_time}"
            Option      "StandbyTime"   "{self.screen_sleep_time}"
            Option      "SuspendTime"   "{self.screen_sleep_time}"
            Option      "OffTime"       "{self.screen_sleep_time}"
            Option      "dpms"          "{str(self.screen_sleep_allow)}"
        EndSection

        Section "ServerLayout"
            Identifier      "Simple Layout"
            Screen          "Panel"
            InputDevice     "TouchScreen"   "Pointer"
            InputDevice     "GPIOKeys"      "Keyboard"
            InputDevice     "Rotary"        "Keyboard"
        EndSection

        Section "Screen"
            Identifier      "Panel"
            Monitor         "DefaultMonitor"
            Device          "FramebufferDevice"
            DefaultDepth 24
            DefaultFbBpp 32
            SubSection "Display"
                Depth 32
                Virtual 480 800
                ViewPort 0 0
                Modes "480x800"
            EndSubSection
        EndSection

        Section "Device"
            Identifier      "FramebufferDevice"
            Driver          "fbdev"
            Option          "fbdev"     "/dev/fb0"
            {rotate_line}
        EndSection

        Section "Monitor"
            Identifier      "DefaultMonitor"
            Option          "DPMS"      "{str(self.screen_sleep_allow)}"
        EndSection

        # All the device buttons are part of event0, which appears as a keyboard
        # 	buttons along the edge are: 1, 2, 3, 4, m
        # 	next to the knob: ESC
        #	knob click: Enter
        Section "InputDevice"
            Identifier  "GPIOKeys"
            Driver      "libinput"
            Option      "Device"        "/dev/input/event0"
        EndSection

        # Turning the dial is a separate device, event1, which also appears as a keyboard
        #	turning the knob corresponds to the left and right arrow keys
        Section "InputDevice"
            Identifier  "Rotary"
            Driver      "libinput"
            Option      "Device"        "/dev/input/event1"
        EndSection

        # The touchscreen is event3
        Section "InputDevice"
            Identifier  "TouchScreen"
            Driver      "libinput"
            Option      "Device"        "/dev/input/event3"
            Option      "Mode"          "Absolute"
            Option      "GrabDevice"    "1"
            {transform_line}
        EndSection
        """

        # strip leading indent
        clines: list[str] = []
        for line in content.splitlines():
            clines.append(line.removeprefix('        '))
        content = '\n'.join(clines)
        return content
