// Javascript for kiosk updater
'use strict';
/* eslint-disable no-unused-vars */

let reload_time = 1; // seconds, how often to reload when waiting for update to complete

function get_urlparam(param) {
    const urlParams = new URLSearchParams(window.location.search);
    let result = urlParams.get(param);
    return result
}

function scroll_div(id) {
    let this_div = document.getElementById(id);
    this_div.scrollTop = this_div.scrollHeight;
}

function scroll_log_to_latest() {
    setTimeout(function () {
        scroll_div("service_log_content");
        scroll_div("upgrade_log_content");
    }, 10);
}

function set_device_name() {
    let result_label = document.getElementById("page_title");
    result_label.innerText = "Kiosk Host Maintenance Center: " + window.location.hostname;
}

function wait_for_update() {
    console.log("Will reload every " + reload_time + " seconds until update completes");
    setTimeout(function () {
        {
            window.location.href = "/";
        }
    }, reload_time * 1000);
}


function handle_refresh() {
    let param = get_urlparam("refresh");
    if (param > 0) {
        console.log("Going to reload page in " + param + " seconds")
        setTimeout(function () {
            window.location.href = "/";
        }, param * 1000);
    }
}

function navigate_superbird() {
    let new_url = window.location.protocol + '//' + window.location.hostname + '/';
    window.open(new_url);
}