from streamdeck_studio.action_icons import action_icons


def test_action_icon_library_contains_common_navigation_icons(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    names = {icon.name for icon in icons}

    assert len(icons) >= 40
    assert {"Next Page", "Previous Page", "Parent Page", "Home"} <= names
    assert all(icon.path.exists() for icon in icons)
