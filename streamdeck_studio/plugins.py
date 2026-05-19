from __future__ import annotations

from dataclasses import dataclass
import shutil
import json
from pathlib import Path
import re
import shlex
from typing import Any

from .model import config_dir


PLUGIN_MANIFEST = "plugin.json"


class PluginError(RuntimeError):
    pass


@dataclass(frozen=True)
class PluginAction:
    plugin_id: str
    plugin_name: str
    action_id: str
    label: str
    command: str | list[str]
    plugin_dir: Path
    description: str = ""
    shell: bool = False
    settings_template: dict[str, Any] | None = None
    icon: str = ""

    @property
    def qualified_id(self) -> str:
        return f"{self.plugin_id}.{self.action_id}"

    def target_template(self) -> str:
        if not self.settings_template:
            return self.qualified_id
        return json.dumps(
            {
                "plugin": self.plugin_id,
                "action": self.action_id,
                "settings": self.settings_template,
            },
            indent=2,
            sort_keys=True,
        )


@dataclass(frozen=True)
class PluginLibraryItem:
    plugin_id: str
    name: str
    description: str
    action_count: int
    manifest_path: Path
    installed: bool = False
    source_url: str = ""
    source_name: str = ""
    source_stars: int = 0
    config_field_count: int = 0


@dataclass(frozen=True)
class PluginConfigField:
    key: str
    label: str
    kind: str = "text"
    default: str = ""
    required: bool = False
    secret: bool = False
    help: str = ""
    options: tuple[str, ...] = ()


def plugins_dir() -> Path:
    return config_dir() / "plugins"


def plugin_library_dir() -> Path:
    return Path(__file__).parent / "resources" / "plugin-library"


def list_library_plugins() -> list[PluginLibraryItem]:
    installed = installed_plugin_ids()
    items: list[PluginLibraryItem] = []
    directory = plugin_library_dir()
    if not directory.exists():
        return []
    for manifest_path in sorted(directory.glob("*.json")):
        try:
            data = _load_manifest_data(manifest_path)
            if not isinstance(data.get("actions"), list):
                continue
            plugin_id = _identifier(str(data.get("id", manifest_path.stem)))
            actions = data.get("actions", [])
            action_count = len([action for action in actions if isinstance(action, dict)])
            try:
                source_stars = int(data.get("source_stars", 0) or 0)
            except (TypeError, ValueError):
                source_stars = 0
            items.append(
                PluginLibraryItem(
                    plugin_id=plugin_id,
                    name=str(data.get("name", plugin_id)).strip() or plugin_id,
                    description=str(data.get("description", "")).strip(),
                    action_count=action_count,
                    manifest_path=manifest_path,
                    installed=plugin_id in installed,
                    source_url=str(data.get("source_url", "")).strip(),
                    source_name=str(data.get("source_name", "")).strip(),
                    source_stars=max(0, source_stars),
                    config_field_count=len(_config_fields_from_data(data)),
                )
            )
        except PluginError:
            continue
    return sorted(items, key=lambda item: item.name.casefold())


def installed_plugin_ids() -> set[str]:
    ids: set[str] = set()
    for manifest_path in _manifest_paths():
        try:
            data = _load_manifest_data(manifest_path)
        except PluginError:
            continue
        ids.add(_identifier(str(data.get("id", manifest_path.parent.name))))
    return ids


def install_library_plugin(plugin_id: str) -> Path:
    clean_id = _identifier(plugin_id)
    for item in list_library_plugins():
        if item.plugin_id == clean_id:
            target_dir = plugins_dir() / clean_id
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / PLUGIN_MANIFEST
            shutil.copy2(item.manifest_path, target)
            return target
    raise PluginError(f"Plugin is not in the library: {plugin_id}")


def uninstall_plugin(plugin_id: str) -> None:
    clean_id = _identifier(plugin_id)
    target_dir = plugins_dir() / clean_id
    if not target_dir.exists():
        return
    shutil.rmtree(target_dir)


def plugin_config_path(plugin_id: str) -> Path:
    return plugins_dir() / _identifier(plugin_id) / "config.json"


def load_plugin_config(plugin_id: str) -> dict[str, Any]:
    path = plugin_config_path(plugin_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_plugin_config(plugin_id: str, values: dict[str, Any]) -> None:
    path = plugin_config_path(plugin_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    clean_values = {
        str(key): value
        for key, value in values.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }
    path.write_text(json.dumps(clean_values, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def plugin_config_fields(plugin_id: str) -> list[PluginConfigField]:
    manifest = plugins_dir() / _identifier(plugin_id) / PLUGIN_MANIFEST
    try:
        data = _load_manifest_data(manifest)
    except PluginError:
        return []
    return _config_fields_from_data(data)


def list_plugin_actions() -> list[PluginAction]:
    actions: list[PluginAction] = []
    for manifest_path in _manifest_paths():
        try:
            actions.extend(_load_manifest_actions(manifest_path))
        except PluginError:
            continue
    return sorted(actions, key=lambda action: (action.plugin_name.casefold(), action.label.casefold()))


def list_plugin_actions_for(plugin_id: str) -> list[PluginAction]:
    clean_id = _identifier(plugin_id)
    return [action for action in list_plugin_actions() if action.plugin_id == clean_id]


def get_plugin_action(plugin_id: str, action_id: str) -> PluginAction | None:
    for action in list_plugin_actions():
        if action.plugin_id == plugin_id and action.action_id == action_id:
            return action
    return None


def parse_plugin_target(target: str) -> tuple[str, str, dict[str, Any]]:
    clean = target.strip()
    if not clean:
        raise PluginError("Plugin action has no target.")
    settings: dict[str, Any] = {}
    if clean.startswith("{"):
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise PluginError(f"Invalid plugin target JSON: {exc.msg}") from exc
        if not isinstance(payload, dict):
            raise PluginError("Plugin target JSON must be an object.")
        plugin_id = str(payload.get("plugin", "")).strip()
        action_id = str(payload.get("action", "")).strip()
        raw_settings = payload.get("settings", {})
        if isinstance(raw_settings, dict):
            settings = raw_settings
        elif raw_settings:
            raise PluginError("Plugin target settings must be an object.")
    else:
        separator = "." if "." in clean else ":"
        plugin_id, _, action_id = clean.partition(separator)
        plugin_id = plugin_id.strip()
        action_id = action_id.strip()
    if not plugin_id or not action_id:
        raise PluginError("Plugin target must identify a plugin and action.")
    return plugin_id, action_id, settings


def command_for_action(action: PluginAction, settings: dict[str, Any] | None = None) -> str | list[str]:
    clean_settings = {**load_plugin_config(action.plugin_id), **(settings or {})}
    settings_json = json.dumps(clean_settings, sort_keys=True)
    replacements = {
        "home": str(Path.home()),
        "plugin_dir": str(action.plugin_dir),
        "settings_json": settings_json,
    }
    for key, value in clean_settings.items():
        if isinstance(value, (str, int, float, bool)):
            replacements[str(key)] = str(value)
    if isinstance(action.command, list):
        return [_format_command_part(part, replacements) for part in action.command]
    return _format_command_part(action.command, replacements)


def _format_command_part(value: str, replacements: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return replacements.get(key, match.group(0))

    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", replace, value)


def _manifest_paths() -> list[Path]:
    directory = plugins_dir()
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob(f"*/{PLUGIN_MANIFEST}") if path.is_file())


def _load_manifest_actions(path: Path) -> list[PluginAction]:
    data = _load_manifest_data(path)
    plugin_id = _identifier(str(data.get("id", path.parent.name)))
    plugin_name = str(data.get("name", plugin_id)).strip() or plugin_id
    raw_actions = data.get("actions", [])
    if not isinstance(raw_actions, list):
        raise PluginError(f"Plugin actions must be a list: {path}")
    actions: list[PluginAction] = []
    for raw_action in raw_actions:
        if not isinstance(raw_action, dict):
            continue
        action_id = _identifier(str(raw_action.get("id", "")))
        command = raw_action.get("command")
        if not action_id or not _valid_command(command):
            continue
        actions.append(
            PluginAction(
                plugin_id=plugin_id,
                plugin_name=plugin_name,
                action_id=action_id,
                label=str(raw_action.get("label", action_id)).strip() or action_id,
                description=str(raw_action.get("description", "")).strip(),
                command=command,
                shell=bool(raw_action.get("shell", False)),
                settings_template=_settings_template(raw_action.get("settings_template")),
                icon=str(raw_action.get("icon", "")).strip(),
                plugin_dir=path.parent,
            )
        )
    return actions


def _settings_template(raw_template: Any) -> dict[str, Any] | None:
    if isinstance(raw_template, dict):
        return raw_template
    return None


def _config_fields_from_data(data: dict[str, Any]) -> list[PluginConfigField]:
    raw_fields = data.get("config_fields", [])
    if not isinstance(raw_fields, list):
        return []
    fields: list[PluginConfigField] = []
    for raw_field in raw_fields:
        if not isinstance(raw_field, dict):
            continue
        key = str(raw_field.get("key", "")).strip()
        if not key:
            continue
        raw_options = raw_field.get("options", ())
        options = tuple(str(option) for option in raw_options) if isinstance(raw_options, list) else ()
        fields.append(
            PluginConfigField(
                key=key,
                label=str(raw_field.get("label", key)).strip() or key,
                kind=str(raw_field.get("kind", "text")).strip() or "text",
                default=str(raw_field.get("default", "")),
                required=bool(raw_field.get("required", False)),
                secret=bool(raw_field.get("secret", False)),
                help=str(raw_field.get("help", "")).strip(),
                options=options,
            )
        )
    return fields


def _load_manifest_data(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PluginError(f"Could not read plugin manifest: {path}") from exc
    if not isinstance(data, dict):
        raise PluginError(f"Plugin manifest must be an object: {path}")
    return data


def _valid_command(command: Any) -> bool:
    if isinstance(command, str):
        try:
            return bool(shlex.split(command))
        except ValueError:
            return False
    return isinstance(command, list) and all(isinstance(part, str) and part for part in command)


def _identifier(value: str) -> str:
    return value.strip().replace("/", "-").replace("\\", "-")
