// novnc integration
// NOTE: based on this: https://github.com/novnc/noVNC/blob/master/vnc_lite.html

const VNC_PASSWORD = 'idunno';
const VNC_HOST = window.location.hostname;
const VNC_PORT = 5901;  // websockify
const VNC_RECONNECT = true;  // if not-clean disconnect, attempt reconnect
const VNC_RECONNECT_DELAY = 2000;  // milliseconds, attempt reconnect after this time


import RFB from './novnc/core/rfb.js';
let rfb;


function noVNC_connectedToServer(e) {
    console.log("noVNC Client: Connected");
}

function noVNC_disconnectedFromServer(e) {
    if (e.detail.clean) {
        console.log("noVNC Client: Disconnected");
    } else {
        console.log("noVNC Client: Something went wrong, connection is closed");
    }
    if (VNC_RECONNECT) {
        noVNC_reconnect();
    }
}

function noVNC_reconnect() {
    console.log("noVNC Client: Reconnecting in " + VNC_RECONNECT_DELAY + "ms");
    setTimeout(function () {
        noVNC_Connect();
    }, VNC_RECONNECT_DELAY);
}

function noVNC_Connect(re = false) {
    if (re) {
        console.log("noVNC Client: Re-connecting");
    } else {
        console.log("noVNC Client: Connecting");
    }

    // Build the websocket URL used to connect
    let url = 'ws://' + VNC_HOST + ':' + VNC_PORT + '/' + 'websockify';

    console.log("noVNC Client: Connecting to " + url);

    // Creating a new RFB object will start a new connection
    rfb = new RFB(document.getElementById('vnc_client_screen'), url, { credentials: { password: VNC_PASSWORD } });

    // Add listeners to important events from the RFB module
    rfb.addEventListener("connect", noVNC_connectedToServer);
    rfb.addEventListener("disconnect", noVNC_disconnectedFromServer);

    // Set parameters that can be changed on an active connection
    rfb.viewOnly = false;
    rfb.scaleViewport = true;
}

noVNC_Connect();
