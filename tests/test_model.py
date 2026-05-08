from streamdeck_studio.model import Profile, load_profile, save_profile


def test_profile_round_trip(tmp_path):
    path = tmp_path / "profile.json"
    profile = Profile(name="Work", rows=2, columns=3)
    profile.get_button(1).label = "Terminal"
    profile.get_button(1).action_type = "command"
    profile.get_button(1).target = "kitty"

    save_profile(profile, path)
    loaded = load_profile(path)

    assert loaded.name == "Work"
    assert loaded.rows == 2
    assert loaded.columns == 3
    assert loaded.get_button(1).label == "Terminal"
    assert loaded.get_button(1).target == "kitty"
