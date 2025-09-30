#!/bin/bash

# setup vnc server

# To change password, run: sudo vncpasswd /etc/vnc/vnc_passwd

while :; do
    /usr/bin/X0tigervnc -display=:0 -rfbport=5900 -rfbauth=/etc/vnc/vnc_passwd -SecurityTypes=VncAuth
    sleep 0.5
done
