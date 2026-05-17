from PIL import Image

from streamdeck_studio.deck import SCREENSAVER_MIN_FRAME_SECONDS, DeckInfo, StreamDeckController
from streamdeck_studio.model import ButtonConfig, Profile


class FakeDeck:
    def __init__(self) -> None:
        self.images: list[tuple[int, bytes]] = []

    def key_image_format(self):
        return {"size": (24, 24)}

    def set_key_image(self, index: int, image: bytes) -> None:
        self.images.append((index, image))


def test_screensaver_starts_after_idle_and_wakes_to_profile(tmp_path, monkeypatch):
    gif_path = tmp_path / "idle.gif"
    frames = [Image.new("RGB", (24, 24), "red"), Image.new("RGB", (24, 24), "blue")]
    frames[0].save(gif_path, save_all=True, append_images=[frames[1]], duration=[80, 80], loop=0)

    profile = Profile(rows=1, columns=2, screensaver_gif_path=str(gif_path), screensaver_idle_seconds=5)
    profile.set_button(0, ButtonConfig(label="One"))
    profile.set_button(1, ButtonConfig(label="Two"))

    controller = StreamDeckController()
    controller._animation_stop.set()
    controller._deck = FakeDeck()
    controller.info = DeckInfo(connected=True, key_count=2)
    controller._profile = profile
    controller._last_activity = 10.0
    monkeypatch.setattr("streamdeck_studio.deck.to_streamdeck_native", lambda _deck, image: image.tobytes())

    assert controller._should_start_screensaver(15.0)

    controller._start_screensaver(15.0)

    assert controller._screensaver_active is True
    assert [index for index, _image in controller._deck.images[-2:]] == [0, 1]

    controller._record_activity()

    assert controller._screensaver_active is False
    assert [index for index, _image in controller._deck.images[-2:]] == [0, 1]


def test_screensaver_frame_duration_is_capped_for_device_writes(tmp_path):
    gif_path = tmp_path / "fast.gif"
    frames = [Image.new("RGB", (24, 24), "red"), Image.new("RGB", (24, 24), "blue")]
    frames[0].save(gif_path, save_all=True, append_images=[frames[1]], duration=[30, 30], loop=0)

    profile = Profile(rows=1, columns=2, screensaver_gif_path=str(gif_path), screensaver_idle_seconds=5)
    controller = StreamDeckController()
    controller._animation_stop.set()
    controller._profile = profile

    assert controller._screensaver_frame_duration(0) == SCREENSAVER_MIN_FRAME_SECONDS


def test_screensaver_preview_restores_profile_when_stopped(tmp_path, monkeypatch):
    gif_path = tmp_path / "preview.gif"
    frames = [Image.new("RGB", (24, 24), "green"), Image.new("RGB", (24, 24), "purple")]
    frames[0].save(gif_path, save_all=True, append_images=[frames[1]], duration=[80, 80], loop=0)

    profile = Profile(rows=1, columns=2)
    profile.set_button(0, ButtonConfig(label="One"))
    profile.set_button(1, ButtonConfig(label="Two"))

    controller = StreamDeckController()
    controller._animation_stop.set()
    controller._deck = FakeDeck()
    controller.info = DeckInfo(connected=True, key_count=2)
    controller._profile = profile
    monkeypatch.setattr("streamdeck_studio.deck.to_streamdeck_native", lambda _deck, image: image.tobytes())

    assert controller.preview_screensaver(str(gif_path)) is True
    assert controller._screensaver_active is True
    assert controller._screensaver_preview_path == str(gif_path)

    controller.stop_screensaver_preview()

    assert controller._screensaver_active is False
    assert controller._screensaver_preview_path == ""
    assert [index for index, _image in controller._deck.images[-2:]] == [0, 1]


def test_stop_screensaver_preview_restores_idle_screensaver_without_preview_flag(tmp_path, monkeypatch):
    gif_path = tmp_path / "idle.gif"
    Image.new("RGB", (24, 24), "black").save(gif_path)

    profile = Profile(rows=1, columns=2, screensaver_gif_path=str(gif_path), screensaver_idle_seconds=5)
    controller = StreamDeckController()
    controller._animation_stop.set()
    controller._deck = FakeDeck()
    controller.info = DeckInfo(connected=True, key_count=2)
    controller._profile = profile
    controller._screensaver_active = True
    controller._screensaver_preview_path = ""
    monkeypatch.setattr("streamdeck_studio.deck.to_streamdeck_native", lambda _deck, image: image.tobytes())

    controller.stop_screensaver_preview()

    assert controller._screensaver_active is False
    assert [index for index, _image in controller._deck.images[-2:]] == [0, 1]


def test_wake_press_is_consumed_instead_of_dispatched(tmp_path, monkeypatch):
    gif_path = tmp_path / "idle.gif"
    Image.new("RGB", (24, 24), "black").save(gif_path)

    calls = []
    profile = Profile(rows=1, columns=2, screensaver_gif_path=str(gif_path), screensaver_idle_seconds=5)
    controller = StreamDeckController()
    controller._animation_stop.set()
    controller._deck = FakeDeck()
    controller.info = DeckInfo(connected=True, key_count=2)
    controller._profile = profile
    controller._screensaver_active = True
    controller.on_key_pressed(lambda key: calls.append(("press", key)))
    controller.on_key_released(lambda key: calls.append(("release", key)))
    monkeypatch.setattr("streamdeck_studio.deck.to_streamdeck_native", lambda _deck, image: image.tobytes())

    controller._on_key_event(None, 0, True)
    controller._on_key_event(None, 0, False)

    assert controller._screensaver_active is False
    assert calls == []
