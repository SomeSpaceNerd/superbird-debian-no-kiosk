#!/usr/bin/env python3
"""
Common things for build and install scripts
"""

import os
import logging
import platform
import subprocess
import inspect
import importlib

from textwrap import dedent
from datetime import datetime
from tempfile import NamedTemporaryFile

from pathlib import Path
from typing import Union

# #### Logging configuration

LOG_LEVEL = logging.INFO
DATE_FORMAT = '%Y-%m-%d %I:%M:%S %p %z'
LOG_FORMAT = '%(levelname)7s %(asctime)s [%(module)16s:%(lineno)4d -> %(funcName)22s()] %(message)s'


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
    # formatter = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)
    formatter = CustomFormatter()
    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(formatter)
    mylog.addHandler(handler)
    return mylog


log = _get_log(LOG_LEVEL)


def announce_myself():
    """Announce the start of this current function"""
    # NOTE this needs to be in the same file where it will be used, in order for the globals lookup to work
    frame = inspect.currentframe()
    if frame is None:
        return
    prev_frame = frame.f_back
    if prev_frame is None:
        return
    funcname = prev_frame.f_code.co_name
    funcdoc = globals()[funcname].__doc__
    log.info(f'#################### Running {funcname}() - {funcdoc}')


class InstallStepException(Exception):
    """Error in an install step"""


class BashException(Exception):
    """Error when executing bash snippet"""


def _print_bash_result(script: str, result: subprocess.CompletedProcess[str], level: int = logging.DEBUG):
    """Print the input and output of a bash invocation"""

    if level == logging.INFO:
        logfunc = log.info
    elif level == logging.WARNING:
        logfunc = log.warning
    elif level == logging.ERROR:
        logfunc = log.error
    else:
        logfunc = log.debug

    logfunc('Input:')
    for line in script.splitlines():
        logfunc(f'    {line}')
    logfunc(f'Return code: {result.returncode}')

    if result.stdout.strip() != '':
        logfunc('stdout:')
        for line in result.stdout.strip().splitlines():
            logfunc(f'    {line}')

    if result.stderr.strip() != '':
        logfunc('stderr:')
        for line in result.stderr.strip().splitlines():
            logfunc(f'    {line}')


def _cleanup_script(script: str) -> str:
    """Cleanup given script, removing overall indentation, blank lines, and comment lines"""
    # remove indentation
    script = dedent(script)

    # remove blank and comment lines
    newlines: list[str] = []
    for line in script.splitlines():
        if line.strip() == '' or line.strip().startswith('#'):
            continue
        newlines.append(line)
    script = '\n'.join(newlines)
    return script


def run_bash(script: str, allow_failure: bool = False) -> str:
    """Run a snippet of bash script"""
    if script.strip() == '':
        raise BashException('Script content is empty!')

    # cleanup
    script = _cleanup_script(script)

    # write it to a temporary file, then run it
    with NamedTemporaryFile('wt', encoding='utf-8') as tempfile:
        tempfile.write('set -e\n' + script)  # HACK: use "set -e" to cause script to exit on any errors
        tempfile.flush()
        result = subprocess.run(['bash', tempfile.name], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False, universal_newlines=True)

    if result.returncode == 0:
        output = result.stdout.strip()
    else:
        output = ''

    if result.returncode != 0 and not allow_failure:
        log.error(f'Failed to run script, return code: {result.returncode}')
        _print_bash_result(script, result, level=logging.ERROR)
        raise BashException(f'Failed to run script, return code was: {result.returncode}')

    if log.level == logging.DEBUG:
        _print_bash_result(script, result, level=logging.DEBUG)

    if result.returncode != 0 and allow_failure:
        log.debug(f'An error was ignored, return code was: {result.returncode}')
    return output


def get_basedir() -> Path:
    """Get the base directory, which is the folder containing this file"""
    return Path(__file__).parent.absolute()


def get_sole_string(file: Path) -> str:
    """
    Get the first line of a file, stripped of any whitespace padding
    """
    with open(file, 'rt', encoding='utf-8') as vf:
        content = vf.read().splitlines()[0].strip()
    return content


def get_version() -> str:
    """
    Read VERSION and COMMIT_ID to create a version string
    """

    version_file = get_basedir().joinpath('VERSION')
    try:
        version = get_sole_string(version_file)
    except Exception:
        version = 'UNKNOWN'
    try:
        commit_id = run_bash('git rev-parse --short HEAD')
    except Exception:
        commit_id = ''
    version_string = version
    if commit_id != '':
        version_string += f'-{commit_id}'
    return version_string


def get_timestamp() -> str:
    """Get a standard timestamp string"""
    return datetime.now().strftime('%Y-%m-%d')


def append_if_missing(file: Union[Path, str], line: str):
    """Append given line to given file, only if that line is not already present"""
    if isinstance(file, str):
        file = Path(file)
    found = False
    if not file.is_file():
        raise FileNotFoundError(f'Could not find target file: {file.absolute()}')
    with open(file, 'rt', encoding='utf-8') as ff:
        content = ff.readlines()
    for cline in content:
        if line in cline:
            found = True
            break
    if not found:
        log.info(f'Appending "{line}" to: {file.absolute()}')
        with open(file, 'at', encoding='utf-8') as ff:
            ff.write(line)
    else:
        log.info(f'The line "{line}" is already present in in: {file.absolute()}')


class ChangeAttributeException(Exception):
    """Exception while changing attributes using chown or chmod"""


def chown(file: Union[Path, str], user: str):
    """Chown given file as given user; assumes group same as user"""
    if isinstance(file, str):
        file = Path(file)
    if not file.is_file():
        raise ChangeAttributeException(f'Cannot chown missing file: {file.absolute()}')
    run_bash(f'chown "{user}":"{user}" "{file.absolute()}"')


def chown_recursive(folder: Union[Path, str], user: str):
    """Chown given folder, recursively, as given user; assumes group same as user"""
    if isinstance(folder, str):
        folder = Path(folder)
    if not folder.is_dir():
        raise ChangeAttributeException(f'Cannot chown missing folder: {folder.absolute()}')
    run_bash(f'chown -R "{user}":"{user}" "{folder.absolute()}"')


def chmod(file: Union[Path, str], mode: Union[str, int]):
    """Chmod given file with given mode"""
    if isinstance(file, str):
        file = Path(file)
    if isinstance(mode, int):
        mode = str(mode)
    if not file.is_file():
        raise ChangeAttributeException(f'Cannot chmod missing file: {file.absolute()}')
    run_bash(f'chmod {mode} "{str(file.absolute())}"')


def write_file(file: Union[Path, str], content: str):
    """Write given content to given file"""
    if isinstance(file, str):
        file = Path(file)
    with open(file, 'wt', encoding='utf-8') as cf:
        cf.write(content)


def check_pip_package(name: str) -> bool:
    """Check if given pip package is installed"""
    # NOTE / HACK: assumes that the package name used for import is same as name used to install it
    #   this is not necessarily always true, but works fine for our case
    try:
        importlib.import_module(name)
        return True
    except Exception:
        return False


def install_pip_packages(reqs_file: str):
    """Install required python packages using pip"""
    announce_myself()

    # read requirements.txt to get packages
    log.debug('Reading required pip packages list')
    try:
        with open(reqs_file, 'rt', encoding='utf-8') as rf:
            reqs = rf.read().splitlines()
    except Exception as ex:
        raise InstallStepException(f'Failed to read requirements.txt for pip packages: {ex}') from ex

    # remove empty lines and comments
    pkgs_cleaned: list[str] = []
    for pkg in reqs:
        if pkg.strip() == '' or pkg.strip().startswith('#'):
            continue
        if '#' in pkg:
            # assume this is a same-line comment
            pkg = pkg.split('#')[0].strip()
        pkgs_cleaned.append(pkg)

    # check if any packages are not installed
    log.info('Checking installed pip packages')
    missing_pkgs: list[str] = []
    for pkg in pkgs_cleaned:
        log.debug(f'Checking for pip package: {pkg}')
        if not check_pip_package(pkg):
            missing_pkgs.append(pkg)

    # install only the packages that are missing
    if len(missing_pkgs) == 0:
        log.info(f'All {len(pkgs_cleaned)} needed pip packages are already installed')
    else:
        pkgs_str = ' '.join(missing_pkgs)
        log.info(f'Installing {len(missing_pkgs)} packages from pip: {pkgs_str}')
        log.info('Installing packages')
        # NOTE: on later versions of pip, you may need --break-system-packages
        run_bash(f'python3 -m pip install {pkgs_str}')


def check_apt_package(name: str) -> bool:
    """Check if given apt package is installed"""
    try:
        output = run_bash(f"dpkg -l |grep 'ii  {name} '|head -n1|awk '{{print $2}}'")
    except Exception as ex:
        raise InstallStepException(f'Failed to check if apt package installed {name}: {ex}') from ex
    return output == name


def install_apt_packages(packages: list[str]):
    """Install packages from apt"""
    announce_myself()

    # first check which packages need to be installed
    log.info('Checking installed apt packages')
    missing_pkgs: list[str] = []
    for pkg in packages:
        if not check_apt_package(pkg):
            missing_pkgs.append(pkg)

    # next, install only the ones that are missing
    if len(missing_pkgs) == 0:
        log.info(f'All {len(packages)} needed apt packages are already installed')
    else:
        pkgs_str = ' '.join(missing_pkgs)
        log.info(f'Installing {len(missing_pkgs)} packages from apt: {pkgs_str}')
        log.info('Updating apt package lists')
        run_bash('apt update')
        log.info('Installing packages')
        run_bash(f'DEBIAN_FRONTEND=noninteractive apt install -y {pkgs_str}')

# ##### Checks - returns a bool


def check_file(file: Union[Path, str]) -> bool:
    """Check given file exists"""
    if isinstance(file, str):
        file = Path(file)
    if not file.is_file():
        return False
    return True


# ##### Asserts - throws exception if expected condition is false

class AssertException(Exception):
    """Error while asserting"""


def assert_root():
    """Ensure script is running as root user"""
    if os.getuid() != 0:
        raise AssertException('Must run this script as root!')


def assert_notroot():
    """Ensure script is NOT running as root user"""
    if os.getuid() == 0:
        raise AssertException('Must NOT run this script as root!')


def assert_linux():
    """Ensure current OS is Linux"""
    if platform.system() != 'Linux':
        raise AssertException(f'This does not appear to be Linux, found: {platform.system()}')


def assert_rasbperrypios():
    """Ensure this is some version of raspberry pi os"""
    wanted_file = '/boot/bcm2710-rpi-zero-2-w.dtb'
    if not check_file(wanted_file):
        raise AssertException(f'This does not appear to be Raspberry Pi OS Legacy (Bullseye) 64-Bit Lite. Expected to find: {wanted_file}')


def assert_rpizero2w():
    """Ensure this is a Raspberry Pi Zero 2 W"""
    wanted_model = 'Raspberry Pi Zero 2 W'
    output = run_bash("cat /proc/cpuinfo|grep Model")
    model = output.removeprefix('Model').strip().removeprefix(':').strip()
    if wanted_model.lower() not in model.lower():
        raise AssertException(f'This does not appear to be a {wanted_model},  found model: {model}')


def assert_debian_bullseye():
    """Ensure this OS is based on Debian Bullseye"""
    output = run_bash("cat /etc/os-release|grep VERSION_CODENAME")
    output = output.strip().removeprefix('VERSION_CODENAME=').strip()
    if output != 'bullseye':
        raise AssertException(f'This is not Debian Bullseye! Found: {output}')


def assert_amlogic():
    """Ensure this device has Amlogic CPU (superbird)"""
    wanted = 'Amlogic'
    output = run_bash("cat /proc/cpuinfo|grep Hardware |awk '{print $3}'")
    if output != wanted:
        raise AssertException(f'This is not Spotify Car Thing (superbird)! Expecting "{wanted}", found: "{output}"')


def assert_broadcom():
    """Ensure this device has BCM2835 CPU (raspberry pi)"""
    wanted = 'BCM2835'
    output = run_bash("cat /proc/cpuinfo|grep Hardware |awk '{print $3}'")
    if output != wanted:
        raise AssertException(f'This is not Raspberry Pi! Expecting "{wanted}", found: "{output}"')


def assert_superbird_blk():
    """Ensure this device has the expected set of block devices for superbird"""
    expected = [
        'mmcblk0boot0',
        'mmcblk0boot1',
        'mmcblk0rpmb',
    ]
    for dev in expected:
        output = run_bash(f'lsblk |grep {dev}')
        if dev not in output:
            raise AssertException(f'The block devices on this system do not look like those of superbird! Expecting: {", ".join(expected)}')


def assert_superbird():
    """Ensure running directly on the superbird device"""
    assert_linux()
    assert_amlogic()
    assert_superbird_blk()
    assert_debian_bullseye()
    log.info('This appears to be Spotify Car Thing (superbird)')


def assert_hostdevice():
    """Ensure running directly on the host device (Raspberry Pi Zero 2 W)"""
    assert_linux()
    assert_broadcom()
    assert_rpizero2w()
    assert_rasbperrypios()
    log.info('This appears to be the host device, Raspberry Pi Zero 2 W')
