// old javscript not used anymore, but might be useful again later

function sendJSON(path, content, callback) {
    // send json content using post url endpoint, without using jquery
    console.debug('sendJSON: ' + path);
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
    xhr.open("POST", path, true);
    xhr.send(content);
}

function get_config(callback) {
    let url = window.location.protocol + "//" + location.hostname + ":" + WEBSERVER_PORT + "/getconfig";
    loadJSON(url, function (result) {
        callback(result);
    })
}

function set_config(config) {
    let url = window.location.protocol + "//" + location.hostname + ":" + WEBSERVER_PORT + "/setconfig";
    sendJSON(url, config);
}
