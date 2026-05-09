from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import json
from pathlib import Path
import shlex
import shutil
import tarfile
import tempfile
from typing import Any
import zipfile

from .model import ACTION_TYPES, ButtonConfig, Profile, config_dir, load_profile


class ImportProfileError(RuntimeError):
    pass


def import_profile(path: Path) -> Profile:
    if path.suffix.lower() == ".json":
        return load_profile(path)

    with _unpacked(path) as root:
        json_documents = list(_load_json_files(root))
        json_objects = [document["data"] for document in json_documents]
        native = _find_native_profile(json_objects)
        if native:
            return native

        profile = _profile_from_elgato_json(json_documents, path)
        if profile.pages or profile.buttons:
            return profile

    raise ImportProfileError(f"No supported profile data found in {path}")


@contextmanager
def _unpacked(path: Path) -> Iterator[Path]:
    if path.is_dir():
        yield path
        return

    with tempfile.TemporaryDirectory(prefix="streamdeck-import-") as temp:
        root = Path(temp)
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                archive.extractall(root)
            yield root
            return
        if tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                archive.extractall(root)
            yield root
            return

        raise ImportProfileError(f"Unsupported profile package format: {path}")


def _load_json_files(root: Path) -> Iterator[dict[str, Any]]:
    for file in root.rglob("*.json"):
        try:
            with file.open("r", encoding="utf-8") as handle:
                yield {"path": file, "data": json.load(handle)}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue


def _find_native_profile(objects: list[Any]) -> Profile | None:
    for data in objects:
        if not isinstance(data, dict):
            continue
        if "buttons" in data and ("rows" in data or "columns" in data):
            return Profile.from_dict(data)
    return None


def _profile_from_elgato_json(documents: list[dict[str, Any]], source: Path) -> Profile:
    documents = _select_elgato_document_set(documents, source)
    controller_profile = _profile_from_elgato_controllers(documents, source)
    if controller_profile.pages:
        return controller_profile

    profile = Profile(name="Imported")
    objects = [document["data"] for document in documents]
    next_index = 0
    for data in objects:
        for action in _walk_actions(data):
            index = _extract_index(action)
            if index is None:
                index = next_index
                next_index += 1
            if index >= profile.button_count():
                continue
            config = _button_from_action(action)
            if config.action_type != "none" or config.label:
                profile.buttons[str(index)] = config
    return profile


def _select_elgato_document_set(documents: list[dict[str, Any]], source: Path) -> list[dict[str, Any]]:
    grouped: dict[Path, list[dict[str, Any]]] = {}
    for document in documents:
        root = _sdprofile_root(document["path"])
        if root is None:
            continue
        grouped.setdefault(root, []).append(document)

    if len(grouped) <= 1:
        return documents

    candidates: list[tuple[int, int, Path, list[dict[str, Any]]]] = []
    source_name = source.stem.lower()
    for root, group in grouped.items():
        root_name = _root_profile_name(root, group).lower()
        controller_pages = sum(
            1
            for document in group
            if isinstance(document["data"], dict) and _controller_actions(document["data"])
        )
        root_score = 0
        if root_name == source_name:
            root_score += 1000
        if root_name == "main":
            root_score += 900
        if "main" in root_name:
            root_score += 100
        candidates.append((root_score, controller_pages, root, group))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return candidates[0][3]


def _sdprofile_root(path: Path) -> Path | None:
    for parent in (path, *path.parents):
        if parent.name.endswith(".sdProfile"):
            return parent
    return None


def _root_profile_name(root: Path, documents: list[dict[str, Any]]) -> str:
    manifest = root / "manifest.json"
    for document in documents:
        if document["path"] != manifest:
            continue
        data = document["data"]
        if isinstance(data, dict):
            name = data.get("Name") or data.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    return root.stem


def _profile_from_elgato_controllers(documents: list[dict[str, Any]], source: Path) -> Profile:
    metadata = _elgato_profile_metadata(documents)
    pages: list[tuple[int, int, str, str, dict[str, ButtonConfig]]] = []
    parent_targets: dict[str, str] = {}
    child_names: dict[str, str] = {}
    for document in documents:
        data = document["data"]
        if not isinstance(data, dict):
            continue
        actions = _controller_actions(data)
        if not actions:
            continue
        page_id = _page_id_from_manifest(document["path"])
        page_name = str(data.get("Name") or "").strip() or page_id
        buttons: dict[str, ButtonConfig] = {}
        has_parent = False
        for position, action in actions.items():
            if not isinstance(action, dict):
                continue
            if "backtoparent" in str(action.get("UUID", "")).lower():
                has_parent = True
            index = _parse_index(position)
            if index is None or index >= 15:
                continue
            config = _button_from_action(action, document["path"].parent, source)
            if config.action_type == "page" and config.target not in {"", "__parent__", "__previous__", "__next__"}:
                canonical_target = _canonical_page_id(config.target)
                parent_targets[canonical_target] = page_id
                if config.label:
                    child_names[canonical_target] = config.label
            if config.action_type != "none" or config.label:
                buttons[str(index)] = config
        score = len(buttons) - (20 if has_parent else 0)
        pages.append((score, len(buttons), page_id, page_name, buttons))
    if not pages:
        return Profile(name="Imported")
    page_order = metadata.get("page_order", [])
    if page_order:
        order_lookup = {page_id: index for index, page_id in enumerate(page_order)}
        pages.sort(key=lambda item: (0, order_lookup[item[2]]) if item[2] in order_lookup else (1, -item[0]))
    else:
        pages.sort(key=lambda item: (item[0], item[1]), reverse=True)
    profile = Profile(name="Imported")
    top_page_id = metadata.get("current_page") or (page_order[0] if page_order else pages[0][2])
    if top_page_id not in {page_id for _score, _count, page_id, _page_name, _buttons in pages}:
        top_page_id = page_order[0] if page_order else pages[0][2]
    for _score, _count, page_id, page_name, buttons in pages:
        profile.pages[page_id] = buttons
        if page_id in page_order:
            profile.page_names[page_id] = "MAIN" if page_id == page_order[0] else f"Page {page_order.index(page_id) + 1}"
        elif _canonical_page_id(page_id) in child_names:
            profile.page_names[page_id] = _clean_label(child_names[_canonical_page_id(page_id)]).title()
        else:
            profile.page_names[page_id] = _friendly_page_name(page_name, buttons)
    profile.current_page = top_page_id
    profile.buttons = profile.pages[profile.current_page]
    _wire_elgato_navigation(profile, page_order, parent_targets)
    _wire_page_actions(profile)
    return profile


def _elgato_profile_metadata(documents: list[dict[str, Any]]) -> dict[str, Any]:
    for document in documents:
        path = document["path"]
        data = document["data"]
        if not path.parent.name.endswith(".sdProfile") or not isinstance(data, dict):
            continue
        pages = data.get("Pages")
        if not isinstance(pages, dict):
            continue
        page_order = [
            _canonical_page_id(page_id)
            for page_id in pages.get("Pages", [])
            if isinstance(page_id, str)
        ]
        current = pages.get("Current")
        return {
            "page_order": page_order,
            "current_page": _canonical_page_id(current) if isinstance(current, str) else "",
        }
    return {"page_order": [], "current_page": ""}


def _page_id_from_manifest(path: Path) -> str:
    if path.parent.name.endswith(".sdProfile"):
        return "main"
    return path.parent.name


def _controller_actions(data: dict[str, Any]) -> dict[str, Any]:
    actions: dict[str, Any] = {}
    controllers = data.get("Controllers")
    if not isinstance(controllers, list):
        return actions
    for controller in controllers:
        if not isinstance(controller, dict):
            continue
        raw_actions = controller.get("Actions")
        if isinstance(raw_actions, dict):
            actions.update(raw_actions)
    return actions


def _walk_actions(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        if _looks_like_action(value):
            yield value
        for child in value.values():
            yield from _walk_actions(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_actions(child)


def _looks_like_action(data: dict[str, Any]) -> bool:
    keys = {key.lower() for key in data}
    return bool({"uuid", "action", "settings", "title", "name"} & keys) and (
        "settings" in keys or "uuid" in keys or "action" in keys
    )


def _extract_index(action: dict[str, Any]) -> int | None:
    for key in ("key", "index", "position"):
        value = action.get(key) or action.get(key.capitalize())
        parsed = _parse_index(value)
        if parsed is not None:
            return parsed
    return None


def _parse_index(value: Any, columns: int = 5) -> int | None:
    if isinstance(value, int):
        return value
    parsed = _parse_position(value)
    if parsed is not None:
        column, row = parsed
        return row * columns + column
    return None


def _parse_position(value: Any) -> tuple[int, int] | None:
    if isinstance(value, str):
        if value.isdigit():
            return None
        parts = value.replace(";", ",").split(",")
        if len(parts) == 2 and all(part.strip().isdigit() for part in parts):
            column, row = (int(part.strip()) for part in parts)
            return column, row
    if isinstance(value, dict):
        row = value.get("row") or value.get("Row") or value.get("y") or value.get("Y")
        column = value.get("column") or value.get("Column") or value.get("x") or value.get("X")
        if isinstance(row, int) and isinstance(column, int):
            return row, column
    return None


def _button_from_action(action: dict[str, Any], manifest_dir: Path | None = None, source: Path | None = None) -> ButtonConfig:
    settings = action.get("Settings") or action.get("settings") or {}
    if not isinstance(settings, dict):
        settings = {}

    uuid = str(action.get("UUID") or action.get("uuid") or action.get("Action") or action.get("action") or "").lower()
    state = _current_state(action)
    label = _clean_label(_first_text(state, action, settings, keys=("Title", "title", "Name", "name", "Label", "label")))
    target = _first_text(
        settings,
        action,
        keys=(
            "URL",
            "Url",
            "url",
            "Path",
            "path",
            "File",
            "file",
            "Text",
            "text",
            "pastedText",
            "Command",
            "command",
            "Script",
            "script",
        ),
    )
    target = _clean_target(target)
    action_type = _infer_action_type(uuid, settings, target)
    if action_type not in ACTION_TYPES:
        action_type = "none"
    subtitle = "Imported" if action_type == "none" else action_type.upper()
    image_path = _copy_state_image(state, manifest_dir, source)
    if "openchild" in uuid:
        action_type = "page"
        target = str(settings.get("ProfileUUID", ""))
        subtitle = "PAGE"
    elif "backtoparent" in uuid:
        action_type = "page"
        target = "__parent__"
        subtitle = "PAGE"
    elif "page.previous" in uuid:
        action_type = "page"
        target = "__previous__"
        subtitle = "PAGE"
    elif "page.next" in uuid:
        action_type = "page"
        target = "__next__"
        subtitle = "PAGE"
    elif "system.multimedia" in uuid:
        action_type, target, label, subtitle = _multimedia_action(settings, label)
    elif "system.hotkey" in uuid:
        known = _known_hotkey_action(label)
        if known:
            action_type, target, subtitle = known
    return ButtonConfig(label=label, action_type=action_type, target=target, subtitle=subtitle, action_image_path=image_path)


def _infer_action_type(uuid: str, settings: dict[str, Any], target: str) -> str:
    setting_keys = {str(key).lower() for key in settings}
    if "createfolder" in uuid or "backtoparent" in uuid or "page." in uuid or "profile." in uuid:
        return "none"
    if "website" in uuid or "url" in uuid or "url" in setting_keys:
        return "url"
    if "open" in uuid or "file" in setting_keys or "path" in setting_keys:
        return "file"
    if "text" in uuid or "text" in setting_keys:
        return "text"
    if "system" in uuid and target:
        return "file"
    return "none"


def _multimedia_action(settings: dict[str, Any], label: str) -> tuple[str, str, str, str]:
    actions = {
        4: ("volume-mute", "Mute"),
        5: ("volume-up", "Volume Up"),
        6: ("volume-down", "Volume Down"),
    }
    action = actions.get(settings.get("actionIdx"))
    if not action:
        return "none", "", label, "Imported"
    target, fallback_label = action
    return "media", target, label if label != "Multimedia" else fallback_label, "MEDIA"


def _known_hotkey_action(label: str) -> tuple[str, str, str] | None:
    normalized = label.lower()
    if normalized == "emoji keyboard":
        return "shortcut", "ctrl+period", "SHORTCUT"
    if normalized == "screen shot":
        return "command", "gnome-screenshot -i", "COMMAND"
    if normalized == "screen record":
        return "shortcut", "ctrl+alt+shift+r", "SHORTCUT"
    return None


def _first_text(*containers: dict[str, Any], keys: tuple[str, ...]) -> str:
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _current_state(action: dict[str, Any]) -> dict[str, Any]:
    states = action.get("States") or action.get("states")
    if not isinstance(states, list) or not states:
        return {}
    index = action.get("State") or action.get("state") or 0
    if not isinstance(index, int) or index >= len(states):
        index = 0
    state = states[index]
    return state if isinstance(state, dict) else {}


def _clean_target(target: str) -> str:
    if not target:
        return ""
    try:
        parts = shlex.split(target)
    except ValueError:
        return target.strip().strip('"')
    if len(parts) == 1:
        return parts[0]
    return target


def _clean_label(label: str) -> str:
    return " ".join(label.split())


def _copy_state_image(state: dict[str, Any], manifest_dir: Path | None, source: Path | None) -> str:
    image = state.get("Image") or state.get("image")
    if not isinstance(image, str) or not manifest_dir or not source:
        return ""
    image_path = manifest_dir / image
    if not image_path.exists():
        return ""
    asset_dir = config_dir() / "assets" / source.stem
    asset_dir.mkdir(parents=True, exist_ok=True)
    target = asset_dir / f"{manifest_dir.name}-{image_path.name}"
    try:
        shutil.copy2(image_path, target)
    except OSError:
        return ""
    return str(target)


def _friendly_page_name(page_name: str, buttons: dict[str, ButtonConfig]) -> str:
    if page_name and page_name != "main" and not page_name.isupper():
        return _clean_label(page_name)
    labels = [button.label for button in buttons.values() if button.label and button.label not in {"Parent Folder", "Previous Page", "Next Page"}]
    if labels:
        return labels[0]
    return "Main" if page_name == "main" else page_name


def _wire_page_actions(profile: Profile) -> None:
    name_lookup = {name.lower(): page_id for page_id, name in profile.page_names.items()}
    page_lookup = {_canonical_page_id(page_id): page_id for page_id in profile.pages}
    for page_id, buttons in profile.pages.items():
        for config in buttons.values():
            if config.action_type != "page":
                continue
            if config.target in profile.pages:
                continue
            target = page_lookup.get(_canonical_page_id(config.target))
            if target and target != page_id:
                config.target = target
                continue
            if config.target in {"__parent__", "__previous__", "__next__"}:
                continue
            target = name_lookup.get(config.label.lower())
            if target and target != page_id:
                config.target = target
                continue
            config.target = ""


def _wire_elgato_navigation(profile: Profile, page_order: list[str], parent_targets: dict[str, str]) -> None:
    page_order = [page_id for page_id in page_order if page_id in profile.pages]
    _wire_linear_pages(profile, page_order)
    page_lookup = {_canonical_page_id(page_id): page_id for page_id in profile.pages}
    for page_id, buttons in profile.pages.items():
        for button in buttons.values():
            if button.action_type != "page":
                continue
            if button.target == "__parent__":
                button.target = parent_targets.get(_canonical_page_id(page_id), page_order[0] if page_order else profile.current_page)
                continue
            resolved = page_lookup.get(_canonical_page_id(button.target))
            if resolved:
                button.target = resolved


def _canonical_page_id(page_id: str) -> str:
    return page_id.upper()


def _name_pages_from_parent_buttons(profile: Profile) -> None:
    unnamed_pages = [
        page_id
        for page_id, name in profile.page_names.items()
        if page_id != profile.current_page and (name == page_id or name in {"Open", "Text", "Website"})
    ]
    if not unnamed_pages:
        return
    parent_buttons = [
        button
        for button in profile.pages.get(profile.current_page, {}).values()
        if button.action_type == "page" and button.label
    ]
    for page_id, button in zip(unnamed_pages, parent_buttons):
        profile.page_names[page_id] = button.label


def _resolve_known_navigation(profile: Profile) -> None:
    label_to_page = _infer_page_roles(profile)
    profile.page_names[profile.current_page] = "MAIN"

    for page_id, buttons in profile.pages.items():
        for button in buttons.values():
            if button.action_type != "page":
                continue
            target = label_to_page.get(button.label) or _parent_target_for(profile, page_id, button.label, label_to_page)
            if target and target != page_id:
                button.target = target
                continue

            if button.target == "__parent__":
                button.target = profile.current_page

    _wire_original_page_buttons(profile, label_to_page)


def _infer_page_roles(profile: Profile) -> dict[str, str]:
    roles: dict[str, str] = {}
    for page_id, buttons in profile.pages.items():
        if page_id == profile.current_page:
            continue
        labels = {button.label for button in buttons.values()}
        targets = {button.target for button in buttons.values()}
        file_count = sum(1 for button in buttons.values() if button.action_type == "file")
        text_count = sum(1 for button in buttons.values() if button.action_type == "text")
        if "Spotify" in labels or file_count >= 8:
            roles.setdefault("Apps", page_id)
        if {"Books", "Kindle"} & labels:
            roles.setdefault("Books", page_id)
        if {"Plugins", "Folders", "Actions", "Pages"} & labels:
            roles.setdefault("Tutorials", page_id)
        if text_count >= 8 and any(button.action_type == "text" and _contains_emoji(button.target) for button in buttons.values()):
            roles.setdefault("Emojis", page_id)
        if {"Trailblazers", "Github"} & labels:
            roles.setdefault("Links", page_id)
        if {"Dating", "Bible Study"} & labels:
            roles.setdefault("Links", page_id)
        if {"eharmony", "Sniffies"} & labels:
            roles.setdefault("Dating", page_id)
        if {"Bible Gateway", "Saint Luke"} & labels:
            roles.setdefault("Bible Study", page_id)
        if {"Local ID", "Apple ID", "Home Address"} & labels:
            roles.setdefault("Personal Info", page_id)
            roles.setdefault("Local ID", page_id)

    for label, page_id in roles.items():
        if label == "Local ID":
            continue
        profile.page_names[page_id] = label
    return roles


def _contains_emoji(text: str) -> bool:
    return any(ord(char) > 0x2600 for char in text)


def _wire_linear_pages(profile: Profile, page_ids: list[str]) -> None:
    page_ids = [page_id for page_id in page_ids if page_id in profile.pages]
    if len(page_ids) < 2:
        return
    for index, page_id in enumerate(page_ids):
        for button in profile.pages[page_id].values():
            if button.action_type != "page":
                continue
            if button.target == "__previous__":
                button.target = page_ids[(index - 1) % len(page_ids)]
            elif button.target == "__next__":
                button.target = page_ids[(index + 1) % len(page_ids)]


def _parent_target_for(profile: Profile, page_id: str, label: str, roles: dict[str, str]) -> str:
    if label != "Parent Folder":
        return ""
    if page_id in {roles.get("Dating"), roles.get("Bible Study")}:
        return roles.get("Links", profile.current_page)
    if page_id == roles.get("Books"):
        return roles.get("Apps", profile.current_page)
    return profile.current_page


def _wire_original_page_buttons(profile: Profile, roles: dict[str, str]) -> None:
    top_page2 = _page_with_label(profile, "Personal Info")
    top_page3 = _page_with_only_previous(profile)
    top_sequence = [page_id for page_id in (profile.current_page, top_page2, top_page3) if page_id]
    _wire_linear_pages(profile, top_sequence)

    apps_sequence = [page_id for page_id in (roles.get("Apps"), roles.get("Books"), _empty_prev_next_page(profile)) if page_id]
    _wire_linear_pages(profile, apps_sequence)


def _page_with_label(profile: Profile, label: str) -> str:
    for page_id, buttons in profile.pages.items():
        if any(button.label == label for button in buttons.values()):
            return page_id
    return ""


def _page_with_only_previous(profile: Profile) -> str:
    for page_id, buttons in profile.pages.items():
        labels = {button.label for button in buttons.values() if button.label}
        if labels == {"Previous Page"}:
            return page_id
    return ""


def _empty_prev_next_page(profile: Profile) -> str:
    for page_id, buttons in profile.pages.items():
        labels = {button.label for button in buttons.values() if button.label}
        if labels == {"Previous Page", "Next Page"} and len(buttons) == 2:
            return page_id
    return ""
