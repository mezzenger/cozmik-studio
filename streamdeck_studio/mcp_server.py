from __future__ import annotations

from dataclasses import asdict
import json
import sys
from typing import Any, BinaryIO

from .actions import ActionError, run_action
from .model import MCP_PROFILE_ID, ButtonConfig, Profile, load_profile_by_id, save_profile_by_id


PROTOCOL_VERSION = "2024-11-05"

# Action types whose targets may contain credentials, private paths, or sensitive text.
_REDACTED_ACTION_TYPES = {"text", "command", "shell", "file", "plugin"}


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
                "target": "[redacted]" if config.action_type in _REDACTED_ACTION_TYPES else config.target,
            }
        )
    return buttons


def activate_button(button: int | None = None, label: str | None = None, profile: Profile | None = None) -> str:
    should_persist = profile is None
    if profile is None:
        profile = load_profile_by_id(MCP_PROFILE_ID)
    if label is not None and button is None:
        needle = label.strip().casefold()
        match = next(
            (int(idx) for idx, cfg in profile.current_buttons().items() if cfg.label.strip().casefold() == needle),
            None,
        )
        if match is None:
            raise ActionError(f"No button with label '{label}'.")
        index = match
    else:
        if button is None:
            raise ActionError("Provide button number or label.")
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
        if should_persist:
            save_profile_by_id(MCP_PROFILE_ID, profile)
        return f"Switched page: {profile.page_names.get(config.target, config.target)}"
    return run_action(config)


def switch_page(page: str, profile: Profile | None = None) -> str:
    should_persist = profile is None
    if profile is None:
        profile = load_profile_by_id(MCP_PROFILE_ID)
    if page in profile.pages:
        page_id = page
    else:
        needle = page.strip().casefold()
        page_id = next(
            (pid for pid, name in profile.page_names.items() if name.strip().casefold() == needle),
            None,
        )
        if page_id is None:
            available = ", ".join(f"{pid!r} ({name!r})" for pid, name in profile.page_names.items())
            raise ActionError(f"No page matching '{page}'. Available: {available}")
    profile.set_current_page(page_id)
    if should_persist:
        save_profile_by_id(MCP_PROFILE_ID, profile)
    return f"Switched page: {profile.page_names.get(page_id, page_id)}"


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
                "serverInfo": {"name": "cozmik-studio", "version": "0.1.1"},
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
        raw_button = arguments.get("button")
        raw_label = arguments.get("label")
        payload = {"message": activate_button(
            button=int(raw_button) if raw_button is not None else None,
            label=str(raw_label) if raw_label is not None else None,
        )}
    elif name == "switch_page":
        payload = {"message": switch_page(str(arguments.get("page", "")))}
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
            "name": "switch_page",
            "description": "Switch the current MCP Deck page by page ID or page name. Use get_profile to see available pages.",
            "inputSchema": {
                "type": "object",
                "properties": {"page": {"type": "string"}},
                "required": ["page"],
                "additionalProperties": False,
            },
        },
        {
            "name": "activate_button",
            "description": "Activate a configured MCP Deck button by 1-based number or label. Provide exactly one of button or label.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "button": {"type": "integer", "minimum": 1},
                    "label": {"type": "string"},
                },
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
