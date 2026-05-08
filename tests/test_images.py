from streamdeck_studio.images import render_button_image
from streamdeck_studio.model import ButtonConfig


def test_render_button_image_size():
    image = render_button_image(ButtonConfig(label="Terminal", action_type="command"), (144, 144))
    assert image.size == (144, 144)
