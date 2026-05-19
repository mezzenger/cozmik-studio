import json
import pytest

import streamdeck_studio.mcp_server as mcp_server
from streamdeck_studio.actions import ActionError
from streamdeck_studio.mcp_server import activate_button, handle_request, list_buttons, switch_page
from streamdeck_studio.model import ButtonConfig, Profile


def test_list_buttons_skips_blank_buttons():
    profile = Profile(name="MCP Deck", rows=1, columns=2)
    profile.set_button(0, ButtonConfig(label="Docs", action_type="url", target="example.com"))

    assert list_buttons(profile) == [
        {
            "button": 1,
            "label": "Docs",
            "subtitle": "",
            "action_type": "url",
            "target": "example.com",
        }
    ]


def test_list_buttons_redacts_sensitive_action_types():
    profile = Profile(name="MCP Deck", rows=1, columns=5)
    profile.set_button(0, ButtonConfig(label="A", action_type="text", target="secret"))
    profile.set_button(1, ButtonConfig(label="B", action_type="command", target="/usr/bin/secret"))
    profile.set_button(2, ButtonConfig(label="C", action_type="shell", target="echo secret | clip"))
    profile.set_button(3, ButtonConfig(label="D", action_type="file", target="/home/user/private"))
    profile.set_button(4, ButtonConfig(label="E", action_type="plugin", target='{"plugin":"p","action":"a","settings":{"token":"abc"}}'))

    buttons = list_buttons(profile)

    assert all(b["target"] == "[redacted]" for b in buttons)


def test_list_buttons_does_not_redact_safe_action_types():
    profile = Profile(name="MCP Deck", rows=1, columns=3)
    profile.set_button(0, ButtonConfig(label="A", action_type="url", target="https://example.com"))
    profile.set_button(1, ButtonConfig(label="B", action_type="shortcut", target="ctrl+alt+t"))
    profile.set_button(2, ButtonConfig(label="C", action_type="media", target="play"))

    buttons = list_buttons(profile)

    assert [b["target"] for b in buttons] == ["https://example.com", "ctrl+alt+t", "play"]


def test_activate_button_runs_configured_button_without_side_effect_for_none():
    profile = Profile(name="MCP Deck", rows=1, columns=1)

    assert activate_button(button=1, profile=profile) == "No action configured."


def test_activate_button_by_label():
    profile = Profile(name="MCP Deck", rows=1, columns=2)
    profile.set_button(1, ButtonConfig(label="Docs", action_type="none"))

    assert activate_button(label="Docs", profile=profile) == "No action configured."


def test_activate_button_by_label_case_insensitive():
    profile = Profile(name="MCP Deck", rows=1, columns=2)
    profile.set_button(0, ButtonConfig(label="Run Tests", action_type="none"))

    assert activate_button(label="run tests", profile=profile) == "No action configured."


def test_activate_button_by_label_not_found():
    profile = Profile(name="MCP Deck", rows=1, columns=1)

    with pytest.raises(ActionError, match="No button with label"):
        activate_button(label="missing", profile=profile)


def test_activate_button_requires_button_or_label():
    profile = Profile(name="MCP Deck", rows=1, columns=1)

    with pytest.raises(ActionError, match="Provide button number or label"):
        activate_button(profile=profile)


def test_activate_page_button_does_not_save_injected_profile(monkeypatch):
    def fail_save(*args, **kwargs):
        raise AssertionError("Injected profiles should not be persisted")

    monkeypatch.setattr(mcp_server, "save_profile_by_id", fail_save)
    profile = Profile(
        name="MCP Deck",
        rows=1,
        columns=1,
        pages={"main": {"0": ButtonConfig(label="Work", action_type="page", target="work")}, "work": {}},
        page_names={"main": "Main", "work": "Work"},
    )

    result = activate_button(button=1, profile=profile)

    assert result == "Switched page: Work"
    assert profile.current_page == "work"


def test_switch_page_by_id():
    profile = Profile(name="MCP Deck", rows=1, columns=1, pages={"main": {}, "work": {}}, page_names={"main": "Main", "work": "Work"})
    result = switch_page("work", profile)
    assert result == "Switched page: Work"
    assert profile.current_page == "work"


def test_switch_page_does_not_save_injected_profile(monkeypatch):
    def fail_save(*args, **kwargs):
        raise AssertionError("Injected profiles should not be persisted")

    monkeypatch.setattr(mcp_server, "save_profile_by_id", fail_save)
    profile = Profile(name="MCP Deck", rows=1, columns=1, pages={"main": {}, "work": {}}, page_names={"main": "Main", "work": "Work"})

    result = switch_page("work", profile)

    assert result == "Switched page: Work"
    assert profile.current_page == "work"


def test_switch_page_by_name_case_insensitive():
    profile = Profile(name="MCP Deck", rows=1, columns=1, pages={"main": {}, "work": {}}, page_names={"main": "Main", "work": "Work"})
    result = switch_page("WORK", profile)
    assert result == "Switched page: Work"
    assert profile.current_page == "work"


def test_switch_page_not_found():
    profile = Profile(name="MCP Deck", rows=1, columns=1, pages={"main": {}}, page_names={"main": "Main"})
    with pytest.raises(ActionError, match="No page matching"):
        switch_page("missing", profile)


def test_handle_tools_list_request():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    assert response["id"] == 1
    assert [tool["name"] for tool in response["result"]["tools"]] == [
        "get_profile",
        "list_buttons",
        "switch_page",
        "activate_button",
    ]


def test_handle_activate_button_error_is_json_rpc_error(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "activate_button", "arguments": {"button": 1}},
        }
    )

    assert response is not None
    assert response["id"] == 2
    assert response["error"]["code"] == -32000


def test_handle_call_serializes_tool_content(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from streamdeck_studio.model import ensure_mcp_profile

    ensure_mcp_profile(rows=1, columns=1)
    response = handle_request({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "get_profile"}})

    assert response is not None
    text = response["result"]["content"][0]["text"]
    assert json.loads(text)["name"] == "MCP Deck"
