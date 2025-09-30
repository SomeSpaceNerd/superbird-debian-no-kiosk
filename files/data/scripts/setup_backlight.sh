#!/bin/bash
# set up the backlight by following if display is on or off

# 0 - 255, display brightness when On
# 	NOTE: 0 = off
# 		  1 = 100%
# 		255 = 0%
BRIGHTNESS=100

if [ -f "/etc/kiosk/config.sh" ]; then
	source "/etc/kiosk/config.sh"
fi


# seconds, how often to check state of display
CHECK_TIME=0.2

# the backlight brightness control
BACKLIGHT="/sys/devices/platform/backlight/backlight/aml-bl/brightness"

echo "NOTE: it is normal to see \"unable to open display\" many times until Xorg has started"
while :;do
	DISPLAY_STATUS=$(DISPLAY=:0 xset -q|grep "Monitor is"|awk '{print $3}')
	if [ "$DISPLAY_STATUS" == "Off" ]; then
		# only turn off backlight if it actually says "Off", fallback is always on
		echo 0 > $BACKLIGHT
	else
		echo $BRIGHTNESS > $BACKLIGHT
	fi
	sleep $CHECK_TIME
done

# try to leave backlight on if the loop breaks
echo $BRIGHTNESS > $BACKLIGHT
