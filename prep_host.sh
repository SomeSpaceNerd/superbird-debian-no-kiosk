#!/usr/bin/bash

# prepare host by upgrading packages, installing git, and cloning the repo
#   copy/paste this script into a file named "prep.sh" on the freshly-flashed raspberry pi
#   then run with: bash prep.sh
#   next, run setup_host.sh from the repo


set -e

# need to be root
if [ "$(id -u)" == "0" ]; then
	echo "Must be NOT run as root"
	exit 1
fi

if [ "$(uname -s)" != "Linux" ]; then
    echo "Only works on Linux!"
    exit 1
fi

if [ ! -f "/boot/bcm2710-rpi-zero-2-w.dtb" ]; then
    echo "This does not appear to be a Raspberry Pi Zero 2 W"
    echo "  expected to find: /boot/bcm2710-rpi-zero-2-w.dtb"
    #exit 1
fi
# Try to ensure we run on the correct machine
CPU_HW=$(cat /proc/cpuinfo|grep Hardware |awk '{print $3}')
if [ "$CPU_HW" != "BCM2835" ]; then
    echo "This doesn't look like Raspberry Pi, was expecting BCM2835, got: $CPU_HW"
    #exit 1
fi

DEB_RELEASE=$(lsb_release -a 2>/dev/null|grep Codename |awk '{print $2}')
if [ ! "$DEB_RELEASE" == "bullseye" ]; then
    echo "This does not appear to be Raspberry Pi OS Legacy (Bullseye) 64-Bit Lite"
    echo "  expected bullseye, got: $DEB_RELEASE"
    #exit 1
fi

echo "Updating apt package lists"
sudo apt update

echo "Upgrading all packages"
sudo apt upgrade -y

echo "Installing required packages"
sudo apt install -y git

echo "Cloning git repo"


REPO="https://github.com/SomeSpaceNerd/superbird-debian-no-kiosk.git"
# REPO="https://github.com/bishopdynamics/superbird-debian-kiosk"
# REPO="https://git.bishopdynamics.com/james/superbird-debian"

sudo git config --global pull.rebase false
sudo git config --global credential.helper store
sudo git clone "$REPO" /repo

echo "Done cloning repo!"

echo "Running host installation script"
cd /repo
sudo python3 ./install_host.py
