import json

from streamdeck_studio.mcp_server import activate_button, handle_request, list_buttons
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


def test_activate_button_runs_configured_button_without_side_effect_for_none():
    profile = Profile(name="MCP Deck", rows=1, columns=1)

    assert activate_button(1, profile) == "No action configured."


def test_handle_tools_list_request():
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    assert response is not None
    assert response["id"] == 1
    assert [tool["name"] for tool in response["result"]["tools"]] == [
        "get_profile",
        "list_buttons",
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
