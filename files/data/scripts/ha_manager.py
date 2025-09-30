#!/usr/bin/env python3
"""
Buttons monitoring, to integrate with Home Assistant
"""
# https://stackoverflow.com/questions/5060710/format-of-dev-input-event
# https://homeassistantapi.readthedocs.io/en/latest/usage.html
# https://homeassistantapi.readthedocs.io/en/latest/api.html#homeassistant_api.Client
# https://github.com/GrandMoff100/HomeAssistantAPI

from __future__ import annotations

import time

from typing import TYPE_CHECKING, Union
from threading import Thread
from threading import Event as ThreadEvent

import urllib3

from homeassistant_api import Client, Domain, errors

from config import Config


if TYPE_CHECKING:
    from log_manager import LogManager


# prevent warnings about insecure connections to HA if using self-signed cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class HAManager:
    """Manage connection with HomeAssistant"""
    retry_sleep = 4  # seconds, how long to wait before trying again

    def __init__(self, config: Config, logger: LogManager) -> None:
        self.config = config
        self.log = logger
        self.ha_server = config.get('ha_server')
        self.ha_token = config.get('ha_token')
        self.log.debug('Initializing HomeAssistant Manager')
        self.client: Client = None  # pyright: ignore[reportAttributeAccessIssue]
        self.lights: Domain = None  # pyright: ignore[reportAttributeAccessIssue]
        self.scenes: Domain = None  # pyright: ignore[reportAttributeAccessIssue]
        self.scripts: Domain = None  # pyright: ignore[reportAttributeAccessIssue]
        self.automations: Domain = None  # pyright: ignore[reportAttributeAccessIssue]
        self.connected: bool = False

    def start(self):
        """Start HA connection"""
        self.connect()

    def connect(self):
        """Attempt the connection repeatedly until successful"""
        self.log.debug(f'Connecting to HomeAssistant at: {self.ha_server}')
        if self.ha_token in ['', 'insert-token-here']:
            self.log.warning('Will not attempt to connect to HomeAssistant: no token set')
            return
        attempt_count = 0
        while not self.connected:
            attempt_count += 1
            try:
                self.client = Client(f'{self.ha_server}/api', self.ha_token, cache_session=False, verify_ssl=False)
                self.lights = self.client.get_domain('light')  # pyright: ignore[reportAttributeAccessIssue]
                self.scenes = self.client.get_domain('scene')  # pyright: ignore[reportAttributeAccessIssue]
                self.scripts = self.client.get_domain('script')  # pyright: ignore[reportAttributeAccessIssue]
                self.automations = self.client.get_domain('automation')  # pyright: ignore[reportAttributeAccessIssue]
                for this_domain in ['lights', 'scenes', 'scripts', 'automations']:
                    if self.__dict__[this_domain] is None:
                        raise ConnectionError(f'Failed to get domain: {this_domain}')
                self.connected = True
                self.log.debug('Successfully connected to HomeAssistant')
            except errors.UnauthorizedError as ex:
                self.log.error(f'Failed to connect to HomeAssistant API: {ex}, will NOT retry!')
                break
            except Exception as ex:
                self.connected = False
                self.log.warning(f'Failed to connect to HomeAssistant API: {ex}, will retry in {self.retry_sleep} seconds (attempt {attempt_count})')
                time.sleep(self.retry_sleep)

    def stop(self):
        """Stop HA connection"""
        # NOTE there is no disconnect()
        self.connected = False

    def get_light_level(self, entity_id: str) -> int:
        """
        Get current brightness of a light
        """
        if not self.connected:
            self.log.warning('Not connected to HomeAssistant API')
            return -1
        try:
            light = self.client.get_entity(entity_id=entity_id)
            if light is None:
                raise ValueError(f'Could not find entity: {entity_id}')
            level: Union[int, None] = light.get_state().attributes['brightness']  # pyright: ignore[reportAssignmentType]
            if level is None:
                level = 0
        except Exception as ex:
            level = -1
            self.log.exception(f'Failed to get brightness for "{entity_id}" : {ex}')
        return int(level)

    def set_light_level(self, entity_id: str, level: int):
        """
        Set light brightness
        """
        if not self.connected:
            self.log.warning('Not connected to HomeAssistant API')
            return
        try:
            self.lights.turn_on(entity_id=entity_id, brightness=level)  # type: ignore
        except Exception as ex:
            self.log.exception(f'Failed to set brightness for "{entity_id}" : {ex}')

    def light_toggle(self, entity_id: str):
        """
        Toggle a light on/off
        """
        if not self.connected:
            self.log.warning('Not connected to HomeAssistant API')
            return
        try:
            self.log.debug(f'Toggling state of light: {entity_id}')
            self.lights.toggle(entity_id=entity_id)  # type: ignore
        except Exception as ex:
            self.log.exception(f'Failed to toggle "{entity_id}" : {ex}')

    def light_raise(self, entity_id: str, increment: int = 32):
        """
        Raise the level of a light
        """
        if not self.connected:
            self.log.warning('Not connected to HomeAssistant API')
            return
        try:
            self.log.debug(f'Incrementing brightness of {entity_id} by {increment}')
            current_level = self.get_light_level(entity_id)
            new_level = current_level + increment
            new_level = max(new_level, 0)
            self.log.debug(f'New level: {new_level}')
            if new_level < current_level:
                self.set_light_level(entity_id, new_level)
        except Exception as ex:
            self.log.exception(f'Failed to increment value of "{entity_id}" : {ex}')

    def light_lower(self, entity_id: str, increment: int = 32):
        """
        Lower the level of a light
        """
        self.light_raise(entity_id=entity_id, increment=increment * -1)

    def recall(self, entity_id: str):
        """
        Recall a scene / automation / script by entity id
            you can use any entity where turn_on is valid
        """
        if not self.connected:
            self.log.warning('Not connected to HomeAssistant API')
            return
        if entity_id == '':
            return
        try:
            domain = entity_id.split('.')[0]
            self.log.debug(f'Recalling {domain}: {entity_id}')
            target_domain = self.client.get_domain(domain)
            target_domain.turn_on(entity_id=entity_id)  # type: ignore
        except Exception as ex:
            self.log.exception(f'Failed to recall "{entity_id}" : {ex}')


class BufferedLight:
    pull_time = 2
    push_time = 0.5
    loop_time = 0.125

    def __init__(self, logger: LogManager, client: HAManager, light_id: str) -> None:
        self.log = logger
        self.ha = client
        self.light_id = light_id
        self.local_value: int = 0
        self.remote_value: int = 0
        self.last_pull: float = 0
        self.last_push: float = 0
        self.stopper = ThreadEvent()
        self.watcher = Thread(target=self.communicate, daemon=True)

    def start(self):
        self.stopper.clear()
        self._pull()
        self.watcher.start()

    def stop(self):
        self.stopper.set()

    def communicate(self):
        """check if need to push or pull value to HA"""
        while not self.stopper.is_set():
            time.sleep(self.loop_time)
            if not self.ha.connected:
                continue
            if self.stopper.is_set():
                break
            now = time.time()
            if self.local_value != self.remote_value:
                if (now - self.last_push) >= self.push_time:
                    self._push()
                    continue  # dont do push & pull on the same cycle
            if self.stopper.is_set():
                break
            if (now - self.last_pull) >= self.pull_time:
                self._pull()
            if self.stopper.is_set():
                break

    def _pull(self):
        if not self.ha.connected:
            self.log.warning('Not connected to HomeAssistant API')
        self.last_pull = time.time()
        value = self.ha.get_light_level(self.light_id)
        self.remote_value = value
        self.local_value = value

    def _push(self):
        if not self.ha.connected:
            self.log.warning('Not connected to HomeAssistant API')
        self.last_push = time.time()
        self.ha.set_light_level(self.light_id, self.local_value)
        self.remote_value = self.local_value

    def set(self, value: int):
        if not self.ha.connected:
            self.log.warning('Not connected to HomeAssistant API')
        value = min(value, 255)
        value = max(value, 0)
        self.local_value = value

    def get(self) -> int:
        if not self.ha.connected:
            self.log.warning('Not connected to HomeAssistant API')
        return self.local_value

    def toggle(self):
        self.ha.light_toggle(self.light_id)
