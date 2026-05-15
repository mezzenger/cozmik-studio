from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


ACTION_TYPES = ("none", "command", "shell", "url", "file", "text", "page", "media", "shortcut", "keys")
LABEL_POSITIONS = ("bottom", "top", "middle")
DEFAULT_PROFILE_ID = "default"
NEW_PROFILE_NAME = "New Profile"
MCP_PROFILE_ID = "mcp-deck"
MCP_PROFILE_NAME = "MCP Deck"
DEFAULT_PROFILE_PAGES = {"main": "Main", "tutorials": "Tutorials"}
DEFAULT_ICON_NAMES = (
    "home",
    "folder",
    "up-arrow",
    "left-arrow",
    "right-arrow",
    "play",
    "pause",
    "stop",
    "record",
    "image",
    "mic-mute",
    "camera",
    "settings",
    "globe",
    "chat",
    "terminal",
    "email",
    "lightbulb",
    "star",
    "power",
    "apps",
    "calendar",
    "clock",
    "cloud",
    "search",
    "calculator",
    "volume-up",
    "volume-down",
    "mute",
    "screenshot",
)


@dataclass
class ButtonConfig:
    label: str = ""
    action_type: str = "none"
    target: str = ""
    subtitle: str = ""
    background: str = "#1f2937"
    foreground: str = "#ffffff"
    image_path: str = ""
    background_image_path: str = ""
    action_image_path: str = ""
    label_position: str = "bottom"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ButtonConfig":
        action_type = data.get("action_type", "none")
        if action_type not in ACTION_TYPES:
            action_type = "none"
        label_position = data.get("label_position", "bottom")
        if label_position not in LABEL_POSITIONS:
            label_position = "bottom"
        return cls(
            label=str(data.get("label", "")),
            action_type=action_type,
            target=str(data.get("target", "")),
            subtitle=str(data.get("subtitle", "")),
            background=str(data.get("background", "#1f2937")),
            foreground=str(data.get("foreground", "#ffffff")),
            image_path=str(data.get("image_path", "")),
            background_image_path=str(data.get("background_image_path", "")),
            action_image_path=str(data.get("action_image_path", "")),
            label_position=label_position,
        )


@dataclass
class Profile:
    name: str = "Default"
    rows: int = 3
    columns: int = 5
    buttons: dict[str, ButtonConfig] = field(default_factory=dict)
    pages: dict[str, dict[str, ButtonConfig]] = field(default_factory=dict)
    page_names: dict[str, str] = field(default_factory=dict)
    current_page: str = "main"

    def button_count(self) -> int:
        return self.rows * self.columns

    def page_ids(self) -> list[str]:
        if not self.pages:
            self.pages = {"main": self.buttons}
            self.page_names.setdefault("main", self.name or "Main")
            self.current_page = "main"
        return list(self.pages)

    def current_buttons(self) -> dict[str, ButtonConfig]:
        self.page_ids()
        if self.current_page not in self.pages:
            self.current_page = self.page_ids()[0]
        return self.pages[self.current_page]

    def get_button(self, index: int, page_id: str | None = None) -> ButtonConfig:
        if page_id:
            self.ensure_page(page_id)
            return self.pages[page_id].setdefault(str(index), ButtonConfig())
        return self.current_buttons().setdefault(str(index), ButtonConfig())

    def set_button(self, index: int, config: ButtonConfig, page_id: str | None = None) -> None:
        if page_id:
            self.ensure_page(page_id)
            self.pages[page_id][str(index)] = config
        else:
            self.current_buttons()[str(index)] = config

    def clear_button(self, index: int) -> None:
        self.current_buttons().pop(str(index), None)

    def swap_buttons(self, first_index: int, second_index: int) -> None:
        if first_index == second_index:
            return
        buttons = self.current_buttons()
        first_key = str(first_index)
        second_key = str(second_index)
        first = buttons.get(first_key)
        second = buttons.get(second_key)
        if first is None and second is None:
            return
        if second is None:
            buttons.pop(first_key, None)
        else:
            buttons[first_key] = second
        if first is None:
            buttons.pop(second_key, None)
        else:
            buttons[second_key] = first

    def ensure_page(self, page_id: str, name: str | None = None) -> None:
        self.pages.setdefault(page_id, {})
        if name:
            self.page_names[page_id] = name
        else:
            self.page_names.setdefault(page_id, page_id)

    def set_current_page(self, page_id: str) -> None:
        self.ensure_page(page_id)
        self.current_page = page_id
        self.buttons = self.pages[page_id]

    def set_layout(self, rows: int, columns: int) -> None:
        self.rows = max(1, rows)
        self.columns = max(1, columns)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Profile":
        profile = cls(
            name=str(data.get("name", "Default")),
            rows=int(data.get("rows", 3)),
            columns=int(data.get("columns", 5)),
            current_page=str(data.get("current_page", "main")),
        )
        raw_buttons = data.get("buttons", {})
        if isinstance(raw_buttons, dict):
            profile.buttons = {
                str(key): ButtonConfig.from_dict(value)
                for key, value in raw_buttons.items()
                if isinstance(value, dict)
            }
        raw_pages = data.get("pages", {})
        if isinstance(raw_pages, dict):
            profile.pages = {
                str(page_id): {
                    str(key): ButtonConfig.from_dict(value)
                    for key, value in buttons.items()
                    if isinstance(value, dict)
                }
                for page_id, buttons in raw_pages.items()
                if isinstance(buttons, dict)
            }
        raw_page_names = data.get("page_names", {})
        if isinstance(raw_page_names, dict):
            profile.page_names = {str(key): str(value) for key, value in raw_page_names.items()}
        if profile.pages:
            if profile.current_page not in profile.pages:
                profile.current_page = next(iter(profile.pages))
            profile.buttons = profile.pages[profile.current_page]
        else:
            profile.pages = {"main": profile.buttons}
            profile.page_names.setdefault("main", profile.name or "Main")
            profile.current_page = "main"
        return profile

    def to_dict(self) -> dict[str, Any]:
        self.page_ids()
        self.buttons = self.current_buttons()
        return {
            "name": self.name,
            "rows": self.rows,
            "columns": self.columns,
            "buttons": {key: asdict(value) for key, value in self.buttons.items()},
            "pages": {
                page_id: {key: asdict(value) for key, value in buttons.items()}
                for page_id, buttons in self.pages.items()
            },
            "page_names": self.page_names,
            "current_page": self.current_page,
        }


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "streamdeck-studio"
    return Path.home() / ".config" / "streamdeck-studio"


def profile_path() -> Path:
    return config_dir() / "profile.json"


def profiles_dir() -> Path:
    return config_dir() / "profiles"


def active_profile_path() -> Path:
    return config_dir() / "active-profile"


def default_profile_path() -> Path:
    return config_dir() / "default-profile"


def profile_library_path(profile_id: str) -> Path:
    return profiles_dir() / f"{_clean_profile_id(profile_id)}.json"


def profile_assets_dir(profile_id: str) -> Path:
    return profiles_dir() / _clean_profile_id(profile_id)


def profile_action_icons_dir(profile_id: str) -> Path:
    return profile_assets_dir(profile_id) / "action-icons"


def profile_id_from_name(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or DEFAULT_PROFILE_ID


def list_profile_ids() -> list[str]:
    ids = {DEFAULT_PROFILE_ID}
    directory = profiles_dir()
    if directory.exists():
        ids.update(path.stem for path in directory.glob("*.json") if path.is_file())
    valid_ids: list[str] = []
    sort_names: dict[str, str] = {}
    for profile_id in ids:
        try:
            sort_names[profile_id] = load_profile_by_id(profile_id).name.lower()
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        valid_ids.append(profile_id)
    return sorted(valid_ids or [DEFAULT_PROFILE_ID], key=lambda profile_id: sort_names.get(profile_id, profile_id))


def profile_name_exists(name: str, exclude_profile_id: str | None = None) -> bool:
    candidate = name.strip().casefold()
    if not candidate:
        return False
    exclude = _clean_profile_id(exclude_profile_id) if exclude_profile_id else ""
    for profile_id in list_profile_ids():
        if profile_id == exclude:
            continue
        try:
            if load_profile_by_id(profile_id).name.strip().casefold() == candidate:
                return True
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return False


def profile_is_saved(profile_id: str) -> bool:
    clean_id = _clean_profile_id(profile_id)
    if profile_library_path(clean_id).exists():
        return True
    return clean_id == DEFAULT_PROFILE_ID and profile_path().exists()


def next_profile_name(base: str = NEW_PROFILE_NAME) -> str:
    existing = set()
    existing_ids = set(list_profile_ids())
    for profile_id in list_profile_ids():
        try:
            existing.add(load_profile_by_id(profile_id).name.strip().casefold())
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    if base.casefold() not in existing and profile_id_from_name(base) not in existing_ids:
        return base
    suffix = 2
    while f"{base} {suffix}".casefold() in existing or profile_id_from_name(f"{base} {suffix}") in existing_ids:
        suffix += 1
    return f"{base} {suffix}"


def load_active_profile() -> tuple[str, Profile]:
    profile_id = DEFAULT_PROFILE_ID
    try:
        saved_id = active_profile_path().read_text(encoding="utf-8").strip()
        if saved_id:
            profile_id = _clean_profile_id(saved_id)
    except OSError:
        pass
    try:
        return profile_id, load_profile_by_id(profile_id)
    except (OSError, json.JSONDecodeError, ValueError):
        if profile_id != DEFAULT_PROFILE_ID:
            return DEFAULT_PROFILE_ID, load_profile_by_id(DEFAULT_PROFILE_ID)
        raise


def save_active_profile_id(profile_id: str) -> None:
    target = active_profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{_clean_profile_id(profile_id)}\n", encoding="utf-8")


def load_default_profile_id() -> str:
    try:
        saved_id = default_profile_path().read_text(encoding="utf-8").strip()
        if saved_id:
            return _clean_profile_id(saved_id)
    except OSError:
        pass
    return DEFAULT_PROFILE_ID


def save_default_profile_id(profile_id: str) -> None:
    target = default_profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"{_clean_profile_id(profile_id)}\n", encoding="utf-8")


def load_profile_by_id(profile_id: str) -> Profile:
    clean_id = _clean_profile_id(profile_id)
    library_path = profile_library_path(clean_id)
    if library_path.exists():
        return load_profile(library_path)
    if clean_id == DEFAULT_PROFILE_ID:
        if not profile_path().exists():
            return create_default_icon_profile(NEW_PROFILE_NAME)
        return load_profile(profile_path())
    raise FileNotFoundError(library_path)


def save_profile_by_id(profile_id: str, profile: Profile) -> None:
    save_profile(profile, profile_library_path(profile_id))
    if _clean_profile_id(profile_id) == DEFAULT_PROFILE_ID:
        save_profile(profile, profile_path())


def create_blank_profile(name: str, rows: int = 3, columns: int = 5) -> Profile:
    profile = Profile(name=name, rows=rows, columns=columns, pages={"main": {}}, page_names={"main": name})
    profile.current_page = "main"
    profile.buttons = profile.pages["main"]
    return profile


def create_default_icon_profile(name: str = NEW_PROFILE_NAME, rows: int = 3, columns: int = 5) -> Profile:
    pages = {page_id: {} for page_id in DEFAULT_PROFILE_PAGES}
    profile = Profile(name=name, rows=rows, columns=columns, pages=pages, page_names=dict(DEFAULT_PROFILE_PAGES))
    icon_paths = _default_icon_paths()
    page_size = rows * columns
    for page_index, page_id in enumerate(DEFAULT_PROFILE_PAGES):
        start = page_index * page_size
        for index, path in enumerate(icon_paths[start : start + page_size]):
            profile.pages[page_id][str(index)] = ButtonConfig(action_image_path=str(path))
    profile.current_page = "main"
    profile.buttons = profile.pages["main"]
    return profile


def delete_profile_by_id(profile_id: str) -> None:
    clean_id = _clean_profile_id(profile_id)
    for path in {profile_library_path(clean_id), profile_assets_dir(clean_id)}:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
    if clean_id == DEFAULT_PROFILE_ID:
        profile_path().unlink(missing_ok=True)
    if load_default_profile_id() == clean_id:
        default_profile_path().unlink(missing_ok=True)
    try:
        if active_profile_path().read_text(encoding="utf-8").strip() == clean_id:
            active_profile_path().unlink(missing_ok=True)
    except OSError:
        pass


def ensure_mcp_profile(rows: int = 3, columns: int = 5) -> Profile:
    try:
        return load_profile_by_id(MCP_PROFILE_ID)
    except (OSError, json.JSONDecodeError, ValueError):
        profile = create_blank_profile(MCP_PROFILE_NAME, rows, columns)
        save_profile_by_id(MCP_PROFILE_ID, profile)
        return profile


def load_profile(path: Path | None = None) -> Profile:
    target = path or profile_path()
    if not target.exists():
        return Profile()
    with target.open("r", encoding="utf-8") as handle:
        return Profile.from_dict(json.load(handle))


def save_profile(profile: Profile, path: Path | None = None) -> None:
    target = path or profile_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(profile.to_dict(), handle, indent=2, sort_keys=True)
        handle.write("\n")


def _clean_profile_id(profile_id: str) -> str:
    clean_id = profile_id_from_name(profile_id) if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", profile_id) else profile_id
    return clean_id or DEFAULT_PROFILE_ID


def _default_icon_paths() -> list[Path]:
    directory = Path(__file__).parent / "resources" / "action-images" / "default"
    paths = [directory / f"{name}.png" for name in DEFAULT_ICON_NAMES]
    return [path for path in paths if path.exists()]
