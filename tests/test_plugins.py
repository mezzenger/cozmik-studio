import json

import pytest

from streamdeck_studio.actions import ActionError, run_action
from streamdeck_studio.diagnostics import profile_diagnostics
from streamdeck_studio.model import ButtonConfig, Profile
from streamdeck_studio.plugin_helpers import home_assistant_call_service
from streamdeck_studio.plugins import (
    command_for_action,
    install_library_plugin,
    list_library_plugins,
    list_plugin_actions,
    load_plugin_config,
    parse_plugin_target,
    plugin_config_fields,
    plugin_library_dir,
    plugins_dir,
    save_plugin_config,
    uninstall_plugin,
)


def test_plugin_action_type_round_trips():
    config = ButtonConfig.from_dict({"action_type": "plugin", "target": "demo.hello"})

    assert config.action_type == "plugin"
    assert config.target == "demo.hello"


def test_plugin_manifest_actions_are_discovered(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    manifest = plugins_dir() / "demo" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "id": "demo",
                "name": "Demo",
                "actions": [
                    {
                        "id": "hello",
                        "label": "Hello",
                        "command": ["printf", "hello"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    actions = list_plugin_actions()

    assert len(actions) == 1
    assert actions[0].qualified_id == "demo.hello"
    assert actions[0].label == "Hello"


def test_bundled_plugin_library_is_listed():
    items = list_library_plugins()

    assert {item.plugin_id for item in items} >= {
        "desktop-tools",
        "home-assistant",
        "media-player",
        "notifications",
        "sengled-home",
        "smart-life",
        "sunco-smart-lighting",
        "tuya-cloud",
        "wled",
        "yolink",
    }
    assert "google-home" not in {item.plugin_id for item in items}
    assert all(item.action_count > 0 for item in items)


def test_desktop_tools_library_is_expanded():
    desktop = next(item for item in list_library_plugins() if item.plugin_id == "desktop-tools")

    assert desktop.action_count >= 20


def test_desktop_tools_actions_have_standard_graphics(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("desktop-tools")
    actions = list_plugin_actions()
    desktop_actions = [action for action in actions if action.plugin_id == "desktop-tools"]
    action_images_dir = plugin_library_dir().parent / "action-images"

    assert desktop_actions
    assert all(action.icon for action in desktop_actions)
    for action in desktop_actions:
        assert (action_images_dir / action.icon).exists(), action.qualified_id


def test_smart_light_plugins_have_config_pages(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for plugin_id in ("wled", "tuya-cloud", "smart-life", "yolink", "sengled-home", "sunco-smart-lighting"):
        install_library_plugin(plugin_id)
    fields_by_plugin = {plugin_id: plugin_config_fields(plugin_id) for plugin_id in ("wled", "tuya-cloud", "smart-life", "yolink", "sengled-home", "sunco-smart-lighting")}

    for plugin_id in ("wled", "tuya-cloud", "smart-life", "yolink", "sengled-home", "sunco-smart-lighting"):
        assert fields_by_plugin[plugin_id], plugin_id
    assert any(field.key == "host" for field in fields_by_plugin["wled"])
    assert any(field.secret and field.key == "client_secret" for field in fields_by_plugin["tuya-cloud"])
    assert any(field.secret and field.key == "secret_key" for field in fields_by_plugin["yolink"])


def test_plugin_config_round_trips_and_feeds_command(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("wled")
    save_plugin_config("wled", {"host": "wled-office.local"})
    action = next(action for action in list_plugin_actions() if action.qualified_id == "wled.turn-on")

    assert load_plugin_config("wled") == {"host": "wled-office.local"}
    assert command_for_action(action) == [
        "curl",
        "-fsS",
        "-X",
        "POST",
        "http://wled-office.local/json/state",
        "-H",
        "Content-Type: application/json",
        "-d",
        "{\"on\":true}",
    ]


def test_plugin_command_formatting_preserves_json_braces(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("wled")
    save_plugin_config("wled", {"host": "wled-office.local"})
    brightness = next(action for action in list_plugin_actions() if action.qualified_id == "wled.brightness")
    preset = next(action for action in list_plugin_actions() if action.qualified_id == "wled.preset")

    assert command_for_action(brightness, {"bri": "42"})[-1] == '{"bri":42}'
    assert command_for_action(preset, {"preset": "3"})[-1] == '{"ps":3}'


def test_github_reengineered_plugins_are_installable_not_standalone_links():
    items = {item.plugin_id: item for item in list_library_plugins()}

    assert items["home-assistant"].source_url == "https://github.com/cgiesche/streamdeck-homeassistant"
    assert items["home-assistant"].source_stars == 975
    assert items["media-player"].source_url == "https://github.com/altdesktop/playerctl"
    assert all(item.name not in {"OpenDeck", "StreamController"} for item in items.values())


def test_library_plugin_installs_to_user_plugins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    target = install_library_plugin("notifications")

    assert target == plugins_dir() / "notifications" / "plugin.json"
    assert target.exists()
    assert any(action.qualified_id == "notifications.ping" for action in list_plugin_actions())
    installed = {item.plugin_id: item.installed for item in list_library_plugins()}
    assert installed["notifications"] is True


def test_library_plugin_can_be_removed(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("notifications")

    uninstall_plugin("notifications")

    assert not (plugins_dir() / "notifications").exists()
    installed = {item.plugin_id: item.installed for item in list_library_plugins()}
    assert installed["notifications"] is False


def test_reengineered_github_plugin_installs_to_user_plugins(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    install_library_plugin("home-assistant")

    actions = {action.qualified_id for action in list_plugin_actions()}
    assert {"home-assistant.call-service", "home-assistant.toggle"} <= actions


def test_plugin_action_target_template_uses_json_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("desktop-tools")
    action = next(action for action in list_plugin_actions() if action.qualified_id == "desktop-tools.open-url")

    target = json.loads(action.target_template())

    assert target["plugin"] == "desktop-tools"
    assert target["action"] == "open-url"
    assert target["settings"]["url"] == "https://example.com"


def test_plugin_command_replaces_settings_values(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("desktop-tools")
    action = next(action for action in list_plugin_actions() if action.qualified_id == "desktop-tools.show-notification")

    command = command_for_action(action, {"title": "Title", "message": "Message"})

    assert command == ["notify-send", "Title", "Message"]


def test_plugin_action_target_template_uses_short_target_without_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    install_library_plugin("notifications")
    action = next(action for action in list_plugin_actions() if action.qualified_id == "notifications.ping")

    assert action.target_template() == "notifications.ping"


def test_home_assistant_helper_calls_service(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b"[]"

    def fake_urlopen(req, timeout):
        calls.append((req, timeout))
        return FakeResponse()

    monkeypatch.setattr("streamdeck_studio.plugin_helpers.request.urlopen", fake_urlopen)

    message = home_assistant_call_service(
        {
            "base_url": "http://ha.local:8123/",
            "token": "secret",
            "domain": "light",
            "service": "toggle",
            "entity_id": "light.office",
        }
    )

    assert message == "Called Home Assistant service: light.toggle light.office"
    assert calls[0][0].full_url == "http://ha.local:8123/api/services/light/toggle"
    assert calls[0][0].headers["Authorization"] == "Bearer secret"
    assert calls[0][1] == 5


def test_plugin_action_runs_manifest_command(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    manifest = plugins_dir() / "demo" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"id": "demo", "actions": [{"id": "hello", "command": ["printf", "{settings_json}"]}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr("streamdeck_studio.actions.subprocess.Popen", lambda args, **kwargs: calls.append((args, kwargs)))

    message = run_action(
        ButtonConfig(
            action_type="plugin",
            target=json.dumps({"plugin": "demo", "action": "hello", "settings": {"name": "Ada"}}),
        )
    )

    assert message == "Ran plugin action: demo / hello"
    assert calls == [
        (
            ["printf", '{"name": "Ada"}'],
            {"cwd": manifest.parent, "start_new_session": True},
        )
    ]


def test_plugin_action_reports_missing_action(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(ActionError, match="Plugin action not found"):
        run_action(ButtonConfig(action_type="plugin", target="missing.action"))


def test_plugin_target_accepts_short_and_json_forms():
    assert parse_plugin_target("demo.hello") == ("demo", "hello", {})
    assert parse_plugin_target("demo:hello") == ("demo", "hello", {})
    assert parse_plugin_target('{"plugin": "demo", "action": "hello", "settings": {"x": 1}}') == (
        "demo",
        "hello",
        {"x": 1},
    )


def test_diagnostics_report_missing_plugin_action(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    profile = Profile()
    profile.set_button(0, ButtonConfig(label="Plugin", action_type="plugin", target="missing.action"))

    diagnostics = profile_diagnostics(profile)

    assert diagnostics.issues
    assert diagnostics.issues[0].message == "plugin action is not installed: missing.action"
