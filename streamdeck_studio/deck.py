from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from queue import SimpleQueue
import threading
import time

from .images import button_animation_frame_count, button_animation_frame_duration, render_button_image, to_streamdeck_native
from .model import Profile


@dataclass
class DeckInfo:
    connected: bool
    name: str = "No Stream Deck"
    rows: int = 3
    columns: int = 5
    key_count: int = 15
    error: str = ""


class StreamDeckController:
    def __init__(self) -> None:
        self._deck = None
        self._lock = threading.RLock()
        self.info = DeckInfo(connected=False)
        self._key_pressed_handlers: list[Callable[[int], None]] = []
        self._key_released_handlers: list[Callable[[int], None]] = []
        self._key_event_handlers: list[Callable[[int, bool], None]] = []
        self._status_handlers: list[Callable[[str], None]] = []
        self._profile: Profile | None = None
        self._animation_frames: dict[int, int] = {}
        self._animation_deadlines: dict[int, float] = {}
        self._animation_stop = threading.Event()
        self._events: SimpleQueue[tuple[int, bool]] = SimpleQueue()
        self._dispatcher = threading.Thread(target=self._dispatch_events, daemon=True)
        self._dispatcher.start()
        self._animator = threading.Thread(target=self._animate_buttons, daemon=True)
        self._animator.start()

    def on_key_pressed(self, handler: Callable[[int], None]) -> None:
        self._key_pressed_handlers.append(handler)

    def on_key_released(self, handler: Callable[[int], None]) -> None:
        self._key_released_handlers.append(handler)

    def on_key_event(self, handler: Callable[[int, bool], None]) -> None:
        self._key_event_handlers.append(handler)

    def on_status_changed(self, handler: Callable[[str], None]) -> None:
        self._status_handlers.append(handler)

    def connect_first(self) -> DeckInfo:
        with self._lock:
            self.close()
            try:
                from StreamDeck.DeviceManager import DeviceManager

                decks = DeviceManager().enumerate()
                if not decks:
                    self.info = DeckInfo(connected=False, error="No Stream Deck detected.")
                    self._emit_status(self.info.error)
                    return self.info
                self._deck = decks[0]
                self._deck.open()
                self._deck.set_poll_frequency(30)
                self._deck.set_key_callback(self._on_key_event)
                rows, columns = self._deck.key_layout()
                self.info = DeckInfo(
                    connected=True,
                    name=self._deck.deck_type(),
                    rows=rows,
                    columns=columns,
                    key_count=self._deck.key_count(),
                )
                self._emit_status(f"Connected to {self.info.name}.")
            except Exception as exc:
                self._deck = None
                self.info = DeckInfo(connected=False, error=str(exc))
                self._emit_status(f"Stream Deck unavailable: {exc}")
            return self.info

    def apply_profile(self, profile: Profile) -> None:
        with self._lock:
            self._profile = profile
            self._animation_frames.clear()
            self._animation_deadlines.clear()
            if not self._deck:
                return
            for index in range(min(profile.button_count(), self.info.key_count)):
                self.apply_button(profile, index)

    def apply_button(self, profile: Profile, index: int) -> None:
        with self._lock:
            self._profile = profile
            self._animation_frames.pop(index, None)
            self._animation_deadlines.pop(index, None)
            if not self._deck or index >= self.info.key_count:
                return
            self._set_key_image(profile, index, 0)

    def close(self, reset: bool = False) -> None:
        with self._lock:
            if self._deck:
                try:
                    self._deck.set_key_callback(None)
                    if reset:
                        self._deck.reset()
                    self._deck.close()
                except Exception:
                    pass
            self._deck = None
            self._profile = None
            self._animation_frames.clear()
            self._animation_deadlines.clear()

    def _on_key_event(self, deck, key: int, state: bool) -> None:
        self._events.put((key, state))

    def _emit_status(self, message: str) -> None:
        for handler in self._status_handlers:
            handler(message)

    def _dispatch_events(self) -> None:
        while True:
            key, pressed = self._events.get()
            for handler in list(self._key_event_handlers):
                handler(key, pressed)
            handlers = self._key_pressed_handlers if pressed else self._key_released_handlers
            for handler in list(handlers):
                handler(key)

    def _animate_buttons(self) -> None:
        while not self._animation_stop.wait(0.03):
            now = time.monotonic()
            updates: list[tuple[Profile, int, int]] = []
            with self._lock:
                if not self._deck or not self._profile:
                    continue
                limit = min(self._profile.button_count(), self.info.key_count)
                for index in range(limit):
                    config = self._profile.get_button(index)
                    frame_count = button_animation_frame_count(config)
                    if frame_count <= 1:
                        self._animation_frames.pop(index, None)
                        self._animation_deadlines.pop(index, None)
                        continue
                    deadline = self._animation_deadlines.get(index, 0)
                    if deadline > now:
                        continue
                    frame = (self._animation_frames.get(index, 0) + 1) % frame_count
                    self._animation_frames[index] = frame
                    self._animation_deadlines[index] = now + button_animation_frame_duration(config, frame)
                    updates.append((self._profile, index, frame))
                for profile, index, frame in updates:
                    self._set_key_image(profile, index, frame)

    def _set_key_image(self, profile: Profile, index: int, frame: int) -> None:
        image = render_button_image(profile.get_button(index), self._deck.key_image_format()["size"], frame)
        native = to_streamdeck_native(self._deck, image)
        self._deck.set_key_image(index, native)


def probe_deck() -> DeckInfo:
    controller = StreamDeckController()
    try:
        return controller.connect_first()
    finally:
        controller.close()
