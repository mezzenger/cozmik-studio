from streamdeck_studio.images import render_button_image
from streamdeck_studio.model import ButtonConfig


def test_render_button_image_size():
    image = render_button_image(ButtonConfig(label="Terminal", action_type="command"), (144, 144))
    assert image.size == (144, 144)


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
