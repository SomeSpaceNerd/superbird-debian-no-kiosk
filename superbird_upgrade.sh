#!/usr/bin/env bash

# Perform an upgrade to the latest version of the kiosk files, on superbird device directly
#   this will not affect the host device, it will need to be upgraded separately
#   this script is called by upgrade.sh

set -e

# Try to ensure we run on the correct machine
CPU_HW=$(cat /proc/cpuinfo|grep Hardware |awk '{print $3}')
if [ "$CPU_HW" != "Amlogic" ]; then
    echo "This doesn't look like Spotify Car Thing, was expecting Amlogic, got: $CPU_HW"
    exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "Only works on Linux! You should be running this from within cloned repo on the superbird device!"
    exit 1
fi

# need to be root
if [ "$(id -u)" != "0" ]; then
	echo "Must be run as root"
	exit 1
fi

cd /repo

git config --global pull.rebase false
git stash
git pull

python3 install_superbird.py  # will reboot at end
