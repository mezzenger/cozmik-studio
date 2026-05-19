from __future__ import annotations

import json
import sys
from typing import Any
from urllib import error, request


class HelperError(RuntimeError):
    pass


def home_assistant_call_service(settings: dict[str, Any]) -> str:
    base_url = str(settings.get("base_url", "")).rstrip("/")
    token = str(settings.get("token", ""))
    domain = str(settings.get("domain", ""))
    service = str(settings.get("service", "toggle"))
    entity_id = str(settings.get("entity_id", ""))
    if not base_url or not token or not domain or not service or not entity_id:
        raise HelperError("Home Assistant settings require base_url, token, domain, service, and entity_id.")
    payload = dict(settings.get("data", {}) or {})
    payload.setdefault("entity_id", entity_id)
    _home_assistant_service_request(base_url, token, domain, service, payload)
    return f"Called Home Assistant service: {domain}.{service} {entity_id}"


def _home_assistant_service_request(base_url: str, token: str, domain: str, service: str, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{base_url}/api/services/{domain}/{service}",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=5) as response:
            response.read()
    except error.HTTPError as exc:
        raise HelperError(f"Home Assistant returned HTTP {exc.code}.") from exc
    except OSError as exc:
        raise HelperError(f"Could not reach Home Assistant: {exc}") from exc


def _settings_from_arg(raw: str) -> dict[str, Any]:
    try:
        settings = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise HelperError(f"Invalid settings JSON: {exc.msg}") from exc
    if not isinstance(settings, dict):
        raise HelperError("Settings JSON must be an object.")
    return settings


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    handlers = {
        "home-assistant-call-service": home_assistant_call_service,
    }
    if len(args) != 2 or args[0] not in handlers:
        print("Usage: python3 -m streamdeck_studio.plugin_helpers HELPER SETTINGS_JSON", file=sys.stderr)
        return 2
    try:
        print(handlers[args[0]](_settings_from_arg(args[1])))
    except HelperError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
