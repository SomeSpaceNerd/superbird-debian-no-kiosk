"""
Kiosk Config
"""

from __future__ import annotations

import json
import platform
import urllib.parse

from copy import deepcopy
from uuid import uuid4
from typing import Any, Union, TYPE_CHECKING
from pathlib import Path

from yattag import Doc

from config_schema import CONFIG_SCHEMA

if TYPE_CHECKING:
    from log_manager import LogManager
    from config_schema import Parameter

if platform.system() == 'Linux':
    CONFIG_FOLDER = Path("/etc/kiosk")
else:
    CONFIG_FOLDER = Path().home().joinpath('.kiosk')  # pyright: ignore[reportConstantRedefinition]


class ConfigChecker:
    mandatory_keys_parameter: list[str] = [
        'type', 'label', 'tooltip', 'default'
    ]
    mandatory_keys_category: list[str] = [
        'label', 'description', 'parameters'
    ]

    def __init__(self, logger: LogManager) -> None:
        self.log = logger

    def check(self):
        """Check entire schema, that all required keys are present and values are sane"""
        self.log.debug('Validating config schema')
        for category in CONFIG_SCHEMA:
            self._check_category_schema(category)

        self.log.debug('Config schema validation passed!')

    def _check_category_schema(self, cat_schema: dict[str, Any]):
        """Check schema of a category"""
        for key in self.mandatory_keys_category:
            if key not in cat_schema:
                raise KeyError(f'Missing required category key: {key}')
        for param_schema in cat_schema['parameters']:
            self._check_param_schema(param_schema)

    def _check_param_schema(self, param_schema: dict[str, Any]):
        """Check schema of a parameter"""
        for key in self.mandatory_keys_parameter:
            if key not in param_schema:
                raise KeyError(f'Missing required parameter key: {key}')

        param_type: str = param_schema['type']
        param_validation: Union[None, dict[str, Any]] = param_schema.get('validation', None)
        param_variant: str = param_schema.get('variant', 'None')
        param_default_type: type = type(param_schema['default'])  # pyright: ignore[reportUnknownVariableType]

        if param_type == 'str':
            if param_default_type != str:
                raise ValueError(f'Default value is wrong type for str: {param_default_type.__name__}')

        if param_type == 'number':
            if param_default_type not in [int, float]:
                raise ValueError(f'Default value is wrong type for number: {param_default_type.__name__}')
            if param_variant == 'slider':
                if param_validation is None:
                    raise KeyError('Key "validation" is required for slider variant')
                for key in ['min', 'max', 'step']:
                    if key not in param_validation:
                        raise KeyError('Slider variant must include validation keys: "min", "max", "step"')


class ConfigEditorRenderer:
    """Configuration Editor Renderer"""

    def __init__(self, logger: LogManager, config: Config):
        self.log = logger
        self.config = config

    def gen_id(self) -> str:
        """Generate a unique id"""
        return str(uuid4())

    def render_form(self) -> str:
        """Render an entire form"""
        doc, tag, text = Doc().tagtext()

        cat_ids: dict[str, str] = {}
        for category in CONFIG_SCHEMA:
            cat_id = self.gen_id()
            cat_label: str = category['label']  # pyright: ignore[reportAssignmentType]
            cat_ids[cat_label] = cat_id

        with tag('form', action='/setconfig', method='post'):
            # tab buttons acrosss the top
            with tag('div', klass='tab_buttons_group'):
                for index, category in enumerate(CONFIG_SCHEMA):
                    cat_label: str = category['label']  # pyright: ignore[reportAssignmentType]
                    cat_id = cat_ids[cat_label]
                    cat_onclick_js = f"document.getElementById('{cat_id}').style.display = 'block';"
                    cat_onclick_js += f"document.getElementById('{cat_id}_button').setAttribute('tab_state', 'active');"
                    for _clabel, other_cat_id in cat_ids.items():
                        if other_cat_id == cat_id:
                            continue
                        cat_onclick_js += f"document.getElementById('{other_cat_id}').style.display = 'none';"
                        cat_onclick_js += f"document.getElementById('{other_cat_id}_button').setAttribute('tab_state', 'inactive');"

                    tab_state = 'inactive'
                    if index == 0:
                        tab_state = 'active'
                    with tag('button', type='button', id=f'{cat_id}_button', klass='tab_button', tab_state=tab_state, onclick=cat_onclick_js):
                        text(cat_label)

            # tab content
            with tag('div', klass='config_editor_tab_content'):
                for index, category in enumerate(CONFIG_SCHEMA):
                    cat_label: str = category['label']  # pyright: ignore[reportAssignmentType]
                    cat_id = cat_ids[cat_label]
                    cat_desc: str = category['description']  # pyright: ignore[reportAssignmentType]
                    params: list[Parameter] = category['parameters']  # pyright: ignore[reportAssignmentType]
                    if index == 0:
                        cat_group_style = 'display:block;'
                    else:
                        cat_group_style = 'display:none;'
                    with tag('div', klass='config_editor_widget_group', id=cat_id, style=cat_group_style):
                        with tag('div', klass='config_cat_description'):
                            text(cat_desc)
                        # TODO: using a table for formatting always causes issues eventually
                        with tag('table', style='width:100%;'):
                            for entry in params:
                                elem_label, elem_input = self.render_input(entry)
                                with tag('tr'):
                                    with tag('td', style='text-align:right;'):
                                        doc.asis(elem_label)
                                    with tag('td', style='width:80%;'):
                                        doc.asis(elem_input)

                doc.stag('br')
                # lines.append(prefix + '<input class="config_editor_input_field" type="submit" value="Save">')
                with tag('input', klass='config_editor_input_field', type='submit', value='Save'):
                    pass
        # end of form
        return doc.getvalue()

    def render_label(self, id_: str, label: str, tooltip: str) -> str:
        doc, tag, text = Doc().tagtext()
        with tag('label', ('for', id_), klass='input_label', title=tooltip):
            text(f'{label}: ')
        return doc.getvalue()

    def render_input(self, param_schema: dict[str, Any]) -> tuple[str, str]:
        """Render label & input elements for given parameter"""
        # NOTE: do not do any validation of keys here. trust check_schema() and assume the ones you need are available

        param_id: str = self.gen_id()
        param_name: str = param_schema['name']
        param_type: str = param_schema['type']
        param_label: str = param_schema['label']
        param_tooltip: str = param_schema['tooltip']
        param_current_value = self.config.get(param_name)
        param_variant: str = param_schema.get('variant', 'None')

        doc, tag, text = Doc().tagtext()
        if param_type == 'bool':
            if bool(param_current_value):
                with tag('input', klass='config_editor_input_field', type='checkbox', id=param_id, name=param_name, title=param_tooltip, checked='checked'):
                    pass
            else:
                with tag('input', klass='config_editor_input_field', type='checkbox', id=param_id, name=param_name, title=param_tooltip):
                    pass
        elif param_type == 'str':
            with tag('input', klass='config_editor_input_field', type='text', id=param_id, name=param_name, value=param_current_value, title=param_tooltip):
                pass
        elif param_type in ['int', 'float']:
            if param_variant == 'slider':
                param_validation: dict[str, Any] = param_schema['validation']
                val_min = param_validation['min']
                val_max = param_validation['max']
                val_step = param_validation['step']
                slider_label_id = self.gen_id()
                oninput_js = f'document.getElementById(\'{slider_label_id}\').innerText = this.value;'
                with tag('input', klass='config_editor_input_field', type='range', id=param_id, name=param_name, value=param_current_value, title=param_tooltip, min=val_min, max=val_max, step=val_step, oninput=oninput_js):
                    pass
                with tag('label', id=slider_label_id):
                    text(param_current_value)
            else:
                with tag('input', klass='config_editor_input_field', type='number', id=param_id, name=param_name, value=param_current_value, title=param_tooltip):
                    pass
        elif param_type == 'select':
            param_select_values: dict[str, str] = param_schema['select_values']
            if param_variant == 'radiogroup':
                with tag('div', klass='radioblock', title=param_tooltip):
                    for value, display in param_select_values.items():
                        sel_id = self.gen_id()
                        if value == param_current_value:
                            with tag('input', klass='config_editor_input_field', type='radio', id=sel_id, name=param_name, value=value, checked='checked'):
                                pass
                        else:
                            with tag('input', klass='config_editor_input_field', type='radio', id=sel_id, name=param_name, value=value):
                                pass
                        with tag('label', ('for', sel_id)):
                            text(display)

            elif param_variant == 'dropdown':
                with tag('select', klass='config_editor_input_field', name=param_name, id=param_id, title=param_tooltip):
                    for value, display in param_select_values.items():
                        if value == param_current_value:
                            with tag('option', value=value, selected='selected'):
                                text(display)
                        else:
                            with tag('option', value=value):
                                text(display)

            else:
                raise ValueError(f'Unsupported select variant: {param_variant}')
        else:
            with tag('input', klass='config_editor_input_field', type='text', id=param_id, name=param_name, value=param_current_value, title=param_tooltip):
                pass

        elem_label = self.render_label(id_=param_id, label=param_label, tooltip=param_tooltip)
        elem_input = doc.getvalue()

        return elem_label, elem_input


class Config:
    """Configuration Manager"""

    def __init__(self, logger: LogManager) -> None:
        self.log = logger
        self.config_file = Path(CONFIG_FOLDER).joinpath('config.json')
        self.config_script_file = Path(CONFIG_FOLDER).joinpath('config.sh')  # sourced by bash scripts for config values
        Path(CONFIG_FOLDER).mkdir(exist_ok=True)
        self.log.debug('Initializing Configuration Manager')
        self.renderer = ConfigEditorRenderer(logger=self.log, config=self)
        self.checker = ConfigChecker(logger=self.log)
        self.previous_config: dict[str, Any] = {}
        # this serves as the reference for valid keys, as well as the default values
        self.config: dict[str, Any] = {}
        self.checker.check()
        self.read_schema()
        if self.config_file.is_file():
            self.load()
        else:
            self.save()

    def read_schema(self):
        """Read the schema and create initial self.config"""
        # this initial state of self.config will serve as the reference for valid keys, as well as the default values
        for category in CONFIG_SCHEMA:
            for param_schema in category['parameters']:
                param_name: str = param_schema['name']   # type: ignore
                param_default: str = param_schema['default']   # type: ignore
                self.config[param_name] = param_default

    @staticmethod
    def config_urlquery_to_json(query: str) -> str:
        """Convert config in urlquery to json"""
        payload_dict = urllib.parse.parse_qs(query)

        # values in payload_dict are all single-entry lists, lets fix that
        payload_dict_nolist: dict[str, Any] = {}
        for key, value in payload_dict.items():
            payload_dict_nolist[key] = value[0]
        payload_dict = payload_dict_nolist

        # values are always str, so we need to convert to correct type
        newdict: dict[str, Any] = {}
        for category in CONFIG_SCHEMA:
            for param_schema in category['parameters']:
                param_name: str = param_schema['name']  # type: ignore
                param_type: str = param_schema['type']  # type: ignore
                param_default = param_schema['default']  # type: ignore

                # NOTE: form handling does not include empty values for text inputs, nor any false values for checkboxes
                #   so we use .get()

                if param_type == 'int':
                    param_value = payload_dict.get(param_name, param_default)
                    newdict[param_name] = int(param_value)  # pyright: ignore[reportArgumentType]
                elif param_type == 'float':
                    param_value = payload_dict.get(param_name, param_default)
                    newdict[param_name] = float(param_value)  # pyright: ignore[reportArgumentType]
                elif param_type == 'str':
                    param_value = payload_dict.get(param_name, '')
                    newdict[param_name] = str(param_value)
                elif param_type == 'bool':
                    param_value = payload_dict.get(param_name, False)
                    newdict[param_name] = bool(param_value)
                else:
                    param_value = payload_dict[param_name]
                    newdict[param_name] = param_value

        payload_json = json.dumps(newdict, indent=4)
        return payload_json

    def clear_changes(self):
        """Clear list of changed config parameters"""
        self.previous_config = deepcopy(self.config)

    def get_changes(self) -> list[str]:
        """Get list of changed config parameters since last time clear_changes() was called"""
        changed_keys: list[str] = []
        for key, value in self.config.items():
            if self.previous_config[key] != value:
                changed_keys.append(key)
        return changed_keys

    def to_json(self) -> str:
        """Dump current config as json string"""
        return json.dumps(self.config)

    def from_json(self, configstr: str):
        """Update current config from json string
            copies values for valid keys only, does not add additional keys
        """
        newconfig: dict[str, Any] = json.loads(configstr)
        for key, value in newconfig.items():
            if key in self.config:
                self.config[key] = value
            else:
                self.log.warning(f'Ignoring config key: "{key}" because it does not exist')

    def load(self):
        """Load config from file"""
        self.log.info(f'Reading config from: {self.config_file.absolute()}')
        with open(self.config_file, 'rt', encoding='utf-8') as cf:
            config_json = cf.read()
        self.from_json(config_json)

    def save(self):
        """Save config to file"""
        self.log.info(f'Saving config to: {self.config_file.absolute()}')
        with open(self.config_file, 'wt', encoding='utf-8') as cf:
            cf.write(self.to_json())

    def get(self, key: str):
        """Get a config value"""
        self.log.debug(f'Getting config key: {key}')
        if key not in self.config:
            raise KeyError(f'Invalid config key: {key}')
        return self.config[key]

    def set(self, key: str, value: Any):
        """Set a config value"""
        self.log.debug(f'Setting config key: {key} to {value}')
        if key not in self.config:
            raise KeyError(f'Invalid config key: {key}')
        self.config[key] = value
