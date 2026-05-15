from streamdeck_studio.model import (
    ButtonConfig,
    MCP_PROFILE_ID,
    MCP_PROFILE_NAME,
    Profile,
    create_default_icon_profile,
    ensure_mcp_profile,
    list_profile_ids,
    load_active_profile,
    load_default_profile_id,
    load_profile,
    next_profile_name,
    save_active_profile_id,
    save_default_profile_id,
    save_profile,
    save_profile_by_id,
)


def test_profile_round_trip(tmp_path):
    path = tmp_path / "profile.json"
    profile = Profile(name="Work", rows=2, columns=3)
    profile.get_button(1).label = "Terminal"
    profile.get_button(1).action_type = "command"
    profile.get_button(1).target = "kitty"
    profile.get_button(1).background_image_path = "/tmp/background.png"
    profile.get_button(1).action_image_path = "/tmp/action.png"
    profile.get_button(1).label_position = "top"

    save_profile(profile, path)
    loaded = load_profile(path)

    assert loaded.name == "Work"
    assert loaded.rows == 2
    assert loaded.columns == 3
    assert loaded.get_button(1).label == "Terminal"
    assert loaded.get_button(1).target == "kitty"
    assert loaded.get_button(1).background_image_path == "/tmp/background.png"
    assert loaded.get_button(1).action_image_path == "/tmp/action.png"
    assert loaded.get_button(1).label_position == "top"


def test_invalid_label_position_loads_as_bottom():
    config = ButtonConfig.from_dict({"label": "Docs", "label_position": "sideways"})

    assert config.label_position == "bottom"


def test_named_profiles_and_active_selection_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_profile_by_id("work", Profile(name="Work"))
    save_active_profile_id("work")

    profile_id, profile = load_active_profile()

    assert profile_id == "work"
    assert profile.name == "Work"
    assert "work" in list_profile_ids()


def test_missing_default_profile_loads_default_icon_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    profile_id, profile = load_active_profile()

    assert profile_id == "default"
    assert profile.name == "New Profile"
    assert profile.page_names == {"main": "Main", "tutorials": "Tutorials"}
    assert profile.get_button(0, "main").action_image_path.endswith("home.png")


def test_list_profile_ids_skips_corrupt_profiles(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_profile_by_id("work", Profile(name="Work"))
    bad = tmp_path / "streamdeck-studio" / "profiles" / "bad.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{not-json", encoding="utf-8")

    assert list_profile_ids() == ["default", "work"]


def test_next_profile_name_avoids_existing_ids_after_rename(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_profile_by_id("new-profile", Profile(name="Renamed"))

    assert next_profile_name() == "New Profile 2"


def test_default_profile_selection_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    save_profile_by_id("work", Profile(name="Work"))
    save_default_profile_id("work")

    assert load_default_profile_id() == "work"


def test_ensure_mcp_profile_creates_blank_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    profile = ensure_mcp_profile(rows=2, columns=4)

    assert profile.name == MCP_PROFILE_NAME
    assert profile.rows == 2
    assert profile.columns == 4
    assert profile.current_buttons() == {}
    assert MCP_PROFILE_ID in list_profile_ids()


def test_default_icon_profile_has_main_and_tutorial_pages():
    profile = create_default_icon_profile("New Profile", rows=3, columns=5)

    assert profile.page_names == {"main": "Main", "tutorials": "Tutorials"}
    assert profile.current_page == "main"
    assert len(profile.pages["main"]) == 15
    assert len(profile.pages["tutorials"]) == 15
    assert profile.get_button(0, "main").action_image_path.endswith("home.png")
    assert profile.get_button(0, "tutorials").action_image_path.endswith("terminal.png")


def test_mcp_profile_edits_persist_after_activation(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    profile = ensure_mcp_profile(rows=2, columns=4)
    profile.set_button(3, ButtonConfig(label="Agent Run", action_type="command", target="true"))

    save_profile_by_id(MCP_PROFILE_ID, profile)
    loaded = ensure_mcp_profile()

    assert loaded.get_button(3).label == "Agent Run"
    assert loaded.get_button(3).action_type == "command"
    assert loaded.get_button(3).target == "true"


def test_swap_buttons_exchanges_configured_slots():
    profile = Profile(rows=2, columns=3)
    profile.set_button(0, ButtonConfig(label="One"))
    profile.set_button(4, ButtonConfig(label="Five"))

    profile.swap_buttons(0, 4)

    assert profile.get_button(0).label == "Five"
    assert profile.get_button(4).label == "One"


def test_swap_buttons_moves_into_empty_slot_without_storing_blank_source():
    profile = Profile(rows=2, columns=3)
    profile.set_button(1, ButtonConfig(label="Terminal"))

    profile.swap_buttons(1, 5)

    assert "1" not in profile.current_buttons()
    assert profile.get_button(5).label == "Terminal"
