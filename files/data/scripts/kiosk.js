// Javascript for Kiosk webui
'use strict';
/* eslint-disable no-unused-vars */

// These lines will be rewritten by backend at runtime
const VERSION = "Unknown";
const WEBSERVER_PORT = 80;
const RELOAD_TIME = 4;  // seconds, how long after save to reload the page
const DEV_ENVIRONMENT = false;

// Functions

function loadJSON(path, callback) {
    // fetch json from a url endpoint, without using jquery
    console.debug('loadJSON: ' + path);
    var xhr = new XMLHttpRequest();


    xhr.onreadystatechange = function () {
        if (xhr.readyState === XMLHttpRequest.DONE) {
            if (xhr.status === 200) {
                if (callback)
                    callback(JSON.parse(xhr.responseText));
            }
        }
    };
    // xhr.onerror = null;
    xhr.open("GET", path, true);
    xhr.send();
}

function get_chromium_debug_url() {
    // we are using HAProxy to rewrite Host header to let this work, but that means we need to manually rewrite devtoolsFrontendUrl because it doesnt have hostname:port
    let port = 9223;
    let url = "http://" + location.hostname + ":" + port + "/json";
    loadJSON(url, function (data) {
        let given_url = String(data[0]['devtoolsFrontendUrl']);
        console.log("Given: ", given_url);
        let newsnippet = location.hostname + ":" + port + "/devtools/page";
        let corrected_url = "http://" + location.hostname + ":" + port + given_url.replace("/devtools/page", newsnippet);
        console.log("Corrected: ", corrected_url);

        let target = document.getElementById("browser_devtools");
        let iframe = document.createElement("iframe");
        iframe.src = corrected_url;
        iframe.setAttribute("id", "browser_devtools_iframe");
        target.appendChild(iframe);
    });
}

function simulate_key(key) {
    // simulate a key/button press
    // TODO should urlescape key, even tho we wont ever use invalid values
    console.log("Simulating key: " + key);
    let url = window.location.protocol + "//" + location.hostname + ":" + WEBSERVER_PORT + "/simulatekey?key=" + encodeURIComponent(key);
    loadJSON(url);

}

function maint_action(action) {
    // Perform a maintenance action
    console.log("Maintenance action: " + action);

    // show overlay first
    if (action === 'Reboot Superbird') {
        show_timer_overlay('Rebooting', 'Rebooting superbird device', 60);
    } else if (action === 'Clear Browser Data') {
        show_timer_overlay('Clearing', 'Clearing browser data', 5);
    } else if (action === 'Restart Kiosk Service') {
        show_timer_overlay('Restarting service', 'Restarting kiosk service', 12);
    }

    let url = window.location.protocol + "//" + location.hostname + ":" + WEBSERVER_PORT + "/maintenance?action=" + encodeURIComponent(action);
    loadJSON(url);

}

// Overlay

function show_overlay(title, message) {
    // show the overlay with given message
    let odiv = document.getElementById('page_overlay');
    let otitle = document.getElementById('page_overlay_title');
    let otext = document.getElementById('page_overlay_text');

    otitle.innerText = title;
    otext.innerText = message;
    odiv.style.display = 'block';
}

function hide_overlay() {
    // show the overlay
    let odiv = document.getElementById('page_overlay');
    odiv.style.display = 'none';
}

function show_timer_overlay(title, message, reload_time) {
    // show an overlay with a timeout (in seconds), before reloading the page
    for (let i = 1; i < reload_time; i++) {
        setTimeout(function () {
            show_overlay(title, message + ', will reload in: ' + (reload_time - i));
        }, (i * 1000));
    }

    setTimeout(function () {
        show_overlay(title, 'Reloading page...');
        let new_url = window.location.protocol + '//' + window.location.hostname + ':' + WEBSERVER_PORT + '/'
        window.location.href = new_url;
    }, (reload_time * 1000));
}


function set_config_status(status) {
    let result_label = document.getElementById("config_status_label");
    result_label.innerText = status;
    console.log(status);
}

function set_device_name() {
    let result_label = document.getElementById("device_name");
    result_label.innerText = "Device: " + window.location.hostname;
}

// version_label
function set_version() {
    let result_label = document.getElementById("version_label");
    result_label.innerText = "Version: " + VERSION;
}

function get_urlparam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    let result = urlParams.get(param);
    return result
}

function scroll_log_to_latest() {
    setTimeout(function () {
        console.log('Scrolling to most recent');
        let log_div = document.getElementById('log_content');
        log_div.scrollTop = log_div.scrollHeight;
    }, 10);
}


// Entrypoints

function common_entrypoint() {
    // used by all entrypoint functions
    set_device_name();
    set_version();
    console.log('Kiosk v' + VERSION);
}

function config_entrypoint() {
    // for the admin page
    console.info('Config Entrypoint');
    common_entrypoint();


    let result = get_urlparam('result');
    if (result) {
        set_config_status('Status: config save ' + result + '!');
    }
}

function logs_entrypoint() {
    // for the logs viewer page
    console.info('Logs Entrypoint');
    common_entrypoint();
    let service = get_urlparam('service');
    if (!(service === 'Running Processes')) {
        scroll_log_to_latest();
    }
}

function vnc_entrypoint() {
    // for the vnc client page
    console.info('VNC Entrypoint');
    common_entrypoint();
}

function devtools_entrypoint() {
    // for the chromium devtools page
    console.info('Devtools Entrypoint');
    common_entrypoint();
    get_chromium_debug_url();
}