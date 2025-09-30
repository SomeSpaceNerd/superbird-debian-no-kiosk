# Wall Thing: Debian Chromium Kiosk on Spotify Car Thing (superbird)

This is a prebuilt image of Debian 11 (Bullseye) for the Spotify Car Thing, aka superbird.
It combines the stock kernel with a debian rootfs, and launches a fullscreen Chromium kiosk. I like to use it with Home Assistant.

<a href="./pictures/superbird_ha_portrait2.jpg"><img src="./pictures/superbird_ha_portrait2.jpg" height=300/></a>
<a href="./pictures/superbird_wall_mount.jpg"><img src="./pictures/superbird_wall_mount.jpg" height=300/></a>
<a href="./pictures/superbird_ha_portrait.jpg"><img src="./pictures/superbird_ha_portrait.jpg" height=300/></a>

This image will remove the default Spotify functionality. You should definitely [make a full backup](https://github.com/bishopdynamics/superbird-tool) before proceeding!

Default user and password are both `superbird`

![Latest Release](https://img.shields.io/github/v/release/bishopdynamics/superbird-debian-kiosk?logo=github)

[Releases](https://github.com/bishopdynamics/superbird-debian-kiosk/releases)

[Changelog](./Changelog.md)

## Warranty and Liability

None. You definitely can mess up your device in ways that are difficult to recover. I cannot promise a bug in this script will not brick your device.
By using this tool, you accept responsibility for the outcome.

I highly recommend connecting to the UART console, [frederic's repo](https://github.com/frederic/superbird-bulkcmd) has some good pictures showing where the pads are.

Make backups.

## WebUI

<a href="./pictures/webui_main.png"><img src="./pictures/webui_main.png" height=300></a>
<a href="./pictures/webui_devtools.png"><img src="./pictures/webui_devtools.png" height=300></a>
<a href="./pictures/webui_host.png"><img src="./pictures/webui_host.png" height=300></a>

## 3D Printed Case

The case in the pictures [can be found in here](./Wallthing/).
![](./pictures/sketchup_models.png)

## Features

Working:

- Debian 11 (Bullseye) aarch64
- Framebuffer display working with X11, in portrait or landscape, with touch input
- Networking via USB RNDIS (requires a host device)
- Automatic blacklight on/off with display wake/sleep
- VNC and SSH (forwarded through host device)
- Chromium browser, fullscreen kiosk mode, with DevTools available
- Buttons and dial used to control a light and recall scenes/automations/scripts on Home Assistant
- 256MB `settings` partition used for Chromium user profile
- Backlight brightness control (default 100)

Available, but not used in this image:

- Bluetooth
- Audio (mic array, DSP)

Not working:

- Wifi
- GPU acceleration

WiFi is _technically_ possible on this hardware, but the stock bootloaders and kernel disable it.
It might be possible to cherry-pick the wifi information from the Radxa Zero device tree (practically the same SoC), but I think you would need to rebuild one or more of the bootloader stages to make it work.

GPU: the hardware has a Mali GPU, but the stock OS uses it via DirectFB QT library, and does not include necessary libraries to make it work with X11. It may be possible to grab the needed files from Radxa Zero.

## Boot Modes

After installation, you will have 3 different boot options, depending on what buttons are held when you plug it in:

| Buttons    | Mode          | Details                                                                                                             | Logo                                                                                                    |
| ---------- | ------------- | ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| none       | Debian        | \* bootlogo is blue Home Assistant icon<br> \* kernel is `boot_a` root is `data`                                    | <a href="./files/logo/upgrade_success.bmp"><img src="./files/logo/upgrade_success.bmp" height=200 ></a> |
| hold 1     | Utility Mode  | \* bootlogo says Utility Mode<br> \* kernel is `boot_a` root is `system_a`<br> \* adb and usbnet already configured | <a href="./files/logo/bootup_spotify.bmp"><img src="./files/logo/bootup_spotify.bmp" height=200></a>    |
| hold 4     | USB Burn Mode | \* bootlogo says USB Burn Mode <br> \* ready to flash images                                                        | <a href="./files/logo/upgrade_error.bmp"><img src="./files/logo/upgrade_error.bmp" height=200></a>      |
| hold 1 & 4 | USB Mode      | \* screen is black <br> \* can enter USB Burn Mode using: <br>`./superbird-toolpy --burn_mode`                      | <img src="./logos_sources/black.bmp" height=200>                                                        |
|            |

## Installation

### Requirements

- Spotify Car Thing (aka superbird)
- a Raspberry Pi Zero 2 W
  - new: this is the ONLY supported host hardware now, enforced by install scripts
- a microsd card, 8GB+ recommended
- a MicroUSB (male) -> USB-C (male) cable to connect the two
- power supply for the host device
- a desktop/laptop for flashing the image to the Car Thing

### Setup Superbird (Spotify Car Thing)

1. Download and extract the latest image from [Releases](https://github.com/bishopdynamics/superbird-debian-kiosk/releases)
2. Put your device in burn mode by holding buttons 1 & 4 while plugging into usb port
   1. avoid using a USB hub, you will have issues flashing the image
3. Use the latest version of [superbird-tool](https://github.com/bishopdynamics/superbird-tool) to flash the extracted image folder:

```bash
# root may be needed, check superbird-tool readme for platform-specific usage
# make sure your device is found
python3 superbird_tool.py --find_device
# restore the entire folder to your device
python3 superbird_tool.py --restore_device ~/Downloads/debian_bullseye_arm64_v2.0.0-4894459_landscape_2025-09-29/
```

- Alternatively (on x86_64 Linux only), use the [Superbird Backup & Recovery](https://github.com/bishopdynamics/superbird-backup-and-recovery) scripts:

```bash
sudo ./restore-device.sh ~/Downloads/debian_bullseye_arm64_v2.0.0-4894459_landscape_2025-09-29/
```

### Setup Host Raspberry Pi

NOTE: you _MUST_ set user name to `superbird` in customization settings. The setup [scripts here](./install_config.py) assume this username.

1.  Flash microsd using Raspbery Pi Imager:

<a href="./pictures/raspberry_pi_os_legacy_bullseye_64bit_lite.png"><img src="./pictures/raspberry_pi_os_legacy_bullseye_64bit_lite.png" width=400></a>

<a href="./pictures/raspberry_pi_os_apply_os_customization.png"><img src="./pictures/raspberry_pi_os_apply_os_customization.png" width=400></a>

<a href="./pictures/raspberry_pi_os_customization.png"><img src="./pictures/raspberry_pi_os_customization.png" width=400></a>

1.  insert microsd into the host raspberry pi and power it on (without Car Thing attached)
2.  copy/paste [`prep_host.sh`](./prep_host.sh) to the host
3.  run `prep_host.sh` as `superbird` user
    ```bash
    bash prep_host.sh
    sudo reboot
    ```
4.  Connect the Car Thing into the host device and power it up

## Access

### WebUI

Access the [main WebUI](./pictures/webui_main.png) to:

- change settings
- control screen via embedded vnc client
- inspect webpage using chromium devtools
- simulate button press
- perform some maintenance actions
- view logs

There is also the [Host Maintenance Center](./pictures/webui_host.png), where you can perform additional maintenance actions including updates

### VNC

You can control the Car Thing's screen using a VNC client

```bash
# user: superbird
# password: superbird
# where "host-device" is the hostname or ip of your host raspberry pi
open vnc://superbird:superbird@host-device
```

### SSH

From another device on the same network, you should be able to ssh directly to the Car Thing using port `2022`:

```bash
# user: superbird
# password: superbird
# where "host-device" is the hostname or ip of your host raspberry pi
ssh -p 2022 superbird@host-device
```

And you can connect to the host raspberry pi on the usal port `22`

```bash
# user: superbird
# password: superbird
# where "host-device" is the hostname or ip of your host raspberry pi
ssh superbird@host-device
```

## How to build the images

The [images build script](./build_images.py) runs the image build process twice, once for each orientation, and will use `apt-cacher-ng` if it is installed.

This script _must_ be run on arm64 Debian 12 (Bookworm)

You _must_ provide a set of images dumped from a stock superbird device

```bash
# looking for files in ./dumps/stock_dump/
sudo ./build_images.py
```
