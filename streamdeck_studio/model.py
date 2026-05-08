from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any


ACTION_TYPES = ("none", "command", "shell", "url", "file", "text", "page", "media", "shortcut")


@dataclass
class ButtonConfig:
    label: str = ""
    action_type: str = "none"
    target: str = ""
    subtitle: str = ""
    background: str = "#1f2937"
    foreground: str = "#ffffff"
    image_path: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ButtonConfig":
        action_type = data.get("action_type", "none")
        if action_type not in ACTION_TYPES:
            action_type = "none"
        return cls(
            label=str(data.get("label", "")),
            action_type=action_type,
            target=str(data.get("target", "")),
            subtitle=str(data.get("subtitle", "")),
            background=str(data.get("background", "#1f2937")),
            foreground=str(data.get("foreground", "#ffffff")),
            image_path=str(data.get("image_path", "")),
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
