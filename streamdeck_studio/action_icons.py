from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .model import config_dir


@dataclass(frozen=True)
class ActionIcon:
    name: str
    path: Path


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


def action_icons() -> list[ActionIcon]:
    directory = config_dir() / "action-icons"
    directory.mkdir(parents=True, exist_ok=True)
    icons = []
    for slug, name, text, color in _ICON_SPECS:
        path = directory / f"{slug}.png"
        if not path.exists():
            _draw_icon(path, text, color)
        icons.append(ActionIcon(name=name, path=path))
    return icons


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


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()
