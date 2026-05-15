from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .model import ButtonConfig


class DeckImageTarget(Protocol):
    def key_image_format(self): ...


def render_button_image(config: ButtonConfig, size: tuple[int, int] = (144, 144), frame_index: int = 0) -> Image.Image:
    if config.image_path and not config.background_image_path and not config.action_image_path:
        path = Path(config.image_path).expanduser()
        if path.exists():
            try:
                image = _image_frame(path, frame_index).convert("RGB")
                return _fit_image(image, size)
            except OSError:
                pass

    width, height = size
    image = _background_image(config, size, frame_index)
    draw = ImageDraw.Draw(image)

    icon_path = config.action_image_path or (config.image_path if config.background_image_path else "")
    title = config.label.strip()
    subtitle = config.subtitle.strip()

    foreground = _valid_color(config.foreground, "#ffffff")
    title_font = _fit_font(title, width - 18, max_size=28, min_size=12, bold=True)
    subtitle_font = _font(13, bold=False)

    if icon_path:
        _draw_action_icon(image, icon_path, size, bool(title or subtitle), frame_index)

    title_lines = _wrap_text(title, title_font, width - 18, max_lines=3) if title else []
    line_heights = [_text_size(line, title_font)[1] for line in title_lines]
    total_title_height = sum(line_heights) + max(0, len(title_lines) - 1) * 4
    subtitle_height = _text_size(subtitle, subtitle_font)[1] if subtitle else 0
    total_height = total_title_height + (12 + subtitle_height if subtitle else 0)
    y = _label_y(config.label_position, height, total_height)

    for line, line_height in zip(title_lines, line_heights):
        _draw_centered_text(draw, line, y, width, title_font, foreground)
        y += line_height + 4

    if subtitle:
        y += 8
        subtitle = _ellipsize(subtitle, subtitle_font, width - 18)
        _draw_centered_text(draw, subtitle, y, width, subtitle_font, "#d1d5db")

    return image


def button_animation_frame_count(config: ButtonConfig) -> int:
    return max((_frame_count(path) for path in _image_paths(config)), default=1)


def button_animation_frame_duration(config: ButtonConfig, frame_index: int) -> float:
    durations = [_frame_duration(path, frame_index) for path in _image_paths(config) if _frame_count(path) > 1]
    return max(0.03, min(durations, default=0.1))


def _background_image(config: ButtonConfig, size: tuple[int, int], frame_index: int) -> Image.Image:
    if config.background_image_path:
        path = Path(config.background_image_path).expanduser()
        if path.exists():
            try:
                image = _image_frame(path, frame_index).convert("RGB")
                image = _cover_image(image, size)
                overlay = Image.new("RGBA", size, (0, 0, 0, 72))
                image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
                return image
            except OSError:
                pass
    return Image.new("RGB", size, _valid_color(config.background, "#1f2937"))


def _draw_action_icon(image: Image.Image, path_value: str, size: tuple[int, int], has_text: bool, frame_index: int) -> int:
    path = Path(path_value).expanduser()
    if not path.exists():
        return 0
    try:
        icon = _image_frame(path, frame_index).convert("RGBA")
    except OSError:
        return 0
    max_size = int(min(size) * (0.82 if has_text else 0.92))
    icon = _contain_image(icon, (max_size, max_size))
    x = (size[0] - icon.width) // 2
    y = (size[1] - icon.height) // 2
    base = image.convert("RGBA")
    base.alpha_composite(icon, (x, y))
    image.paste(base.convert("RGB"))
    return icon.height + 8 if has_text else 0


def _label_y(position: str, height: int, text_height: int) -> int:
    if text_height <= 0:
        return 0
    if position == "top":
        return 10
    if position == "middle":
        return max(0, (height - text_height) // 2)
    return max(0, height - text_height - 12)


def to_streamdeck_native(deck: DeckImageTarget, image: Image.Image) -> bytes:
    from StreamDeck.ImageHelpers import PILHelper

    return PILHelper.to_native_key_format(deck, image)


def _valid_color(value: str, fallback: str) -> str:
    try:
        ImageColor.getrgb(value)
        return value
    except ValueError:
        return fallback


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


def _cover_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    if image_ratio > target_ratio:
        new_height = size[1]
        new_width = round(new_height * image_ratio)
    else:
        new_width = size[0]
        new_height = round(new_width / image_ratio)
    resized = image.resize((new_width, new_height), Image.LANCZOS)
    left = (new_width - size[0]) // 2
    top = (new_height - size[1]) // 2
    return resized.crop((left, top, left + size[0], top + size[1]))


def _contain_image(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image_ratio = image.width / image.height
    target_ratio = size[0] / size[1]
    if image_ratio > target_ratio:
        new_width = size[0]
        new_height = round(new_width / image_ratio)
    else:
        new_height = size[1]
        new_width = round(new_height * image_ratio)
    return image.resize((new_width, new_height), Image.LANCZOS)


def _image_paths(config: ButtonConfig) -> list[str]:
    paths = []
    if config.image_path:
        paths.append(config.image_path)
    if config.background_image_path:
        paths.append(config.background_image_path)
    if config.action_image_path:
        paths.append(config.action_image_path)
    return paths


def _image_frame(path: Path, frame_index: int) -> Image.Image:
    try:
        stat = path.stat()
    except OSError:
        image = Image.open(path)
        count = getattr(image, "n_frames", 1)
        if count > 1:
            image.seek(frame_index % count)
        return image.copy()
    return _cached_image_frame(str(path), stat.st_mtime_ns, stat.st_size, frame_index).copy()


@lru_cache(maxsize=256)
def _cached_image_frame(path_value: str, _mtime_ns: int, _size: int, frame_index: int) -> Image.Image:
    image = Image.open(path_value)
    count = getattr(image, "n_frames", 1)
    if count > 1:
        image.seek(frame_index % count)
    return image.copy()


def _frame_count(path_value: str) -> int:
    path = Path(path_value).expanduser()
    if not path.exists():
        return 1
    try:
        with Image.open(path) as image:
            return max(1, getattr(image, "n_frames", 1))
    except OSError:
        return 1


def _frame_duration(path_value: str, frame_index: int) -> float:
    path = Path(path_value).expanduser()
    if not path.exists():
        return 0.1
    try:
        with Image.open(path) as image:
            count = max(1, getattr(image, "n_frames", 1))
            if count > 1:
                image.seek(frame_index % count)
            duration_ms = int(image.info.get("duration", 100))
    except OSError:
        return 0.1
    return max(30, duration_ms) / 1000
