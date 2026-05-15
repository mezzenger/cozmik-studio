from __future__ import annotations

from dataclasses import asdict
import json
import sys
from typing import Any, BinaryIO

from .actions import ActionError, run_action
from .model import MCP_PROFILE_ID, ButtonConfig, Profile, load_profile_by_id, save_profile_by_id


PROTOCOL_VERSION = "2024-11-05"


def list_buttons(profile: Profile | None = None) -> list[dict[str, Any]]:
    profile = profile or load_profile_by_id(MCP_PROFILE_ID)
    buttons: list[dict[str, Any]] = []
    for raw_index, config in sorted(profile.current_buttons().items(), key=lambda item: int(item[0])):
        if _is_blank(config):
            continue
        buttons.append(
            {
                "button": int(raw_index) + 1,
                "label": config.label,
                "subtitle": config.subtitle,
                "action_type": config.action_type,
                "target": config.target if config.action_type not in {"text"} else "[redacted]",
            }
        )
    return buttons


def activate_button(button: int, profile: Profile | None = None) -> str:
    profile = profile or load_profile_by_id(MCP_PROFILE_ID)
    index = button - 1
    if index < 0 or index >= profile.button_count():
        raise ActionError(f"Button must be between 1 and {profile.button_count()}.")
    config = profile.get_button(index)
    if config.action_type == "page":
        if not config.target:
            raise ActionError("The selected page button is not linked.")
        if config.target not in profile.pages:
            raise ActionError("Page target is not available.")
        profile.set_current_page(config.target)
        save_profile_by_id(MCP_PROFILE_ID, profile)
        return f"Switched page: {profile.page_names.get(config.target, config.target)}"
    return run_action(config)


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    request_id = message.get("id")
    method = message.get("method")
    if method == "notifications/initialized":
        return None
    try:
        if method == "initialize":
            result = {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "cozmik-studio", "version": "0.1.0"},
            }
        elif method == "tools/list":
            result = {"tools": _tool_definitions()}
        elif method == "tools/call":
            params = message.get("params", {})
            result = _call_tool(str(params.get("name", "")), params.get("arguments", {}))
        else:
            return _error(request_id, -32601, f"Method not found: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        return _error(request_id, -32000, str(exc))


def serve(input_stream: BinaryIO | None = None, output_stream: BinaryIO | None = None) -> int:
    input_stream = input_stream or sys.stdin.buffer
    output_stream = output_stream or sys.stdout.buffer
    while True:
        message = _read_message(input_stream)
        if message is None:
            return 0
        response = handle_request(message)
        if response is not None:
            _write_message(output_stream, response)


def main() -> int:
    return serve()


def _call_tool(name: str, arguments: Any) -> dict[str, Any]:
    if not isinstance(arguments, dict):
        arguments = {}
    if name == "get_profile":
        profile = load_profile_by_id(MCP_PROFILE_ID)
        payload = {
            "name": profile.name,
            "rows": profile.rows,
            "columns": profile.columns,
            "button_count": profile.button_count(),
            "current_page": profile.current_page,
            "pages": profile.page_names,
        }
    elif name == "list_buttons":
        payload = list_buttons()
    elif name == "activate_button":
        payload = {"message": activate_button(int(arguments.get("button", 0)))}
    else:
        raise ActionError(f"Unknown tool: {name}")
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2, sort_keys=True)}]}


def _tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "get_profile",
            "description": "Return MCP Deck metadata, pages, and layout.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "list_buttons",
            "description": "List configured buttons on the current MCP Deck page.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "activate_button",
            "description": "Activate a configured MCP Deck button by 1-based button number.",
            "inputSchema": {
                "type": "object",
                "properties": {"button": {"type": "integer", "minimum": 1}},
                "required": ["button"],
                "additionalProperties": False,
            },
        },
    ]


def _is_blank(config: ButtonConfig) -> bool:
    return asdict(config) == asdict(ButtonConfig())


def _read_message(stream: BinaryIO) -> dict[str, Any] | None:
    headers: dict[str, str] = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        if line in {b"\r\n", b"\n"}:
            break
        name, _, value = line.decode("ascii").partition(":")
        headers[name.lower()] = value.strip()
    length = int(headers.get("content-length", "0"))
    if length <= 0:
        return None
    return json.loads(stream.read(length).decode("utf-8"))


def _write_message(stream: BinaryIO, message: dict[str, Any]) -> None:
    body = json.dumps(message, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    stream.write(body)
    stream.flush()


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


if __name__ == "__main__":
    raise SystemExit(main())
