from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .model import ButtonConfig


class DeckImageTarget(Protocol):
    def key_image_format(self): ...


def render_button_image(config: ButtonConfig, size: tuple[int, int] = (144, 144)) -> Image.Image:
    if config.image_path:
        path = Path(config.image_path).expanduser()
        if path.exists():
            try:
                image = Image.open(path).convert("RGB")
                return _fit_image(image, size)
            except OSError:
                pass

    image = Image.new("RGB", size, _valid_color(config.background, "#1f2937"))
    draw = ImageDraw.Draw(image)
    width, height = size

    accent = _valid_color(_accent_for_action(config.action_type), "#14b8a6")
    draw.rectangle((0, 0, width, 8), fill=accent)

    title = config.label.strip() or _default_label(config.action_type)
    subtitle = config.subtitle.strip()
    if not subtitle and config.action_type != "none":
        subtitle = config.action_type.upper()

    foreground = _valid_color(config.foreground, "#ffffff")
    title_font = _fit_font(title, width - 18, max_size=28, min_size=12, bold=True)
    subtitle_font = _font(13, bold=False)

    title_lines = _wrap_text(title, title_font, width - 18, max_lines=3)
    line_heights = [_text_size(line, title_font)[1] for line in title_lines]
    total_title_height = sum(line_heights) + max(0, len(title_lines) - 1) * 4
    subtitle_height = _text_size(subtitle, subtitle_font)[1] if subtitle else 0
    total_height = total_title_height + (12 + subtitle_height if subtitle else 0)
    y = max(18, (height - total_height) // 2)

    for line, line_height in zip(title_lines, line_heights):
        _draw_centered_text(draw, line, y, width, title_font, foreground)
        y += line_height + 4

    if subtitle:
        y += 8
        subtitle = _ellipsize(subtitle, subtitle_font, width - 18)
        _draw_centered_text(draw, subtitle, y, width, subtitle_font, "#d1d5db")

    return image


def to_streamdeck_native(deck: DeckImageTarget, image: Image.Image) -> bytes:
    from StreamDeck.ImageHelpers import PILHelper

    return PILHelper.to_native_key_format(deck, image)


def _valid_color(value: str, fallback: str) -> str:
    try:
        ImageColor.getrgb(value)
        return value
    except ValueError:
        return fallback


def _accent_for_action(action_type: str) -> str:
    return {
        "none": "#64748b",
        "command": "#22c55e",
        "shell": "#10b981",
        "url": "#38bdf8",
        "file": "#f59e0b",
        "text": "#a78bfa",
        "page": "#64748b",
    }.get(action_type, "#14b8a6")


def _default_label(action_type: str) -> str:
    return {
        "none": "Empty",
        "command": "Command",
        "shell": "Shell",
        "url": "Website",
        "file": "Open",
        "text": "Text",
        "page": "Page",
    }.get(action_type, "Button")


@lru_cache(maxsize=64)
def _font(size: int, bold: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _fit_font(text: str, max_width: int, max_size: int, min_size: int, bold: bool) -> ImageFont.ImageFont:
    for size in range(max_size, min_size - 1, -1):
        font = _font(size, bold)
        if all(_text_size(part, font)[0] <= max_width for part in text.split()):
            return font
    return _font(min_size, bold)


def _wrap_text(text: str, font: ImageFont.ImageFont, max_width: int, max_lines: int) -> list[str]:
    words = text.split() or [text]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if _text_size(candidate, font)[0] <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if lines:
        lines[-1] = _ellipsize(lines[-1], font, max_width)
    return lines[:max_lines]


def _ellipsize(text: str, font: ImageFont.ImageFont, max_width: int) -> str:
    if _text_size(text, font)[0] <= max_width:
        return text
    suffix = "..."
    for length in range(len(text), 0, -1):
        candidate = text[:length].rstrip() + suffix
        if _text_size(candidate, font)[0] <= max_width:
            return candidate
    return suffix


def _text_size(text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = font.getbbox(text)
    return box[2] - box[0], box[3] - box[1]


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    width: int,
    font: ImageFont.ImageFont,
    fill: str,
) -> None:
    box = font.getbbox(text)
    text_width = box[2] - box[0]
    x = (width - text_width) // 2 - box[0]
    draw.text((x, y - box[1]), text, font=font, fill=fill)


def _fit_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    output = Image.new("RGB", size, "black")
    thumbnail = image.copy()
    thumbnail.thumbnail(size, Image.LANCZOS)
    x = (size[0] - thumbnail.width) // 2
    y = (size[1] - thumbnail.height) // 2
    output.paste(thumbnail, (x, y))
    return output
