#!/usr/bin/env python3
"""
Kiosk Mod common stuffs
"""

from __future__ import annotations

import time
import subprocess
import asyncio

from typing import TYPE_CHECKING
from abc import abstractmethod
from pathlib import Path
from tempfile import NamedTemporaryFile


if TYPE_CHECKING:
    from log_manager import LogManager
    from config import Config

DEBUG_BASH = False  # set to True to print debugging info when using run_bash()


class ModService:
    """Base class for mod services"""

    @abstractmethod
    def __init__(self, config: Config, logger: LogManager) -> None:
        pass

    @abstractmethod
    def start(self):
        """Start"""

    @abstractmethod
    def stop(self):
        """Stop"""

    def restart(self):
        """Restart"""
        self.stop()
        time.sleep(0.5)
        self.cleanup()
        time.sleep(0.5)
        self.start()

    @abstractmethod
    def cleanup(self):
        """Cleanup"""


def _print_bash_result(script: str, result: subprocess.CompletedProcess[str]):
    """Print the input and output of a bash invocation"""
    print('Input:')
    for line in script.splitlines():
        print(f'    {line}')
    print(f'Return code: {result.returncode}')

    if result.stdout.strip() != '':
        print('stdout:')
        for line in result.stdout.strip().splitlines():
            print(f'    {line}')

    if result.stderr.strip() != '':
        print('stderr:')
        for line in result.stderr.strip().splitlines():
            print(f'    {line}')


def run_bash(script: str) -> str:
    """Run a snippet of bash and return stdout. If error, returns empty string"""
    with NamedTemporaryFile('wt', encoding='utf-8') as tempfile:
        tempfile.write(script)
        tempfile.flush()
        result = subprocess.run(['bash', tempfile.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, universal_newlines=True)
    if result.returncode == 0:
        output = result.stdout.strip()
    else:
        output = ''
    if DEBUG_BASH:
        _print_bash_result(script, result)
    return output


def get_basedir() -> Path:
    """Get the base directory, which is the folder containing this file"""
    return Path(__file__).parent.absolute()


def get_sole_string(file: Path) -> str:
    """Get the first line of a file, stripped of any whitespace padding"""
    with open(file, 'rt', encoding='utf-8') as vf:
        content = vf.read().splitlines()[0].strip()
    return content


def get_version() -> str:
    """Read version string from VERSION"""
    version_file = get_basedir().joinpath('VERSION')
    try:
        version = get_sole_string(version_file)
    except Exception:
        version = 'UNKNOWN'
    return version


def kill_event_loop(loop: asyncio.AbstractEventLoop):
    """Cancel all tasks in a given event loop and stop it"""
    tasks = asyncio.all_tasks(loop=loop)
    for task in tasks:
        try:
            task.cancel()
        except Exception:
            pass
    try:
        loop.stop()
    except Exception:
        pass
