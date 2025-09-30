"""
Kiosk Config Schema
"""

from typing import Any, Union

ParamKeys = Union[str, int, float, dict[str, Any]]
Parameter = dict[str, ParamKeys]
Category = dict[str, Union[str, list[Parameter]]]


CONFIG_SCHEMA: list[Category] = [
    {
        'label': 'Browser',
        'description': 'Configure browser details',
        'parameters': [
            {
                "name": "url",
                "label": "Browser URL",
                "tooltip": "URL to point the browser at",
                "default": "https://192.168.1.144:8123/lovelace",
                "type": "str",
                "validation": {
                    "str_type": "url"
                }
            },
            {
                "name": "browser_scale",
                "label": "Browser Scale",
                "tooltip": "scale/zoom of the browser",
                "default": 1.0,
                "type": "float",
                "variant": "slider",
                "comment": "below 0.5 you get weird rendering issues, and below 0.2 causes chromium to hang and eventually crash",
                "validation": {
                    "min": 0.5,
                    "max": 3.0,
                    "step": 0.1
                }
            },
        ]
    },
    {
        'label': 'VNC Server',
        'description': 'Configure VNC Server',
        'parameters': [
            {
                "name": "vnc_password",
                "label": "VNC Password",
                "tooltip": "Password for VNC service",
                "default": "superbird",
                "type": "str",
                "validation": {
                    "max_length": 8
                }
            },
        ]
    },
    {
        'label': 'Screen',
        'description': 'Adjust screen',
        'parameters': [
            {
                "name": "screen_sleep_allow",
                "label": "Allow Screen Sleep",
                "tooltip": "Allow the screen to go to sleep",
                "default": False,
                "type": "bool"
            },
            {
                "name": "screen_sleep_time",
                "label": "Screen Timeout (minutes)",
                "tooltip": "minutes, sleep screen after N minutes; Allow Screen Sleep must be checked for effect",
                "default": 10,
                "type": "int",
                "variant": "slider",
                "validation": {
                    "min": 0,
                    "max": 60,
                    "step": 1
                }
            },
            {
                "name": "screen_brightness",
                "label": "Screen Brightness",
                "tooltip": "Adjust the brightness of the screen, when on",
                "default": 128,
                "type": "int",
                "variant": "slider",
                "comment": "Brightness is actually 255 (off) to 1 (brightest), and 0 (off). This translation will be done by backend",
                "validation": {
                    "min": 0,
                    "max": 256,
                    "step": 4
                }
            },
            {
                "name": "screen_rotate",
                "label": "Screen Rotation",
                "tooltip": "Rotate the screen 90deg CW or CCW, or upside-down",
                "default": "None",
                "type": "select",
                "comment": "variants: dropdown, radiogroup",
                "variant": "dropdown",
                "select_values": {
                    "None": "None",
                    "CW": "Clockwise",
                    "CCW": "Counter-Clockwise",
                    "UD": "Upside-Down"
                }
            },
        ]
    },
    {
        'label': 'HomeAssistant',
        'description': 'Configure connection to HomeAssistant',
        'parameters': [
            {
                "name": "ha_server",
                "label": "Address (including port)",
                "tooltip": "URL to point the chromium browser at",
                "default": "https://192.168.1.144:8123",
                "type": "str",
                "validation": {
                    "str_type": "url",
                    "url_port_required": True
                }
            },
            {
                "name": "ha_token",
                "label": "Long-Lived Token",
                "tooltip": "Long-Lived token for HomeAssistant API",
                "default": "",
                "type": "str"
            },
        ]
    },
    {
        'label': 'Knob',
        'description': 'Configure knob and front button',
        'parameters': [
            {
                "name": "room_light",
                "label": "Room Light Entity",
                "tooltip": "Light entity to be controlled by the knob",
                "default": "light.office",
                "type": "str",
                "validation": {
                    "contains_all": [
                        "light."
                    ]
                }
            },
            {
                "name": "level_increment",
                "label": "Level Increment",
                "tooltip": "when you turn the knob, brightness will go up or down by this amount; brightness is 0 - 255",
                "default": 32,
                "type": "int",
                "variant": "slider",
                "validation": {
                    "min": 8,
                    "max": 128,
                    "step": 8
                }
            },
            {
                "name": "esc_scene",
                "label": "Button next to knob (scene, automation, or script)",
                "tooltip": "scene/automation/script to call when the button next to knob is pressed",
                "default": "scene.office_bright",
                "type": "str",
                "validation": {
                    "contains_one": [
                        "scene.",
                        "automation.",
                        "script."
                    ]
                }
            },
        ]
    },
    {
        'label': 'Side Buttons',
        'description': 'Assign a scene, automation, or script to buttons on side',
        'parameters': [
            {
                "name": "room_scene_1",
                "label": "Button 1",
                "tooltip": "scene/automation/script to call when button 1 is pressed",
                "default": "scene.office_bright",
                "type": "str",
                "validation": {
                    "contains_one": [
                        "scene.",
                        "automation.",
                        "script."
                    ]
                }
            },
            {
                "name": "room_scene_2",
                "label": "Button 2",
                "tooltip": "scene/automation/script to call when button 2 is pressed",
                "default": "scene.office_half",
                "type": "str",
                "validation": {
                    "contains_one": [
                        "scene.",
                        "automation.",
                        "script."
                    ]
                }
            },
            {
                "name": "room_scene_3",
                "label": "Button 3",
                "tooltip": "scene/automation/script to call when button 3 is pressed",
                "default": "scene.office_blue",
                "type": "str",
                "validation": {
                    "contains_one": [
                        "scene.",
                        "automation.",
                        "script."
                    ]
                }
            },
            {
                "name": "room_scene_4",
                "label": "Button 4",
                "tooltip": "scene/automation/script to call when button 4 is pressed",
                "default": "",
                "type": "str",
                "validation": {
                    "contains_one": [
                        "scene.",
                        "automation.",
                        "script."
                    ]
                }
            },
            {
                "name": "room_scene_5",
                "label": "Button 5 (recessed)",
                "tooltip": "scene/automation/script to call when button 5 is pressed",
                "default": "",
                "type": "str",
                "validation": {
                    "contains_one": [
                        "scene.",
                        "automation.",
                        "script."
                    ]
                }
            },
        ]
    },
]
