import subprocess

import pytest

from streamdeck_studio.actions import ActionError, _parse_key_press_script, copy_text_action, paste_text_action, run_action
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


def test_command_action_resolves_gnome_alias(monkeypatch):
    calls = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "gnome-control-center" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="command", target="settings"))

    assert message == "Started command: settings"
    assert calls[0][0] == ["gnome-control-center"]


def test_command_action_rejects_bad_quoting():
    with pytest.raises(ActionError):
        run_action(ButtonConfig(action_type="command", target="echo 'unterminated"))


def test_tutorial_action_is_gui_handled_noop():
    assert run_action(ButtonConfig(action_type="tutorial", target="cozmik-tutorial:[]")) == "Opened tutorial."


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


def test_url_action_adds_https_scheme(monkeypatch):
    calls = []

    monkeypatch.setattr("streamdeck_studio.actions.webbrowser.open", lambda url, **kwargs: calls.append((url, kwargs)) or True)

    message = run_action(ButtonConfig(action_type="url", target="example.com"))

    assert message == "Opened URL: https://example.com"
    assert calls == [("https://example.com", {"new": 2})]


def test_file_action_translates_mac_app_to_linux_desktop_file(monkeypatch, tmp_path):
    calls = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: "/usr/bin/gio" if command == "gio" else None)
    monkeypatch.setattr("streamdeck_studio.actions._desktop_file_exists", lambda name: name == "org.gnome.Calculator.desktop")
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="file", target="/System/Applications/Calculator.app"))

    assert message == "Started: /usr/bin/gio launch org.gnome.Calculator.desktop"
    assert calls == [(["/usr/bin/gio", "launch", "org.gnome.Calculator.desktop"], {"start_new_session": True})]


def test_file_action_reports_unmapped_mac_app(monkeypatch):
    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda _command: None)
    monkeypatch.setattr("streamdeck_studio.actions._desktop_file_exists", lambda _name: False)

    with pytest.raises(ActionError, match="No Linux launcher found"):
        run_action(ButtonConfig(action_type="file", target="/System/Applications/FaceTime.app"))


def test_media_action_uses_wpctl_when_available(monkeypatch):
    calls = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "wpctl" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="media", target="volume-up"))

    assert message == "Ran media action: volume-up"
    assert calls == [(["/usr/bin/wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"], {"start_new_session": True})]


def test_shortcut_action_uses_ydotool_when_available(monkeypatch):
    calls = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "ydotool" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="shortcut", target="ctrl+alt+shift+r"))

    assert message == "Sent shortcut: ctrl+alt+shift+r"
    assert calls[0][1]["check"] is True
    assert calls == [
        (
            ["/usr/bin/ydotool", "key", "29:1", "56:1", "42:1", "19:1", "19:0", "42:0", "56:0", "29:0"],
            calls[0][1],
        )
    ]


def test_shortcut_action_uses_builtin_evdev_codes_without_kernel_headers(monkeypatch):
    calls = []

    def missing_header(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("streamdeck_studio.actions.Path.read_text", missing_header)
    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "ydotool" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="shortcut", target="ctrl+a"))

    assert message == "Sent shortcut: ctrl+a"
    assert calls == [
        (
            ["/usr/bin/ydotool", "key", "29:1", "30:1", "30:0", "29:0"],
            calls[0][1],
        )
    ]


def test_shortcut_action_falls_back_to_wtype(monkeypatch):
    calls = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "wtype" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="shortcut", target="ctrl+period"))

    assert message == "Sent shortcut: ctrl+period"
    assert calls == [
        (
            ["/usr/bin/wtype", "-M", "ctrl", ".", "-m", "ctrl"],
            {"check": True},
        )
    ]


def test_press_keys_parser_supports_groups_and_delays():
    assert _parse_key_press_script("alt+delay+F4,f") == [
        ("down", ["leftalt"]),
        ("delay", 0.5),
        ("tap", ["f4"]),
        ("up", ["leftalt"]),
        ("tap", ["f"]),
    ]


def test_press_keys_parser_supports_custom_delay_and_literals():
    assert _parse_key_press_script('1,delay 1,2,plus,comma,",enter') == [
        ("tap", ["1"]),
        ("delay", 1.0),
        ("tap", ["2"]),
        ("tap", ["kpplus"]),
        ("tap", ["comma"]),
        ("tap", ["leftshift", "apostrophe"]),
        ("tap", ["enter"]),
    ]


def test_keys_action_uses_ydotool_for_multi_step_script(monkeypatch):
    calls = []
    sleeps = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "ydotool" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("streamdeck_studio.actions.time.sleep", lambda seconds: sleeps.append(seconds))

    message = run_action(ButtonConfig(action_type="keys", target="alt+delay+F4,f"))

    assert message == "Sent key presses: alt+delay+F4,f"
    assert sleeps == [0.5]
    assert calls == [
        (["/usr/bin/ydotool", "key", "56:1"], calls[0][1]),
        (["/usr/bin/ydotool", "key", "62:1", "62:0", "56:0", "33:1", "33:0"], calls[1][1]),
    ]


def test_keys_action_uses_builtin_evdev_codes_without_kernel_headers(monkeypatch):
    calls = []

    def missing_header(*_args, **_kwargs):
        raise FileNotFoundError

    monkeypatch.setattr("streamdeck_studio.actions.Path.read_text", missing_header)
    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "ydotool" else None)
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(ButtonConfig(action_type="keys", target="enter,F4"))

    assert message == "Sent key presses: enter,F4"
    assert calls == [
        (
            ["/usr/bin/ydotool", "key", "28:1", "28:0", "62:1", "62:0"],
            calls[0][1],
        )
    ]


def test_keys_action_falls_back_to_xdotool_when_ydotool_fails(monkeypatch):
    calls = []

    monkeypatch.setattr(
        "streamdeck_studio.actions.shutil.which",
        lambda command: f"/usr/bin/{command}" if command in {"ydotool", "xdotool"} else None,
    )

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "/usr/bin/ydotool":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", fake_run)

    message = run_action(ButtonConfig(action_type="keys", target="a"))

    assert message == "Sent key presses: a"
    assert calls == [
        (["/usr/bin/ydotool", "key", "30:1", "30:0"], calls[0][1]),
        (["/usr/bin/xdotool", "key", "a"], {"check": True}),
    ]


def test_keys_action_releases_ydotool_keys_before_fallback_after_unsupported_token(monkeypatch):
    calls = []
    sleeps = []

    monkeypatch.setattr("streamdeck_studio.actions.shutil.which", lambda command: f"/usr/bin/{command}" if command == "ydotool" else None)
    monkeypatch.setattr("streamdeck_studio.actions._key_code_for_ydotool", lambda key, _codes: None if key == "unknown" else {"leftalt": 56}.get(key))
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.run", lambda args, **kwargs: calls.append((args, kwargs)))
    monkeypatch.setattr("streamdeck_studio.actions.time.sleep", lambda seconds: sleeps.append(seconds))

    try:
        run_action(ButtonConfig(action_type="keys", target="alt+delay+unknown"))
    except ActionError as error:
        assert "No keyboard helper found" in str(error)
    else:
        raise AssertionError("Expected ActionError")

    assert sleeps == [0.5]
    assert calls == [
        (["/usr/bin/ydotool", "key", "56:1"], calls[0][1]),
        (["/usr/bin/ydotool", "key", "56:0"], calls[1][1]),
    ]
