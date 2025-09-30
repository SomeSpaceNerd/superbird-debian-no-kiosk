#!/bin/bash

# run the websockify server, which translates the tcp -> websocket for vnc service, to make it accessible from a browser

python3 -m websockify 5901 0.0.0.0:5900

