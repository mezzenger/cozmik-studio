from streamdeck_studio.action_icons import action_icons
from streamdeck_studio.model import ButtonConfig, Profile, profile_action_icons_dir, save_profile


def _write_png(path):
    from PIL import Image

    Image.new("RGB", (24, 24), "#ff0000").save(path)


def test_action_icon_library_contains_common_navigation_icons(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    names = {icon.name for icon in icons}
    groups = {icon.group for icon in icons}

    assert len(icons) >= 40
    assert {"Next Page", "Previous Page", "Parent Page", "Home"} <= names
    assert "Simple" in groups
    assert "Built In" not in groups
    assert all(icon.path.exists() for icon in icons)


def test_action_icon_library_does_not_show_main_page_group(tmp_path, monkeypatch):
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

    assert "Main Page" not in {icon.group for icon in icons}


def test_action_icon_library_includes_bundled_gif_resource(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    umbrella = [icon for icon in icons if icon.name == "Umbrella 028"]

    assert umbrella
    assert umbrella[0].group == "Elgato"
    assert umbrella[0].path.suffix == ".gif"
    assert umbrella[0].path.exists()


def test_action_icon_library_starts_with_bundled_default_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    default_icons = icons[:32]
    names = {icon.name for icon in default_icons}

    assert len(default_icons) == 32
    assert {"Home", "Terminal", "Calendar", "Search", "Volume Up", "Screenshot", "Emoji", "Calculator"} <= names
    assert {icon.group for icon in default_icons} == {"Default"}
    assert all("action-images/default" in str(icon.path) for icon in default_icons)


def test_action_icon_library_includes_bundled_neon_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    neon_icons = [icon for icon in icons if icon.name.startswith("Neon ")]
    names = {icon.name for icon in neon_icons}

    assert len(neon_icons) == 24
    assert {
        "Neon Home",
        "Neon Terminal",
        "Neon Favorites Star",
        "Neon Volume Up",
        "Neon Screenshot",
        "Neon Emoji",
        "Neon Up Arrow",
        "Neon Calculator",
    } <= names
    assert {icon.group for icon in neon_icons} == {"Neon"}
    assert all(icon.path.exists() for icon in neon_icons)


def test_action_icon_library_includes_obs_studio_variants(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    names = {icon.name for icon in icons}
    obs_icons = [icon for icon in icons if icon.name.startswith("Obs Studio ")]

    assert len(obs_icons) == 4
    assert {
        "Obs Studio Cyber",
        "Obs Studio Metallic",
        "Obs Studio Minimal",
        "Obs Studio Neon",
    } <= names
    assert {icon.name: icon.group for icon in obs_icons} == {
        "Obs Studio Cyber": "Cyber",
        "Obs Studio Metallic": "Installed Apps",
        "Obs Studio Minimal": "Installed Apps",
        "Obs Studio Neon": "Neon",
    }
    assert all(icon.path.exists() for icon in obs_icons)


def test_action_icon_library_has_no_minimal_or_metallic_groups(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()

    assert {"Minimal", "Metallic"}.isdisjoint({icon.group for icon in icons})


def test_action_icon_library_includes_profile_user_installed_icons(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    icon_path = profile_action_icons_dir("work") / "custom-scene.png"
    icon_path.parent.mkdir(parents=True)
    _write_png(icon_path)

    icons = action_icons("work")
    user_icons = [icon for icon in icons if icon.group == "User Installed"]

    assert len(user_icons) == 1
    assert user_icons[0].name == "Custom Scene"
    assert user_icons[0].path == icon_path


def test_action_icon_library_includes_additional_button_face_styles(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()
    names = {icon.name for icon in icons}
    styles = {
        "Set 1 Streamlined Neon": "Streamlined Neon",
        "Set 2 Sleek Flat": "Sleek Flat",
        "Set 3 Retro Pixel": "Retro Pixel",
        "Set 4 Monochrome Minimal": "Monochrome Minimal",
    }

    for style, group in styles.items():
        style_icons = [icon for icon in icons if icon.name.startswith(style)]
        style_group_icons = [icon for icon in style_icons if icon.group == group]
        elgato_icons = [icon for icon in style_icons if icon.group == "Elgato"]
        assert len(style_icons) == 93
        assert len(style_group_icons) == 71
        assert len(elgato_icons) == 22
        assert f"{style} Simple Scan" in names
        assert all(icon.path.exists() for icon in style_icons)


def test_action_icon_library_has_no_bundled_group(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    icons = action_icons()

    assert "Bundled" not in {icon.group for icon in icons}
