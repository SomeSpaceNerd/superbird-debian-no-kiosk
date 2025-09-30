#!/usr/bin/env bash

# Perform an upgrade to the latest version of kiosk
#   will upgrade host AND superbird

set -e

echo "Running as: $(whoami)"
# need to be root
if [ "$(id -u)" != "0" ]; then
	echo "Must be run as root"
	exit 1
fi

# NOTE - these vars must be set by the source line below
USER_NAME=""
HOST_NAME=""

cd /repo

# Get config
# shellcheck disable=SC1090
source "$(python3 ./install_config.py)"

if [ -z "$USER_NAME" ] || [ -z "$HOST_NAME" ]; then
    echo "Error loading values from install_config.py"
    exit 1
fi

# Try to ensure we run on the correct machine
CPU_HW=$(cat /proc/cpuinfo|grep Hardware |awk '{print $3}')
if [ "$CPU_HW" != "BCM2835" ]; then
    echo "This doesn't look like Raspberry Pi, was expecting BCM2835, got: $CPU_HW"
    exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "Only works on Linux! You should be running this from within cloned repo on the raspberry pi host!"
    exit 1
fi

git config pull.rebase false
git stash
git pull
python3 install_host.py

ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null -i "/home/${USER_NAME}/.ssh/id_rsa" "$USER_NAME"@"$HOST_NAME" "sudo /repo/superbird_upgrade.sh" || true  # connection close counts as an error

echo ""
echo "The superbird device is rebooting"
echo "    After reboot completes you can configure this device at: http://$(hostname)/"

if [ "$1" == "-d" ]; then
    echo "Upgrade complete"
else
    echo "Upgrade complete, you must reboot this host for all changes to take effect"
fi
