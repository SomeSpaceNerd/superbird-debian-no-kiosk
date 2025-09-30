#!/usr/bin/env bash

# Update the updater
#   the updater is also updated by upgrade.sh and install_host.py

set -e

# Try to ensure we run on the correct machine
CPU_HW=$(cat /proc/cpuinfo|grep Hardware |awk '{print $3}')
if [ "$CPU_HW" != "BCM2835" ]; then
    echo "This doesn't look like Raspberry Pi, was expecting BCM2835, got: $CPU_HW"
    exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "Only works on Linux! You should be running this from within cloned repo on the host raspberry pi!"
    exit 1
fi

# need to be root
if [ "$(id -u)" != "0" ]; then
	echo "Must be run as root"
	exit 1
fi

cd /repo

echo "Updating the kiosk-updater service"

git pull
cp ./files/host/kiosk-updater/* /kiosk-updater/
systemctl restart kiosk-updater
systemctl status kiosk-updater

echo "Done updating kiosk-updater service"
