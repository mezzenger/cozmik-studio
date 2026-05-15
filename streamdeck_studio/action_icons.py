from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import configparser
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .model import config_dir, load_profile, profile_action_icons_dir


@dataclass(frozen=True)
class ActionIcon:
    name: str
    path: Path
    group: str = "Other"


_ICON_SPECS = (
    ("next-page", "Next Page", "NEXT", "#2563eb"),
    ("previous-page", "Previous Page", "PREV", "#2563eb"),
    ("parent-page", "Parent Page", "UP", "#2563eb"),
    ("home", "Home", "HOME", "#0f766e"),
    ("back", "Back", "BACK", "#0f766e"),
    ("forward", "Forward", "FWD", "#0f766e"),
    ("open", "Open", "OPEN", "#d97706"),
    ("folder", "Folder", "DIR", "#d97706"),
    ("file", "File", "FILE", "#d97706"),
    ("link", "Link", "LINK", "#0284c7"),
    ("browser", "Browser", "WEB", "#0284c7"),
    ("terminal", "Terminal", "TERM", "#16a34a"),
    ("command", "Command", "CMD", "#16a34a"),
    ("shell", "Shell", "SH", "#16a34a"),
    ("text", "Text", "TXT", "#7c3aed"),
    ("clipboard", "Clipboard", "CLIP", "#7c3aed"),
    ("paste", "Paste", "PASTE", "#7c3aed"),
    ("keyboard", "Keyboard", "KEYS", "#7c3aed"),
    ("settings", "Settings", "SET", "#475569"),
    ("calculator", "Calculator", "CALC", "#475569"),
    ("mail", "Mail", "MAIL", "#0891b2"),
    ("message", "Message", "MSG", "#0891b2"),
    ("music", "Music", "MUS", "#db2777"),
    ("volume-up", "Volume Up", "VOL+", "#db2777"),
    ("volume-down", "Volume Down", "VOL-", "#db2777"),
    ("mute", "Mute", "MUTE", "#db2777"),
    ("screenshot", "Screenshot", "SHOT", "#9333ea"),
    ("record", "Record", "REC", "#dc2626"),
    ("emoji", "Emoji", "EMO", "#eab308"),
    ("play", "Play", "PLAY", "#22c55e"),
    ("pause", "Pause", "PAUSE", "#22c55e"),
    ("stop", "Stop", "STOP", "#ef4444"),
    ("search", "Search", "FIND", "#64748b"),
    ("save", "Save", "SAVE", "#64748b"),
    ("trash", "Trash", "DEL", "#ef4444"),
    ("plus", "Add", "ADD", "#22c55e"),
    ("minus", "Remove", "SUB", "#ef4444"),
    ("star", "Star", "STAR", "#eab308"),
    ("heart", "Heart", "LOVE", "#e11d48"),
    ("lock", "Lock", "LOCK", "#475569"),
    ("key", "Key", "KEY", "#475569"),
    ("info", "Info", "INFO", "#0284c7"),
    ("warning", "Warning", "WARN", "#eab308"),
)


def action_icons(profile_id: str | None = None) -> list[ActionIcon]:
    root = config_dir() / "action-icons"
    _ensure_builtin_icons(root / "built-in")
    _ensure_main_page_icons(root / "main")
    _ensure_app_icons(root / "apps")
    icons = [*_collect_resource_icons(), *_collect_icons(root)]
    if profile_id:
        icons.extend(_collect_user_installed_icons(profile_action_icons_dir(profile_id)))
    return icons


def _ensure_builtin_icons(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    existing = {path.stem for path in directory.glob("*.png")}
    expected = {slug for slug, _name, _text, _color in _ICON_SPECS}
    if existing == expected:
        return
    icons = []
    for slug, name, text, color in _ICON_SPECS:
        path = directory / f"{slug}.png"
        if not path.exists():
            _draw_icon(path, text, color)
        icons.append(ActionIcon(name=name, path=path))


def _ensure_main_page_icons(directory: Path) -> None:
    try:
        profile = load_profile()
    except (OSError, ValueError):
        return
    main_page = next((page_id for page_id, name in profile.page_names.items() if name.upper() == "MAIN"), profile.current_page)
    buttons = profile.pages.get(main_page, {})
    directory.mkdir(parents=True, exist_ok=True)
    for raw_index, button in buttons.items():
        source = Path(button.action_image_path or button.image_path or "").expanduser()
        if not source.exists() or not source.is_file():
            continue
        index = int(raw_index) + 1 if raw_index.isdigit() else 0
        name = _safe_name(f"main-{index:02d}-{button.label or source.stem}")
        _copy_icon_image(source, directory / f"{name}.png")


def _ensure_app_icons(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for desktop_file in _desktop_files():
        desktop = _read_desktop_file(desktop_file)
        name = desktop.get("Name", "").strip()
        icon_name = desktop.get("Icon", "").strip()
        if not name or not icon_name:
            continue
        source = _resolve_icon(icon_name)
        if not source:
            continue
        target = directory / f"{_safe_name(name)}.png"
        if target.exists():
            continue
        _copy_icon_image(source, target)


def _collect_icons(root: Path) -> list[ActionIcon]:
    icons: list[ActionIcon] = []
    groups = {
        "built-in": "Simple",
        "apps": "Installed Apps",
    }
    for directory in (root / "built-in", root / "apps"):
        if not directory.exists():
            continue
        for path in _image_files(directory):
            icons.append(ActionIcon(name=_display_name(path.stem), path=path, group=groups.get(directory.name, "Other")))
    return icons


def _collect_resource_icons() -> list[ActionIcon]:
    directory = Path(__file__).parent / "resources" / "action-images"
    if not directory.exists():
        return []
    icons: list[ActionIcon] = []
    default_directory = directory / "default"
    if default_directory.exists():
        icons.extend(ActionIcon(name=_display_name(path.stem), path=path, group="Default") for path in _image_files(default_directory))
    icons.extend(ActionIcon(name=_display_name(path.stem), path=path, group="Elgato") for path in _image_files(directory))
    for child in sorted(path for path in directory.iterdir() if path.is_dir() and path.name != "default"):
        icons.extend(_resource_child_icons(child))
    return icons


def _resource_child_icons(directory: Path) -> list[ActionIcon]:
    if directory.name == "obs_studio":
        app_name = _display_name(directory.name)
        return [
            ActionIcon(name=f"{app_name} {_display_name(path.stem)}", path=path, group=_obs_studio_icon_group(path))
            for path in _image_files(directory, recursive=True)
        ]
    prefix = _display_name(directory.name)
    group = re.sub(r"^Set \d+ ", "", prefix)
    return [
        ActionIcon(name=f"{prefix} {_display_name(path.stem)}", path=path, group=_resource_icon_group(path, group))
        for path in _image_files(directory, recursive=True)
    ]


def _obs_studio_icon_group(path: Path) -> str:
    group = _display_name(path.stem)
    if group in {"Metallic", "Minimal"}:
        return "Installed Apps"
    return group


def _resource_icon_group(path: Path, design_group: str) -> str:
    if path.parent.name == "stream_deck_core":
        return "Elgato"
    return design_group


def _collect_user_installed_icons(directory: Path) -> list[ActionIcon]:
    if not directory.exists():
        return []
    return [
        ActionIcon(name=_display_name(path.stem), path=path, group="User Installed")
        for path in _image_files(directory)
    ]


def _image_files(directory: Path, recursive: bool = False) -> list[Path]:
    paths = directory.rglob("*") if recursive else directory.iterdir()
    return sorted(
        path
        for path in paths
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}
    )


def _draw_icon(path: Path, text: str, color: str) -> None:
    size = 96
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((6, 6, size - 6, size - 6), radius=20, fill=color)
    draw.rounded_rectangle((11, 11, size - 11, size - 11), radius=16, outline=(255, 255, 255, 90), width=2)
    font = _font(24 if len(text) <= 4 else 20)
    box = draw.textbbox((0, 0), text, font=font)
    x = (size - (box[2] - box[0])) // 2 - box[0]
    y = (size - (box[3] - box[1])) // 2 - box[1]
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    image.save(path)


def _desktop_files() -> list[Path]:
    roots = [
        Path.home() / ".local/share/applications",
        Path("/usr/local/share/applications"),
        Path("/usr/share/applications"),
    ]
    files: list[Path] = []
    for root in roots:
        if root.exists():
            files.extend(sorted(root.glob("*.desktop")))
    return files


@lru_cache(maxsize=512)
def _read_desktop_file(path: Path) -> dict[str, str]:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except configparser.Error:
        return {}
    if not parser.has_section("Desktop Entry"):
        return {}
    entry = parser["Desktop Entry"]
    if entry.get("NoDisplay", "").lower() == "true" or entry.get("Hidden", "").lower() == "true":
        return {}
    return {"Name": entry.get("Name", ""), "Icon": entry.get("Icon", "")}


def _resolve_icon(icon_name: str) -> Path | None:
    candidate = Path(icon_name).expanduser()
    if candidate.is_absolute() and candidate.exists() and candidate.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return candidate
    if candidate.is_absolute():
        return None
    names = [icon_name]
    if not Path(icon_name).suffix:
        names.extend(f"{icon_name}{suffix}" for suffix in (".png", ".jpg", ".jpeg"))
    icon_index = _icon_index()
    matches: list[Path] = []
    for name in names:
        matches.extend(icon_index.get(name, []))
    matches = [path for path in matches if path.suffix.lower() in {".png", ".jpg", ".jpeg"}]
    return _best_icon_match(matches)


def _icon_roots() -> list[Path]:
    return [
        Path.home() / ".local/share/icons",
        Path.home() / ".icons",
        Path("/usr/local/share/icons"),
        Path("/usr/share/icons"),
        Path("/usr/share/pixmaps"),
    ]


@lru_cache(maxsize=1)
def _icon_index() -> dict[str, list[Path]]:
    index: dict[str, list[Path]] = {}
    for root in _icon_roots():
        if not root.exists():
            continue
        try:
            paths = root.rglob("*")
            for path in paths:
                if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
                    continue
                index.setdefault(path.name, []).append(path)
        except OSError:
            continue
    return index


def _best_icon_match(matches: list[Path]) -> Path | None:
    best: tuple[int, Path] | None = None
    for path in matches:
        try:
            with Image.open(path) as image:
                size = min(image.size)
        except OSError:
            continue
        score = abs(size - 96)
        if best is None or score < best[0]:
            best = (score, path)
    return best[1] if best else None


def _copy_icon_image(source: Path, target: Path) -> None:
    if target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with Image.open(source) as image:
            image.convert("RGBA").save(target)
    except OSError:
        try:
            shutil.copy2(source, target)
        except OSError:
            pass


def _safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "icon"


def _display_name(value: str) -> str:
    value = re.sub(r"^main-\d+-", "", value)
    return value.replace("-", " ").replace("_", " ").title()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()
