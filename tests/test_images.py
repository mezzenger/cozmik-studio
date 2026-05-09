from PIL import Image

from streamdeck_studio.images import button_animation_frame_count, button_animation_frame_duration, render_button_image
from streamdeck_studio.model import ButtonConfig


def test_render_button_image_size():
    image = render_button_image(ButtonConfig(label="Terminal", action_type="command"), (144, 144))
    assert image.size == (144, 144)


def test_render_button_has_no_top_action_bar():
    image = render_button_image(ButtonConfig(background="#123456"), (144, 144))
    assert image.getpixel((4, 4)) == (18, 52, 86)


def test_render_button_uses_background_and_action_images(tmp_path):
    background_path = tmp_path / "background.png"
    action_path = tmp_path / "action.png"
    render_button_image(ButtonConfig(background="#ff0000"), (144, 144)).save(background_path)
    render_button_image(ButtonConfig(background="#00ff00"), (144, 144)).resize((48, 48)).save(action_path)

    image = render_button_image(
        ButtonConfig(
            label="Launch",
            action_type="command",
            background_image_path=str(background_path),
            action_image_path=str(action_path),
        ),
        (144, 144),
    )

    assert image.size == (144, 144)
    assert image.getpixel((72, 36)) != image.getpixel((8, 136))


def test_render_button_uses_animated_gif_frames(tmp_path):
    gif_path = tmp_path / "action.gif"
    frames = [
        Image.new("RGB", (48, 48), "#ff0000"),
        Image.new("RGB", (48, 48), "#00ff00"),
    ]
    frames[0].save(gif_path, save_all=True, append_images=[frames[1]], duration=[80, 120], loop=0)
    config = ButtonConfig(action_image_path=str(gif_path), background="#000000")

    first = render_button_image(config, (144, 144), frame_index=0)
    second = render_button_image(config, (144, 144), frame_index=1)

    assert button_animation_frame_count(config) == 2
    assert button_animation_frame_duration(config, 0) == 0.08
    assert button_animation_frame_duration(config, 1) == 0.12
    assert first.getpixel((72, 36)) != second.getpixel((72, 36))


def test_blank_subtitle_stays_blank(monkeypatch):
    drawn = []

    def record_text(_draw, text, _y, _width, _font, _fill):
        drawn.append(text)

    monkeypatch.setattr("streamdeck_studio.images._draw_centered_text", record_text)

    render_button_image(ButtonConfig(label="Docs", action_type="url", subtitle=""), (144, 144))

    assert drawn == ["Docs"]
