import pytest

from streamdeck_studio.actions import ActionError, copy_text_action, paste_text_action, run_action
from streamdeck_studio.model import ButtonConfig


def test_command_action_splits_arguments(monkeypatch):
    calls = []

    def fake_popen(args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr("streamdeck_studio.actions.subprocess.Popen", fake_popen)

    message = run_action(ButtonConfig(action_type="command", target="echo 'hello world'"))

    assert message == "Started command: echo 'hello world'"
    assert calls[0][0] == ["echo", "hello world"]
    assert calls[0][1]["start_new_session"] is True


def test_command_action_rejects_bad_quoting():
    with pytest.raises(ActionError):
        run_action(ButtonConfig(action_type="command", target="echo 'unterminated"))


def test_text_action_copies_before_paste():
    calls = []

    message = run_action(
        ButtonConfig(action_type="text", target="expected target"),
        copy_text=lambda text: calls.append(("copy", text)),
        paste=lambda: calls.append(("paste", "")),
    )

    assert message == "Pasted text."
    assert calls == [("copy", "expected target"), ("paste", "")]


def test_text_action_can_split_press_and_release():
    calls = []
    config = ButtonConfig(action_type="text", target="expected target")

    assert copy_text_action(config, copy_text=lambda text: calls.append(("copy", text))) == "Copied text."
    assert calls == [("copy", "expected target")]

    assert paste_text_action(config, paste=lambda: calls.append(("paste", ""))) == "Pasted text."
    assert calls == [("copy", "expected target"), ("paste", "")]
