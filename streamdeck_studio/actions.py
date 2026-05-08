from __future__ import annotations

import os
from pathlib import Path
import shutil
import shlex
import subprocess
import time
import webbrowser
from collections.abc import Callable

from .model import ButtonConfig


class ActionError(RuntimeError):
    pass


def run_action(config: ButtonConfig, copy_text: Callable[[str], None] | None = None, paste: Callable[[], None] | None = None) -> str:
    action_type = config.action_type
    target = config.target.strip()

    if action_type == "none":
        return "No action configured."
    if action_type == "page":
        return "Switched page."
    if not target:
        raise ActionError("The selected button has no target.")
    if action_type == "command":
        try:
            args = shlex.split(target)
        except ValueError as exc:
            raise ActionError(f"Invalid command: {exc}") from exc
        if not args:
            raise ActionError("The selected button has no command.")
        subprocess.Popen(args, start_new_session=True)
        return f"Started command: {target}"
    if action_type == "shell":
        subprocess.Popen(target, shell=True, start_new_session=True)
        return f"Started shell command: {target}"
    if action_type == "url":
        if not webbrowser.open(target, new=2):
            raise ActionError(f"Could not open URL: {target}")
        return f"Opened URL: {target}"
    if action_type == "file":
        path = Path(os.path.expanduser(target))
        if not path.exists():
            raise ActionError(f"Path does not exist: {path}")
        opener = shutil.which("xdg-open")
        if not opener:
            raise ActionError("xdg-open is not installed.")
        subprocess.Popen([opener, str(path)], start_new_session=True)
        return f"Opened: {path}"
    if action_type == "text":
        copy_text_action(config, copy_text=copy_text)
        time.sleep(0.08)
        return paste_text_action(config, paste=paste)

    raise ActionError(f"Unsupported action type: {action_type}")


def copy_text_action(config: ButtonConfig, copy_text: Callable[[str], None] | None = None) -> str:
    target = config.target.strip()
    if config.action_type != "text":
        raise ActionError("The selected button is not a text action.")
    if not target:
        raise ActionError("The selected text button has no target.")
    if copy_text:
        copy_text(target)
    else:
        _copy_text_with_cli(target)
    return "Copied text."


def paste_text_action(config: ButtonConfig, paste: Callable[[], None] | None = None) -> str:
    if config.action_type != "text":
        raise ActionError("The selected button is not a text action.")
    if paste:
        paste()
    else:
        _paste_with_cli()
    return "Pasted text."


def _copy_text_with_cli(text: str) -> None:
    for command in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        executable = shutil.which(command[0])
        if not executable:
            continue
        subprocess.run([executable, *command[1:]], input=text, text=True, check=True)
        return
    raise ActionError("No clipboard helper found. Install wl-clipboard, xclip, or xsel.")


def _paste_with_cli() -> None:
    time.sleep(0.05)
    commands = (
        ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],
        ["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
        ["xdotool", "key", "ctrl+v"],
    )
    for command in commands:
        executable = shutil.which(command[0])
        if not executable:
            continue
        subprocess.run([executable, *command[1:]], check=True, env=_paste_env(command[0]))
        return
    raise ActionError("Text was copied, but paste needs ydotoold running. Try: systemctl --user enable --now ydotool.service")


def _paste_env(tool: str) -> dict[str, str] | None:
    if tool != "ydotool":
        return None
    env = os.environ.copy()
    socket = Path(f"/run/user/{os.getuid()}/.ydotool_socket")
    if socket.exists():
        env.setdefault("YDOTOOL_SOCKET", str(socket))
    return env
