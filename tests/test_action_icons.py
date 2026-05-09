from streamdeck_studio.action_icons import action_icons
from streamdeck_studio.model import ButtonConfig, Profile, save_profile


def _write_png(path):
    from PIL import Image

    Image.new("RGB", (24, 24), "#ff0000").save(path)


def test_action_icon_library_contains_common_navigation_icons(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    names = {icon.name for icon in icons}

    assert len(icons) >= 40
    assert {"Next Page", "Previous Page", "Parent Page", "Home"} <= names
    assert all(icon.path.exists() for icon in icons)


def test_action_icon_library_copies_main_page_icons(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    source = tmp_path / "main-icon.png"
    _write_png(source)
    profile = Profile(
        name="Imported",
        pages={"main": {"0": ButtonConfig(label="Apps", action_image_path=str(source))}},
        page_names={"main": "MAIN"},
        current_page="main",
    )
    save_profile(profile)

    icons = action_icons()
    main_icons = [icon for icon in icons if icon.name == "Apps"]

    assert main_icons
    assert all(icon.path.exists() for icon in main_icons)
