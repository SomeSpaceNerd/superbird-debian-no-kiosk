#!/usr/bin/env python3
"""
Build images for superbird device
NOTE this only works using the PUBLIC github repo, not our private one
    so you MUST push latest code to github before you can build this image
"""

import sys
import shutil
import inspect
import logging


from install_config import *  # pylint: disable=unused-wildcard-import

from install_common import assert_root, assert_linux, log, get_version, get_timestamp, run_bash, chmod, write_file


# ##### Static Vars

ORIENTATIONS = ['landscape', 'portrait']

DIST_FOLDER = BASE_PATH.joinpath('dist')
AML_IMGPACK = BASE_PATH.joinpath('aml_imgpack.py')

STAGE1_APT_PKGS: list[str] = [
    # init system, either systemd or sysvinit
    #   without systemd-sysv, no reboot/shutdown commands
    'systemd',
    'systemd-sysv',
    'dbus',
    'kmod',
    # base packages
    'usbutils',
    'htop',
    'nano',
    'tree',
    'file',
    'less',
    'locales',
    'sudo',
    'dialog',
    'apt',
    'systemd-sysv',
    # stuff for networking
    'wget',
    'curl',
    'iputils-ping',
    'iputils-tracepath',
    'iputils-arping',
    'iproute2',
    'net-tools',
    'openssh-server',
    'ntpsec',
    # minimal xorg
    'xserver-xorg-core',
    'xserver-xorg-video-fbdev',
    'xterm',
    'xinit',
    'x11-xserver-utils',
    'shared-mime-info',
    # xorg input
    'xserver-xorg-input-evdev',
    'libinput-bin',
    'xserver-xorg-input-libinput',
    'xinput',

    # additional required packages
    'fbset',
    'tigervnc-scraping-server',
    'git',
]

# NOTE: we cannot install chromium at at the debootstrap stage
#   so we install chromium and other packages in a separate stage using chroot
STAGE2_APT_PKGS: list[str] = [
    'python3-minimal',
    'python3-pip',
    # the browser
    'chromium',
    # proxy, to fix remote chromium debug port access
    'haproxy',
]

KERNEL_VERSION = '4.9.113'  # this is the kernel that comes with superbird, we dont have any other kernel

DATA_SIZE = 2189224  # KB, size of the data partition image file
SETTINGS_SIZE = 262144  # KB, size of the settings partition image file

TEMP_DIR = BASE_PATH.joinpath('temp')


# ##### Running vars

FILES_BASE: Path = BASE_PATH.joinpath('files')
"""base folder for files to install"""
LOGO_SOURCES = BASE_PATH.joinpath('logos_sources')
"""source folder for logo images, where we will grab the portrait or landscape image"""

ENV_TXT_FILE = FILES_BASE.joinpath('env/env_switchable.txt')
"""Env.txt which will replace the existing one, with more button combos for boot options"""
ENV_DUMP_FILE = FILES_BASE.joinpath('env/env_switchable.dump')
"""Env.dump which will replace the existing one, with more button combos for boot options"""

FILES_SYS = FILES_BASE.joinpath('system_a')
"""files to install in system_a partition"""
FILES_DATA = FILES_BASE.joinpath('data')
"""files to install in data partition"""
LOGO_IMAGES = FILES_BASE.joinpath('logo')
"""images in the repo, which we will copy to TEMP_IMAGES before making changes"""
TEMP_IMAGES = TEMP_DIR.joinpath('logo')
"""images to pack into images partition"""

MOUNT_BASE = TEMP_DIR.joinpath('mounts')
"""base folder for any mounted filesystems"""
MOUNT_SYS = MOUNT_BASE.joinpath("system_a")
"""this is where we will mount system_a partition to modify, and get modules"""
MOUNT_DATA = MOUNT_BASE.joinpath("data")
"""this is where we will mount data partition to perform install"""

CSV_PACKAGES = ','.join(STAGE1_APT_PKGS)
"""comma-separated list of packages for debootstrap"""
global_target_image: Path = None  # type:ignore
"""This is the folder containing the dump that we are currently working on"""

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


def in_target(command: str) -> str:
    """Run a command inside the target system via chroot"""
    return run_bash(f'chroot "{MOUNT_DATA}" {command}')


class BuildStepException(Exception):
    """Error in a build step"""


def create_image_file(filepath: Path, size: int):
    log.info(f'Creating empty image file ({size}KB): {filepath.absolute()}')
    run_bash(f'dd if=/dev/zero of="{filepath.absolute()}" bs=1K count={size}')

# #### Build steps


def setup_folders():
    """Cleanup and re-create all needed temp folders"""
    announce_myself()
    if TEMP_DIR.is_dir():
        shutil.rmtree(TEMP_DIR)
    TEMP_DIR.mkdir()
    MOUNT_BASE.mkdir()
    MOUNT_SYS.mkdir()
    MOUNT_DATA.mkdir()
    DIST_FOLDER.mkdir(exist_ok=True)


def copy_stock_image(ver_name: str):
    """Create a copy of the stock image to use as a base for this one"""
    announce_myself()
    global global_target_image
    global_target_image = TEMP_DIR.joinpath(ver_name)
    log.info(f'Creating new image: {global_target_image.absolute()}')

    def ignore_stock_files(_path: str, names: list[str]) -> set[str]:
        """used by copytree to ignore some files when copying stock dump"""
        dont_want = [
            'settings.ext4', 'data.ext4', 'env.txt', 'env.dump', 'checksums.txt',
        ]
        ignore: set[str] = set()
        for name in names:
            if name in dont_want:
                ignore.add(name)
            if name.startswith('.') or name.startswith('_'):
                ignore.add(name)
        return ignore

    shutil.copytree(EXISTING_DUMP, global_target_image, ignore=ignore_stock_files)


def modify_env():
    """Modify env partition"""
    # TODO we can probably generate the env.dump from env.txt, and skip having an 8MB env.dump in the repo
    announce_myself()

    target_env_txt = global_target_image.joinpath('env.txt')
    if target_env_txt.is_file():
        target_env_txt.unlink()
    target_env_dump = global_target_image.joinpath('env.dump')
    if target_env_dump.is_file():
        target_env_dump.unlink()

    shutil.copy(ENV_TXT_FILE, target_env_txt)
    shutil.copy(ENV_DUMP_FILE, target_env_dump)


def rebuild_logo_custom(orient: str):
    """Rebuild logo.dump using custom images"""
    announce_myself()

    shutil.copytree(LOGO_IMAGES, TEMP_IMAGES)

    img_landscape = LOGO_SOURCES.joinpath('upgrade_success_landscape.bmp')
    img_portrait = LOGO_SOURCES.joinpath('upgrade_success_portrait.bmp')
    img_target = TEMP_IMAGES.joinpath('upgrade_success.bmp')
    if orient == 'landscape':
        shutil.copy(img_landscape, img_target)
    else:
        shutil.copy(img_portrait, img_target)

    # NOTE: we _could_ import and use the function directly,
    #   but then we have to list the contents of TEMP_IMAGES ourselves
    #   this way we let bash do it for us with the glob
    run_bash(f'{AML_IMGPACK} --pack "{global_target_image}/logo.dump" {TEMP_IMAGES}/*.bmp')


def cleanup_mountpoints():
    """Cleanup any leftover mountpoints from a previous execution"""
    announce_myself()
    run_bash((f'mountpoint "{MOUNT_SYS}" && umount "{MOUNT_SYS}"'), allow_failure=True)
    run_bash((f'mountpoint "{MOUNT_DATA}" && umount "{MOUNT_DATA}"'), allow_failure=True)


def create_settings_image():
    """Create the settings.ext4 image"""
    announce_myself()
    filepath = global_target_image.joinpath('settings.ext4')
    create_image_file(filepath, SETTINGS_SIZE)


def create_data_image():
    """Create the data.ext4 image"""
    announce_myself()
    filepath = global_target_image.joinpath('data.ext4')
    create_image_file(filepath, DATA_SIZE)


def format_partitions():
    """Format partitions and put them to our own use"""
    announce_myself()
    for filename in ['data.ext4', 'settings.ext4']:
        imgfile = global_target_image.joinpath(filename)
        log.info(f'Formatting {imgfile}')
        run_bash(f'mkfs.ext4 -F "{imgfile}"')


def mount_data():
    """Mount the data partition"""
    announce_myself()
    run_bash(f'mount -o loop "{global_target_image}/data.ext4" "{MOUNT_DATA}"')


def mount_system():
    """Mount the system_a partition"""
    announce_myself()
    run_bash(f'mount -o loop "{global_target_image}/system_a.ext2" "{MOUNT_SYS}"')


def install_debian():
    """Install basic debian to data partition using debootstrap"""
    announce_myself()
    try:
        output = run_bash("dpkg -l |grep apt-cacher-ng|awk '{print $2}'")
    except Exception:
        log.error('Failed to check if apt-cacher-ng is installed, assuming not')
        output = ''
    if output == 'apt-cacher-ng':
        log.info('Using apt-cacher-ng to cache apt repo files')
        prefix = 'export http_proxy=http://127.0.0.1:3142'
    else:
        log.info('Not using apt-cacher-ng to cache apt repo files')
        prefix = '# not using proxy'
    scr_content = f"""
    {prefix}
    debootstrap --verbose --variant="{DISTRO_VARIANT}" --no-check-gpg --include="{CSV_PACKAGES}" --arch="{ARCHITECTURE}" "{DISTRO_BRANCH}" "{MOUNT_DATA}" "{DISTRO_REPO_URL}"
    """
    run_bash(scr_content)


def install_stage2_apt_packages():
    """Install packages that must be installed later via apt"""
    announce_myself()
    in_target('apt update')
    pkgs_str = ' '.join(STAGE2_APT_PKGS)
    in_target(f'apt install -y --no-install-recommends --no-install-suggests {pkgs_str}')


def create_utility_mode():
    """Create a utility mode in system_a, that has adb and usbnet ready to go, but otherwise stock"""
    announce_myself()
    # TODO include DNS fix here when we figure it out
    shutil.copy(FILES_SYS.joinpath('etc/fstab'), MOUNT_SYS.joinpath('etc'))
    shutil.copy(FILES_SYS.joinpath('etc/inittab'), MOUNT_SYS.joinpath('etc'))
    shutil.copy(FILES_SYS.joinpath('etc/init.d/S49usbgadget'), MOUNT_SYS.joinpath('etc/init.d'))
    chmod(MOUNT_SYS.joinpath('etc/init.d/S49usbgadget'), '+x')


def copy_kernel_modules():
    """Copy kernel modules from system_a, we need those for debian"""
    announce_myself()
    dir_lib = MOUNT_DATA.joinpath('lib')
    dir_modules = dir_lib.joinpath('modules')
    dir_lib.mkdir()
    dir_modules.mkdir()
    target = dir_modules.joinpath(KERNEL_VERSION)
    source = MOUNT_SYS.joinpath(f"lib/modules/{KERNEL_VERSION}")
    shutil.copytree(source, target)


def unmount_system():
    """Unmount the system_a partition"""
    announce_myself()
    run_bash('sync')
    run_bash(f'umount {MOUNT_SYS}')


def unmount_data():
    """Unmount the data partition"""
    announce_myself()
    run_bash('sync')
    run_bash(f'umount {MOUNT_DATA}')


def fix_systemd_getty():
    """Fix missing symlink for getty"""
    announce_myself()
    in_target('ln -sf "/lib/systemd/system/getty@.service" "/etc/systemd/system/getty.target.wants/getty@ttyS0.service"')


def setup_timezone_locale():
    """Setup timezone and locale"""
    announce_myself()
    log.info(f"Generating locales for {LOCALE}")
    run_bash(f"sed -i -e 's/# {LOCALE} UTF-8/{LOCALE} UTF-8/' \"{MOUNT_DATA}/etc/locale.gen\"")
    locfile = MOUNT_DATA.joinpath('etc/default/locale')
    write_file(locfile, f'LANG={LOCALE}')
    in_target('dpkg-reconfigure --frontend=noninteractive locales')

    log.info(f"Setting timezone to {TIMEZONE}")
    in_target(f'ln -sf "/usr/share/zoneinfo/{TIMEZONE}" "/etc/localtime"')
    in_target('dpkg-reconfigure --frontend=noninteractive tzdata')


def install_xorgconf(orient: str):
    """Install xorg.conf for this orientation"""
    announce_myself()

    MOUNT_DATA.joinpath('etc/X11').mkdir(exist_ok=True)

    log.info(f'Installing xorg.conf for orientation: {orient}')
    if orient == 'landscape':
        shutil.copy(FILES_DATA.joinpath('etc/X11/xorg.conf.landscape'), MOUNT_DATA.joinpath('etc/X11/xorg.conf'))
    else:
        shutil.copy(FILES_DATA.joinpath('etc/X11/xorg.conf.portrait'), MOUNT_DATA.joinpath('etc/X11/xorg.conf'))

    # need to disable the scripts that try to autodetect input devices, they cause double input
    # 	this is particularly evident when in landscape mode, as only one of the two inputs is correctly transformed for the rotation
    # 	these files were installed by xserver-xorg-input-libinput

    log.info("disabling autoconfigured xorg input")
    in_target('mv /usr/share/X11/xorg.conf.d /usr/share/X11/xorg.conf.d.bak')


def setup_user():
    """Setup the non-root user account: superbird"""
    announce_myself()
    log.info(f'Creating regular user (with sudo): {USER_NAME}')

    in_target(f'useradd -p \'{USER_PASS_HASH}\' --shell /bin/bash "{USER_NAME}"')

    in_target(f'mkdir -p "/home/{USER_NAME}"')
    in_target(f'chown -R "{USER_NAME}":"{USER_NAME}" "/home/{USER_NAME}"')
    in_target(f'chmod 700 "/home/{USER_NAME}"')

    in_target(f'mkdir -p "/home/{USER_NAME}/.ssh"')
    in_target(f'chown -R "{USER_NAME}":"{USER_NAME}" "/home/{USER_NAME}/.ssh"')
    in_target(f'chmod 700 "/home/{USER_NAME}/.ssh"')

    # let user use sudo without password
    run_bash(f'echo "{USER_NAME} ALL=(ALL) NOPASSWD: ALL" >> "{MOUNT_DATA}/etc/sudoers"')

    in_target(f'usermod -aG cdrom "{USER_NAME}"')
    in_target(f'usermod -aG floppy "{USER_NAME}"')
    in_target(f'usermod -aG sudo "{USER_NAME}"')
    in_target(f'usermod -aG audio "{USER_NAME}"')
    in_target(f'usermod -aG dip "{USER_NAME}"')
    in_target(f'usermod -aG video "{USER_NAME}"')
    in_target(f'usermod -aG plugdev "{USER_NAME}"')


def setup_ssh_key():
    """Install public key for passwordless ssh authentication"""
    announce_myself()
    authpath = f'home/{USER_NAME}/.ssh/authorized_keys'
    write_file(MOUNT_DATA.joinpath(authpath), SSH_KEY_PUBLIC)
    in_target(f'chown "{USER_NAME}":"{USER_NAME}" "/{authpath}"')
    in_target(f'chmod 600 "/{authpath}"')


def install_kiosk():
    """Install the kiosk app"""
    # NOTE here we copy THIS REPO, instead of cloning it fresh
    #   that means that this repo needs to be the public github one!
    announce_myself()

    def ignore_repo_files(_path: str, names: list[str]) -> set[str]:
        """used by copytree to ignore some folders"""
        dont_want = [
            'dumps', 'dist', 'temp', 'tmp', 'modules', 'headers', 'rootfs', 'output', 'venv', 'env', 'old', '__pycache__', '.mypy_cache', '.DS_Store', '._DS_Store'
        ]
        ignore: set[str] = set()
        for name in names:
            if name in dont_want:
                ignore.add(name)
        return ignore

    shutil.copytree(BASE_PATH, MOUNT_DATA.joinpath('repo'), ignore=ignore_repo_files)

    in_target('chown -R root:root /repo')
    # NOTE use the --bypass flag to skip tasks that require running on real hardware
    in_target('python3 /repo/install_superbird.py --bypass')


def create_archive(ver_name: str):
    """Create the release archive"""
    announce_myself()
    run_bash(f'cd {TEMP_DIR}; tar czf "{ver_name}.tar.gz" "{ver_name}"')
    run_bash(f'cd {TEMP_DIR}; mv "{ver_name}.tar.gz" {DIST_FOLDER.absolute()}/')


def cleanup_temp():
    """Cleanup temporary folder"""
    announce_myself()
    if TEMP_DIR.is_dir():
        shutil.rmtree(TEMP_DIR)

# #### The whole image


def build_image(orient: str, ver_name: str):
    """Build an individual image"""
    log.info('-------------------------------------------------------------------------------------------------------------------------------------------------------------------------')
    announce_myself()

    # cleanup and prepare temp folders
    cleanup_mountpoints()
    setup_folders()

    # prepare img files
    copy_stock_image(ver_name)
    modify_env()
    rebuild_logo_custom(orient)
    create_settings_image()
    create_data_image()
    format_partitions()

    # mount images
    mount_system()
    mount_data()

    # grab kernel modules from system_a to data, we need those
    copy_kernel_modules()

    # work on system_a partition
    create_utility_mode()

    # done with system_a
    unmount_system()

    # work on data partition
    install_debian()
    install_stage2_apt_packages()
    fix_systemd_getty()
    setup_timezone_locale()
    install_xorgconf(orient)
    setup_user()
    setup_ssh_key()

    # install the kiosk files and services
    install_kiosk()

    # done with data
    unmount_data()
    create_archive(ver_name)

    # cleanup temp unless debugging
    if log.level != logging.DEBUG:
        cleanup_temp()


def build_release():
    """Build the full release, containing both images"""
    announce_myself()

    version = get_version()
    timestamp = get_timestamp()
    filename_base = f"debian_{DISTRO_BRANCH}_{ARCHITECTURE}_v{version}"

    Path(DIST_FOLDER).mkdir(exist_ok=True)
    log.info(f'Building release: {filename_base}_{timestamp}')

    for orient in ORIENTATIONS:
        ver_name = f'{filename_base}_{orient}_{timestamp}'
        build_image(orient, ver_name)


def check_existing_dump():
    """check the existing dump files exist"""
    announce_myself()
    wanted_files = [
        'system_a.ext2',
        # 'settings.ext4',
    ]
    if not EXISTING_DUMP.is_dir():
        raise BuildStepException(f'Need to provide existing stock dump for reference at: {EXISTING_DUMP.absolute()}')
    for file in wanted_files:
        file_path = EXISTING_DUMP.joinpath(file)
        if not file_path.is_file():
            raise BuildStepException(f'Missing expected file: {file_path.absolute()}')


def check_dev():
    """Check if this is dev repo and print a warning"""
    output = run_bash("git remote -v|head -n 1|awk '{print $2}'")
    if 'git.bishopdynamics.com' in output:
        print()
        log.warning(' ********* THIS IS THE DEV REPO!!! **********')
        log.warning(' DO NOT RELEASE THESE IMAGES! THEY WILL HAVE THE WRONG REPO INSTALLED!')
        log.warning(' ********* THIS IS THE DEV REPO!!! **********')
        print()


if __name__ == '__main__':
    try:
        log.info('Building Images')
        log.debug(f'Base path: {BASE_PATH}')

        assert_linux()
        assert_root()

        check_dev()
        check_existing_dump()

        build_release()

        check_dev()
        log.info('Finished building images')
    except Exception as ex:
        log.exception(f'Unexpected exception in build-images.py:main(): {ex}')
        cleanup_mountpoints()
        sys.exit(1)
