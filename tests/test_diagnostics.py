from collections import Counter

from streamdeck_studio.diagnostics import profile_diagnostics, redact_target
from streamdeck_studio.model import ButtonConfig, Profile


def test_profile_diagnostics_summarizes_import_without_text_targets(monkeypatch):
    monkeypatch.setattr("streamdeck_studio.diagnostics._translated_launcher", lambda _target: [])
    profile = Profile(name="Imported", pages={"main": {}}, page_names={"main": "Main"})
    profile.set_button(0, ButtonConfig(label="Secret", action_type="text", target="very private value"), page_id="main")
    profile.set_button(1, ButtonConfig(label="Broken nav", action_type="page", target="missing-page"), page_id="main")
    profile.set_button(2, ButtonConfig(label="FaceTime", action_type="file", target="/System/Applications/FaceTime.app"), page_id="main")
    profile.set_button(3, ButtonConfig(label="Unsupported", action_type="none", subtitle="Imported"), page_id="main")

    report = profile_diagnostics(profile)
    rendered = report.render()

    assert report.page_count == 1
    assert report.configured_buttons == 4
    assert report.action_counts == Counter({"text": 1, "page": 1, "file": 1, "none": 1})
    assert "missing-page" in rendered
    assert "FaceTime" in rendered
    assert "imported button has no supported action yet" in rendered
    assert "very private value" not in rendered


def test_profile_diagnostics_does_not_flag_translated_mac_launcher(monkeypatch):
    monkeypatch.setattr("streamdeck_studio.diagnostics._translated_launcher", lambda _target: ["gio", "launch", "org.gnome.Calculator.desktop"])
    profile = Profile(name="Imported", pages={"main": {}}, page_names={"main": "Main"})
    profile.set_button(0, ButtonConfig(label="Calculator", action_type="file", target="/System/Applications/Calculator.app"), page_id="main")

    rendered = profile_diagnostics(profile).render()

    assert "Issues: none found" in rendered


def test_redact_target_only_hides_text_actions():
    assert redact_target(ButtonConfig(action_type="text", target="secret")) == "<redacted text>"
    assert redact_target(ButtonConfig(action_type="url", target="example.com")) == "example.com"
    assert redact_target(ButtonConfig(action_type="command", target="")) == "-"
