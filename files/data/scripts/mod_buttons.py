#!/usr/bin/env python3
"""
Buttons monitoring, to integrate with Home Assistant
"""

from __future__ import annotations

import time
import struct
import platform

from dataclasses import dataclass
from typing import Callable

from queue import Queue
from threading import Thread
from threading import Event as ThreadEvent

from config import Config
from log_manager import LogManager
from mod_common import ModService
from ha_manager import HAManager, BufferedLight


# All the device buttons are part of event0, which appears as a keyboard
# 	buttons along the edge are: 1, 2, 3, 4, m
# 	next to the knob: ESC
# knob click: Enter
# Turning the knob is a separate device, event1, which also appears as a keyboard
# turning the knob corresponds to the left and right arrow keys


# https://github.com/torvalds/linux/blob/v5.5-rc5/include/uapi/linux/input.h#L28
# long int, long int, unsigned short, unsigned short, unsigned int
EVENT_FORMAT = 'llHHI'
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)

# hide warning when using HA api because self-signed cert
# urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


@dataclass
class DeviceEvent:
    device: str
    event: str


class ButtonListener:
    """Listen to button inputs"""
    # for event0, these are the keycodes for buttons
    button_codes_map: dict[int, str] = {
        2: '1',
        3: '2',
        4: '3',
        5: '4',
        50: 'm',
        28: 'ENTER',
        1: 'ESC',
    }
    # for event1, when the knob is turned it is always keycode 6, but value changes on direction
    knob_left = 4294967295  # actually -1 but unsigned int so wraps around
    knob_right = 1

    def __init__(self, logger: LogManager, watchers: dict[str, Callable[[str], None]]) -> None:
        self.log = logger
        self.watchers = watchers
        # HACK need pointer to the callback of first element for doing fake events
        self.callback: Callable[[str], None] = None  # pyright: ignore[reportAttributeAccessIssue]
        for _key, cb in self.watchers.items():
            self.callback = cb
            break
        self.stopper = ThreadEvent()
        self.event_q: Queue[DeviceEvent] = Queue()
        self.threads: list[Thread] = []

    def start(self):
        """Start"""
        if platform.system() == 'Darwin':
            self.log.warning('platform.system() == Darwin, so no listener threads will be created')
            self.log.warning('  you can simulate key events from the webui')
            self.log.warning('  all fake events will come appear to come from /dev/input/event0')
            self.log.warning('  all fake events will be passed to the callback for the first watcher given only')
        else:
            for device in self.watchers:
                self.log.info(f'Starting listener for device: {device}')
                self.threads.append(Thread(target=self.listen, args=[device,], daemon=True))
        self.log.info('Starting event handler')
        self.threads.append(Thread(target=self.handle_events, daemon=True))
        for thr in self.threads:
            thr.start()

    def stop(self):
        """Stop"""
        self.stopper.set()
        while not self.event_q.empty():
            self.event_q.get()

    def cleanup(self):
        """Cleanup"""
        self.threads = []
        self.event_q = Queue()

    def submit_fake(self, key: str):
        """submit a fake event"""
        self.log.info(f'Simulating a key press: {key}')
        valid_keys = ['1', '2', '3', '4', 'm', 'ENTER', 'ESC', 'LEFT', 'RIGHT']
        if key not in valid_keys:
            self.log.warning(f'Simulating a key press not in button_codes_map: {key}')
        self.event_q.put(DeviceEvent('/dev/input/event0', key))

    def handle_events(self):
        """Process the event queue and pass them to registered callbacks"""
        self.log.debug('Event handler loop started')
        while not self.stopper.is_set():
            while not self.event_q.empty():
                if self.stopper.is_set():
                    break
                evt: DeviceEvent = self.event_q.get()
                if platform.system() == 'Darwin':
                    callback = self.callback
                else:
                    callback = self.watchers[evt.device]
                callback(evt.event)
                time.sleep(0.1)
            if self.stopper.is_set():
                break
            time.sleep(0.1)
        self.log.debug('Event handler loop ended')

    def listen(self, device: str):
        """
        To run in thread, listen for events and call handle_buttons if applicable
        """
        self.log.info(f'Listening for events from: {device}')
        with open(device, "rb") as in_file:
            event = in_file.read(EVENT_SIZE)
            while event and not self.stopper.is_set():
                if self.stopper.is_set():
                    break
                (_sec, _usec, etype, code, value) = struct.unpack(EVENT_FORMAT, event)

                event_str = self.translate_event(etype, code, value)
                self.event_q.put(DeviceEvent(device, event_str))
                if self.stopper.is_set():
                    break
                event = in_file.read(EVENT_SIZE)

    def translate_event(self, etype: int, code: int, value: int) -> str:
        """
        Translate combination of type, code, value into string representing button pressed
        """
        # self.logger.info(f'Event: type: {etype}, code: {code}, value:{value}')
        if etype == 1 and value == 1:
            # button press
            if code in self.button_codes_map:
                return self.button_codes_map[code]
        if etype == 2:
            if code == 6:
                # knob turn
                if value == self.knob_right:
                    return 'RIGHT'
                if value == self.knob_left:
                    return 'LEFT'
        return 'UNKNOWN'


class Buttons(ModService):
    """Handle input from events on spotify car thing (superbird)"""
    dev_buttons = '/dev/input/event0'
    dev_knob = '/dev/input/event1'

    def __init__(self, config: Config, logger: LogManager) -> None:
        self.config = config
        self.log = logger
        self.log.info('Initializing Buttons service')
        self.ha: HAManager = None  # pyright: ignore[reportAttributeAccessIssue]
        self.room_light = self.config.get('room_light')
        self.level_increment = self.config.get('level_increment')
        self.listener: ButtonListener = None  # pyright: ignore[reportAttributeAccessIssue]
        self.light_buffer: BufferedLight = None  # pyright: ignore[reportAttributeAccessIssue]

    def start(self):
        """Start"""
        self.log.info('Starting Buttons Service')
        try:
            self.ha = HAManager(config=self.config, logger=self.log)
            self.ha.start()
            if self.ha is None:  # type: ignore
                raise ConnectionError('Failed to connect to Home Assistant')
            self.light_buffer = BufferedLight(self.log, self.ha, self.room_light)
            self.light_buffer.start()
            self.log.info('Setting up button listener')
            self.listener = ButtonListener(logger=self.log, watchers={
                self.dev_buttons: self.handle_button,
                self.dev_knob: self.handle_button,
            })
            self.listener.start()
            self.log.debug('Successfully setup button listener')
        except Exception as ex:
            self.log.exception(f'Unexpected exception while starting Buttons service: {ex}')

    def stop(self):
        """Stop"""
        self.log.info('Stopping Buttons service')
        if self.light_buffer is not None:  # pyright: ignore[reportUnnecessaryComparison]
            self.light_buffer.stop()
        if self.listener is not None:  # pyright: ignore[reportUnnecessaryComparison]
            self.listener.stop()
        if self.ha is not None:  # pyright: ignore[reportUnnecessaryComparison]
            self.ha.stop()

    def cleanup(self):
        """Cleanup"""
        if self.listener is not None:  # pyright: ignore[reportUnnecessaryComparison]
            self.listener.cleanup()
        self.listener = None  # pyright: ignore[reportAttributeAccessIssue]
        self.ha = None  # pyright: ignore[reportAttributeAccessIssue]

    def start_listener(self):
        """Start button listener"""

    def get_light_level(self) -> int:
        """Get current light level"""
        return self.light_buffer.get()

    def set_light_level(self, level: int):
        """Set the level of the light"""
        self.light_buffer.set(level)

    def light_lower(self):
        """Lower level of the light"""
        current_level = self.get_light_level()
        new_level = current_level - self.level_increment
        new_level = max(new_level, 0)
        if new_level < current_level:
            self.set_light_level(new_level)

    def light_raise(self):
        """Raise level of the light"""
        current_level = self.get_light_level()
        new_level = current_level + self.level_increment
        new_level = min(new_level, 255)
        if new_level > current_level:
            self.set_light_level(new_level)

    def call_scene(self, scene: str):
        """Call a scene"""
        self.log.info(f'Recalling: {scene}')
        self.ha.recall(scene)

    def handle_button(self, pressed_key: str):
        """Handle a button press"""
        try:
            if pressed_key in ['1', '2', '3', '4', 'm', 'ENTER', 'ESC', 'LEFT', 'RIGHT']:
                self.log.debug(f'Pressed button: {pressed_key}')

                # check for presets
                if pressed_key in ['1', '2', '3', '4', 'm']:
                    if pressed_key == 'm':
                        pressed_key = '5'
                    cfg_name = f'room_scene_{pressed_key}'
                    room_scene = self.config.get(cfg_name)
                    self.call_scene(room_scene)

                elif pressed_key in ['ESC', 'ENTER', 'LEFT', 'RIGHT']:
                    if pressed_key == 'ENTER':
                        self.light_buffer.toggle()
                    elif pressed_key == 'LEFT':
                        self.light_lower()
                    elif pressed_key == 'RIGHT':
                        self.light_raise()
                    if pressed_key == 'ESC':
                        esc_scene = self.config.get('esc_scene')
                        self.call_scene(esc_scene)
        except Exception as ex:
            self.log.exception(f'Exception while handling a button press: {ex}')
