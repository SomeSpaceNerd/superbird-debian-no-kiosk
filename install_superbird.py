#!/usr/bin/env python3
"""
Install files and services on superbird device
"""

import os
import sys
import inspect
import shutil
import argparse

from pathlib import Path

from install_config import *  # pylint: disable=unused-wildcard-import
from install_common import assert_root, assert_superbird, log
from install_common import run_bash, chown, write_file, get_version, install_pip_packages, install_apt_packages

from build_images import STAGE1_APT_PKGS, STAGE2_APT_PKGS

NEW_FILES = Path("/repo/files/data")
LOCAL_SCRIPTS = Path("/scripts")

CONFIG_FILES_REPLACE: dict[str, str] = {
    f"{NEW_FILES}/etc/fstab": "/etc/fstab",
    f"{NEW_FILES}/etc/inittab": "/etc/inittab",
    f"{NEW_FILES}/etc/haproxy/haproxy.cfg": "/etc/haproxy/haproxy.cfg",
}

CONFIG_FILES_NOREPLACE: dict[str, str] = {
    f"{NEW_FILES}/etc/vnc/vnc_passwd": "/etc/vnc/vnc_passwd",
    f"{NEW_FILES}/etc/X11/xorg.conf.portrait": "/etc/X11/xorg.conf",
}

# #### Utility


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


# #### Setup steps


def shutdown_services():
    """Shutdown running services so we can update them"""
    announce_myself()
    services = [
        'backlight',
        'kiosk',
        'vnc',
        'usbgadget',
        'websockify',
    ]
    for svc in services:
        log.info(f'Stopping service: {svc}')
        run_bash(f'systemctl stop {svc}.service', allow_failure=True)


def check_settings_partition():
    """Check if /dev/settings has been setup for browser profile"""
    # NOTE this does NOT work in the chroot, need to run on actual device
    announce_myself()
    output = run_bash('mount |grep -q /dev/settings || echo missing')
    if output != 'missing':
        log.info('/dev/settings is already mounted on /config')
    else:
        log.info('Preparing /dev/settings as /config for browser profile')
        content = """
        umount /config  # just in case
        rm -r /config
        mkfs.ext4 -F /dev/settings
        mkdir /config
        mount /config
        """
        run_bash(content)


def install_scripts():
    """Install scripts for kiosk"""
    announce_myself()
    version = get_version()
    log.info(f'Installing scripts v{version}')
    if LOCAL_SCRIPTS.is_dir():
        log.info(f'Removing existing folder: {LOCAL_SCRIPTS}')
        shutil.rmtree(LOCAL_SCRIPTS)
    log.info(f'Copying new files to folder: {LOCAL_SCRIPTS}')
    shutil.copytree(NEW_FILES.joinpath('scripts'), LOCAL_SCRIPTS)
    write_file(LOCAL_SCRIPTS.joinpath('VERSION'), version)


def clear_systemd_logs():
    """Clear all systemd logs"""
    announce_myself()
    run_bash('journalctl --rotate')
    run_bash('journalctl --vacuum-time=1s')


def _install_service(name: str, bypass: bool):
    """Install a single service"""
    # NOTE would normally do "systemctl daemon-reload", but systemd on superbird it doesnt matter
    if not name.endswith('.service'):
        name = f'{name}.service'
    log.info(f'Installing service: {name}')
    run_bash(f'touch "/lib/systemd/system/{name}"')
    chown(f"/lib/systemd/system/{name}", USER_NAME)
    shutil.copy(f"{NEW_FILES}/lib/systemd/system/{name}", "/lib/systemd/system/")
    if not bypass:
        run_bash(f'systemctl restart "{name}"')
    try:
        os.symlink(f"/lib/systemd/system/{name}", f"/etc/systemd/system/multi-user.target.wants/{name}")
    except FileExistsError:
        pass


def install_services(bypass: bool):
    """Install systemd services for kiosk"""
    announce_myself()
    services = [
        'backlight',
        'kiosk',
        'vnc',
        'websockify',
        'usbgadget',
    ]
    for svc in services:
        _install_service(svc, bypass)


def install_config_files():
    """Install any missing config files"""
    announce_myself()
    for src, dest in CONFIG_FILES_REPLACE.items():
        log.info(f'Overwriting config file: {dest}')
        shutil.copy(src, dest)
    for src, dest in CONFIG_FILES_NOREPLACE.items():
        if not Path(dest).is_file():
            log.info(f'Installing missing config file: {dest}')
            parent = Path(dest).parent
            if not parent.is_dir():
                log.info(f'Creating folder: {parent}')
                parent.mkdir()
            shutil.copy(src, dest)


def restart_haproxy():
    """Restart HAProxy after updating config file"""
    announce_myself()
    run_bash('systemctl restart haproxy')


def setup_hostname():
    """Write hostname to /etc/hostname"""
    announce_myself()
    write_file('/etc/hostname', HOST_NAME)


def setup_hosts():
    """Generate content of /etc/hosts"""
    announce_myself()
    content = f"""
	# generated by install-superbird.py
	127.0.0.1     localhost
	127.0.0.1     {HOST_NAME}
	::1           localhost {HOST_NAME} ip6-localhost ip6-loopback
	ff02::1	      ip6-allnodes
	ff02::2       ip6-allrouters
	{USBNET_PREFIX}.1   host
    """
    write_file('/etc/hosts', content)


# #### The whole process


def install_superbird(bypass: bool = False):
    """Setup superbird device"""
    if not bypass:
        shutdown_services()
        check_settings_partition()
        clear_systemd_logs()
    install_scripts()
    install_apt_packages(STAGE1_APT_PKGS)
    install_apt_packages(STAGE2_APT_PKGS)
    install_pip_packages(f'{LOCAL_SCRIPTS}/requirements.txt')
    install_services(bypass)
    install_config_files()
    if not bypass:
        restart_haproxy()
    setup_hostname()
    setup_hosts()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='superbird kiosk installer')
    parser.add_argument('--bypass', action='store_true', help='Bypass steps dependant on real hardware (for installing in chroot)')
    args = parser.parse_args(sys.argv[1:])  # the sys.argv bit makes it work with pyinstaller

    try:
        log.info('Installing on superbird')
        log.debug(f'Base path: {BASE_PATH}')

        if not args.bypass:
            assert_superbird()
        assert_root()

        if not NEW_FILES.is_dir():
            raise FileNotFoundError(f'Could not find NEW_FILES: {NEW_FILES.absolute()}')

        install_superbird(args.bypass)
    except Exception as ex:
        log.exception(f'Unexpected exception in install-superbird.py:main(): {ex}')
        sys.exit(1)
    log.info('Done setting up superbird!')

    if not args.bypass:
        log.info('Will reboot superbird device now')
        os.system('reboot')
