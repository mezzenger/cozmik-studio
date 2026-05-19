from streamdeck_studio.gtk_ui import _parse_args, _should_start_minimized


def test_minimized_startup_flags_are_accepted():
    assert _parse_args(["--minimized"]).start_minimized is True
    assert _parse_args(["--start-minimized"]).start_minimized is True
    assert _parse_args(["--hidden"]).start_minimized is True


def test_minimized_startup_defaults_off():
    assert _parse_args([]).start_minimized is False


def test_saved_minimized_startup_is_used(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    from streamdeck_studio.model import save_start_minimized

    save_start_minimized(True)

    assert _should_start_minimized(_parse_args([])) is True


def test_cli_minimized_overrides_saved_normal_startup(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert _should_start_minimized(_parse_args(["--minimized"])) is True
