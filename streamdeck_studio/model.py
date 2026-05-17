from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


ACTION_TYPES = ("none", "command", "shell", "url", "file", "text", "page", "media", "shortcut", "keys", "tutorial")
LABEL_POSITIONS = ("top", "middle", "bottom")
DEFAULT_PROFILE_ID = "default"
NEW_PROFILE_NAME = "New Profile"
MCP_PROFILE_ID = "mcp-deck"
MCP_PROFILE_NAME = "MCP Deck"
DEFAULT_PROFILE_PAGES = {"main": "Main", "tutorials": "Tutorials"}
TUTORIAL_TARGET_PREFIX = "cozmik-tutorial:"
SUPER_SHORTCUT_TARGET = "super"
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

TUTORIAL_TOPICS = (
    {
        "label": "Start Here",
        "subtitle": "TOUR",
        "icon": "start-here.png",
        "background": "#123c69",
        "slides": [
            {
                "title": "Start with a profile",
                "body": "Cozmik Studio stores complete button layouts as profiles. Use the Profile selector in the toolbar to switch between saved layouts before editing buttons.",
            },
            {
                "title": "Edit one button at a time",
                "body": "Select a key in the grid, set its label, subtitle, action, target, colors, and images, then use Run or the physical Stream Deck to test it.",
            },
            {
                "title": "Save applies to hardware",
                "body": "Most edits autosave. The Save button is still useful as an explicit apply step when a physical deck is connected.",
            },
        ],
    },
    {
        "label": "Profiles",
        "subtitle": "LAYOUTS",
        "icon": "profiles.png",
        "background": "#0f766e",
        "slides": [
            {
                "title": "Profiles are separate decks",
                "body": "A profile contains pages, buttons, labels, images, colors, and actions. Use separate profiles for work, streaming, experiments, or a blank MCP Deck.",
            },
            {
                "title": "Renaming and defaults",
                "body": "Right-click the profile selector to rename a placeholder profile. Use the star button to make the current profile the default at startup.",
            },
            {
                "title": "Connected deck layouts",
                "body": "When hardware is connected, Cozmik matches the active profile to the physical row and column layout so every key has a usable slot.",
            },
        ],
    },
    {
        "label": "Pages",
        "subtitle": "NAV",
        "icon": "pages.png",
        "background": "#1d4ed8",
        "slides": [
            {
                "title": "Pages act like folders",
                "body": "A page is another set of buttons inside the same profile. Page buttons let you jump between topic-specific layouts without changing profiles.",
            },
            {
                "title": "Create navigation first",
                "body": "Build navigation buttons before filling every page. A clear home, previous, next, or parent path keeps large decks usable.",
            },
            {
                "title": "Use the page selector",
                "body": "The Page selector lets you edit any page directly. Selecting a page from the toolbar does not require pressing a hardware key.",
            },
        ],
    },
    {
        "label": "Buttons",
        "subtitle": "EDITOR",
        "icon": "buttons.png",
        "background": "#4f46e5",
        "slides": [
            {
                "title": "Readable beats crowded",
                "body": "Use short labels and subtitles. Put the most important word in the label, then use subtitle text for context such as APP, WEB, or KEYS.",
            },
            {
                "title": "Drag to rearrange",
                "body": "Drag a button onto another slot to swap or move configurations. Cozmik refreshes both previews and reapplies the profile.",
            },
            {
                "title": "Clear without deleting pages",
                "body": "Clear removes only the selected button configuration. Pages and other buttons remain intact.",
            },
        ],
    },
    {
        "label": "Actions",
        "subtitle": "RUN",
        "icon": "actions.png",
        "background": "#7c2d12",
        "slides": [
            {
                "title": "Choose the action type first",
                "body": "Action type controls how the Target field is interpreted. URLs open in a browser, files use desktop openers, commands start processes, and text copies or pastes content.",
            },
            {
                "title": "Run before relying on it",
                "body": "Use the Run button in the editor to test the selected action. This catches missing commands, bad paths, and unsupported helpers before you need the deck.",
            },
            {
                "title": "Shell is intentionally different",
                "body": "Use command for normal executable arguments. Use shell only when you need pipes, redirects, variables, or other shell expansion.",
            },
        ],
    },
    {
        "label": "Text Paste",
        "subtitle": "CLIP",
        "icon": "text-paste.png",
        "background": "#be123c",
        "slides": [
            {
                "title": "Text actions split press and release",
                "body": "On hardware, pressing a text key copies the configured text. Releasing it attempts to paste into the focused app.",
            },
            {
                "title": "Wayland needs a helper",
                "body": "On GNOME and other Wayland sessions, paste usually needs ydotool, wtype, or xdotool. Start ydotoold if ydotool is installed but paste does not work.",
            },
            {
                "title": "Sensitive text stays local",
                "body": "Text targets can contain private snippets. Review exported profiles before sharing because exports include button targets.",
            },
        ],
    },
    {
        "label": "Key Presses",
        "subtitle": "KEYS",
        "icon": "key-presses.png",
        "background": "#6d28d9",
        "slides": [
            {
                "title": "Shortcuts are chords",
                "body": "Use shortcut for a single chord such as ctrl+alt+t. It presses and releases the whole combination as one action.",
            },
            {
                "title": "Keys can be scripted",
                "body": "Use keys for multi-step sequences such as alt+delay+F4,f. Commas separate taps; delay pauses between steps.",
            },
            {
                "title": "Fallback helpers",
                "body": "Cozmik tries ydotool first for key scripts. If ydotool is installed but unusable, it falls back to xdotool when available.",
            },
        ],
    },
    {
        "label": "Images",
        "subtitle": "STYLE",
        "icon": "images.png",
        "background": "#b45309",
        "slides": [
            {
                "title": "Use action images for symbols",
                "body": "Action images sit over the button background and are best for app icons, arrows, media symbols, and topic markers.",
            },
            {
                "title": "Use background images sparingly",
                "body": "Background images fill the entire key. Cozmik adds a dark overlay so labels remain readable.",
            },
            {
                "title": "Bundled galleries are portable",
                "body": "Bundled icons travel with the app. User-installed icons are copied into your local profile assets and should be reviewed before sharing.",
            },
        ],
    },
    {
        "label": "Import",
        "subtitle": "MAC",
        "icon": "import.png",
        "background": "#0369a1",
        "slides": [
            {
                "title": "Import Elgato exports",
                "body": "Use Import for .streamDeckProfile files or .StreamDeckProfilesBackup archives exported from the macOS Stream Deck app.",
            },
            {
                "title": "Expect best-effort mapping",
                "body": "Cozmik maps common URL, file, text, hotkey, media, and navigation actions. Plugin-specific actions may need manual cleanup.",
            },
            {
                "title": "Read diagnostics",
                "body": "The diagnostics panel summarizes unsupported buttons, missing page links, and translated launchers so you know what to repair.",
            },
        ],
    },
    {
        "label": "Hardware",
        "subtitle": "DECK",
        "icon": "hardware.png",
        "background": "#334155",
        "slides": [
            {
                "title": "Device access uses HID",
                "body": "If Cozmik cannot open the Stream Deck, install the udev rule from packaging/udev and reconnect the device.",
            },
            {
                "title": "Offline editing is normal",
                "body": "The app works without hardware connected. You can build profiles offline and apply them later when a deck is available.",
            },
            {
                "title": "Animations refresh on deck",
                "body": "Animated GIF buttons are rendered frame by frame and applied to connected hardware while the profile is active.",
            },
        ],
    },
    {
        "label": "MCP Deck",
        "subtitle": "AGENTS",
        "icon": "mcp-deck.png",
        "background": "#0e7490",
        "slides": [
            {
                "title": "MCP Deck is a separate profile",
                "body": "Press MCP to create and switch to a blank MCP Deck profile. Configure buttons there specifically for local agent workflows.",
            },
            {
                "title": "Agents get tools, not secrets",
                "body": "The MCP server exposes get_profile, list_buttons, and activate_button. Text targets are redacted from list output, but activated buttons still run locally.",
            },
            {
                "title": "Smoke-test the server",
                "body": "Run cozmik-studio-mcp through an MCP client, or send a tools/list JSON-RPC frame to verify it returns the tool definitions.",
            },
        ],
    },
    {
        "label": "Privacy",
        "subtitle": "LOCAL",
        "icon": "privacy.png",
        "background": "#475569",
        "slides": [
            {
                "title": "Profiles are local runtime data",
                "body": "Saved profiles live under ~/.config/streamdeck-studio. They are not part of the source repository unless you intentionally copy or export them.",
            },
            {
                "title": "Targets can be sensitive",
                "body": "Targets may contain private URLs, file paths, commands, snippets, or workflow details. Sanitize exported profiles before sharing.",
            },
            {
                "title": "Use separate profiles",
                "body": "Keep public demos, daily work, and experiments in separate profiles so you can share one without exposing another.",
            },
        ],
    },
    {
        "label": "Backups",
        "subtitle": "SAFE",
        "icon": "backups.png",
        "background": "#15803d",
        "slides": [
            {
                "title": "Back up before big imports",
                "body": "Before importing large profile archives, back up ~/.config/streamdeck-studio or export the current profile.",
            },
            {
                "title": "Keep backups outside git",
                "body": "Backups often contain personal profile data. Store them outside the source tree or in ignored locations.",
            },
            {
                "title": "Test restores",
                "body": "A backup is only useful if it restores. Keep one small known-good profile export for sanity checks.",
            },
        ],
    },
    {
        "label": "Fix Issues",
        "subtitle": "DEBUG",
        "icon": "fix-issues.png",
        "background": "#991b1b",
        "slides": [
            {
                "title": "Use diagnostics first",
                "body": "Open Diagnostics to inspect the selected button, current page, device state, last hardware event, and last action result.",
            },
            {
                "title": "Check helpers",
                "body": "If paste, shortcuts, or key scripts fail, verify ydotool, wtype, or xdotool is installed and usable in your session.",
            },
            {
                "title": "Check paths and permissions",
                "body": "Failed file and command actions usually come down to missing files, non-executable commands, or device permission issues.",
            },
        ],
    },
    {
        "label": "Workflow",
        "subtitle": "PLAN",
        "icon": "workflow.png",
        "background": "#4338ca",
        "slides": [
            {
                "title": "Start with structure",
                "body": "Create pages by topic first: apps, media, links, snippets, system actions, or agent actions. Then add navigation.",
            },
            {
                "title": "Make buttons scannable",
                "body": "Use consistent colors, short labels, and recognizable icons. Similar actions should look related but not identical.",
            },
            {
                "title": "Iterate on the deck",
                "body": "Use the physical deck for a day, then move frequent actions toward the first page and demote rarely used buttons.",
            },
        ],
    },
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
    screensaver_gif_path: str = ""
    screensaver_idle_seconds: int = 0
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
            screensaver_gif_path=str(data.get("screensaver_gif_path", "")),
            screensaver_idle_seconds=max(0, int(data.get("screensaver_idle_seconds", 0) or 0)),
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
            "screensaver_gif_path": self.screensaver_gif_path,
            "screensaver_idle_seconds": self.screensaver_idle_seconds,
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
    _configure_default_main_page(profile)
    _configure_tutorial_page(profile)
    _configure_shared_access_buttons(profile)
    profile.current_page = "main"
    profile.buttons = profile.pages["main"]
    return profile


def _configure_default_main_page(profile: Profile) -> None:
    tutorials_icon = _tutorial_icon_path("start-here.png")
    if 5 < profile.button_count():
        profile.set_button(
            5,
            ButtonConfig(
                label="Tutorials",
                subtitle="GUIDE",
                action_type="page",
                target="tutorials",
                background="#123c69",
                foreground="#ffffff",
                action_image_path=str(tutorials_icon),
                label_position="bottom",
            ),
            page_id="main",
        )


def _configure_tutorial_page(profile: Profile) -> None:
    button_count = profile.button_count()
    topic_count = max(0, button_count - 1)
    for index, topic in enumerate(TUTORIAL_TOPICS[:topic_count]):
        profile.set_button(
            index,
            ButtonConfig(
                label=str(topic["label"]),
                subtitle=str(topic["subtitle"]),
                action_type="tutorial",
                target=_tutorial_target(topic["slides"]),
                background=str(topic["background"]),
                foreground="#ffffff",
                action_image_path=str(_tutorial_icon_path(str(topic["icon"]))),
                label_position="bottom",
            ),
            page_id="tutorials",
        )
    if button_count:
        _set_tutorial_home_button(profile)


def ensure_shared_access_buttons(profile: Profile) -> bool:
    changed = False
    tutorial_page = _tutorial_page_id(profile)
    if not tutorial_page:
        tutorial_page = "tutorials"
        profile.ensure_page(tutorial_page, "Tutorials")
        _configure_tutorial_page(profile)
        changed = True

    for page_id, buttons in profile.pages.items():
        if page_id == tutorial_page:
            continue
        changed = _fix_tutorial_targets(buttons, tutorial_page) or changed
        if not _page_has_super_button(buttons):
            changed = _place_access_button(profile, page_id, profile.button_count() - 2, _super_button_config()) or changed
        if not _page_has_tutorials_button(buttons, tutorial_page):
            changed = (
                _place_access_button(profile, page_id, profile.button_count() - 1, _tutorials_button_config(tutorial_page))
                or changed
            )
    if profile.current_page in profile.pages:
        profile.buttons = profile.pages[profile.current_page]
    return changed


def _configure_shared_access_buttons(profile: Profile) -> None:
    tutorial_page = _tutorial_page_id(profile) or "tutorials"
    for page_id in list(profile.pages):
        if page_id == tutorial_page:
            continue
        if profile.button_count() >= 2:
            profile.set_button(profile.button_count() - 2, _super_button_config(), page_id)
            profile.set_button(profile.button_count() - 1, _tutorials_button_config(tutorial_page), page_id)


def _tutorial_page_id(profile: Profile) -> str:
    if "tutorials" in profile.pages:
        return "tutorials"
    for page_id, name in profile.page_names.items():
        if name.strip().casefold() == "tutorials" and page_id in profile.pages:
            return page_id
    return ""


def _fix_tutorial_targets(buttons: dict[str, ButtonConfig], tutorial_page: str) -> bool:
    changed = False
    for button in buttons.values():
        if button.action_type == "page" and button.target.strip().casefold() == "tutorials" and button.target != tutorial_page:
            button.target = tutorial_page
            changed = True
    return changed


def _page_has_super_button(buttons: dict[str, ButtonConfig]) -> bool:
    return any(
        button.action_type in {"shortcut", "keys", "command"}
        and button.target.strip().casefold() in {SUPER_SHORTCUT_TARGET, "ydotool key 125:1 125:0"}
        for button in buttons.values()
    )


def _page_has_tutorials_button(buttons: dict[str, ButtonConfig], tutorial_page: str) -> bool:
    return any(button.action_type == "page" and button.target == tutorial_page for button in buttons.values())


def _place_access_button(profile: Profile, page_id: str, preferred_index: int, config: ButtonConfig) -> bool:
    if preferred_index < 0:
        return False
    for index in [preferred_index, *range(profile.button_count() - 1, -1, -1)]:
        button = profile.get_button(index, page_id)
        if _button_is_empty(button):
            profile.set_button(index, config, page_id)
            return True
    return False


def _button_is_empty(button: ButtonConfig) -> bool:
    return not any((button.label, button.subtitle, button.target, button.image_path, button.background_image_path, button.action_image_path)) and button.action_type == "none"


def _super_button_config() -> ButtonConfig:
    return ButtonConfig(
        label="Super",
        subtitle="KEY",
        action_type="shortcut",
        target=SUPER_SHORTCUT_TARGET,
        background="#1f2937",
        foreground="#ffffff",
        action_image_path=str(_resource_action_icon_path("default", "apps.png")),
        label_position="bottom",
    )


def _tutorials_button_config(tutorial_page: str) -> ButtonConfig:
    return ButtonConfig(
        label="Tutorials",
        subtitle="GUIDE",
        action_type="page",
        target=tutorial_page,
        background="#123c69",
        foreground="#ffffff",
        action_image_path=str(_tutorial_icon_path("start-here.png")),
        label_position="bottom",
    )


def ensure_tutorial_home_button(profile: Profile) -> bool:
    if "tutorials" not in profile.pages or "main" not in profile.pages:
        return False
    index = profile.button_count() - 1
    if index < 0:
        return False
    current = profile.get_button(index, "tutorials")
    if current.action_type == "page" and current.target == "main":
        return False
    _set_tutorial_home_button(profile)
    return True


def _set_tutorial_home_button(profile: Profile) -> None:
    profile.set_button(
        profile.button_count() - 1,
        ButtonConfig(
            label="Home",
            subtitle="MAIN",
            action_type="page",
            target="main",
            background="#123c69",
            foreground="#ffffff",
            action_image_path=str(_resource_action_icon_path("default", "home.png")),
            label_position="bottom",
        ),
        page_id="tutorials",
    )


def _tutorial_target(slides: Any) -> str:
    return TUTORIAL_TARGET_PREFIX + json.dumps(slides, separators=(",", ":"), ensure_ascii=True)


def _tutorial_icon_path(name: str) -> Path:
    return Path(__file__).parent / "resources" / "action-images" / "tutorials" / name


def _resource_action_icon_path(group: str, name: str) -> Path:
    return Path(__file__).parent / "resources" / "action-images" / group / name


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
