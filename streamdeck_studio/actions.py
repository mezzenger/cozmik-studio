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


MAC_APP_LAUNCHERS = {
    "Amazon Kindle": (("kindle",), ()),
    "Books": (("foliate", "gnome-books"), ()),
    "Calculator": (("gnome-calculator", "kcalc"), ("org.gnome.Calculator.desktop",)),
    "Elgato Stream Deck": (("streamdeck-studio",), ("streamdeck-studio.desktop",)),
    "FaceTime": ((), ()),
    "Google Chrome": (("google-chrome", "google-chrome-stable", "chromium", "firefox"), ("google-chrome.desktop", "chromium.desktop", "firefox.desktop")),
    "Joplin": (("joplin",), ("joplin.desktop", "net.cozic.joplin_desktop.desktop")),
    "LibreOffice": (("libreoffice",), ("libreoffice-startcenter.desktop",)),
    "Mail": (("evolution", "thunderbird"), ("org.gnome.Evolution.desktop", "thunderbird.desktop")),
    "Messages": ((), ()),
    "Messenger": (("caprine",), ("caprine.desktop",)),
    "Microsoft Excel": (("libreoffice", "--calc"), ("libreoffice-calc.desktop",)),
    "Microsoft Word": (("libreoffice", "--writer"), ("libreoffice-writer.desktop",)),
    "Photo Booth": (("cheese", "gnome-snapshot"), ("org.gnome.Snapshot.desktop", "org.gnome.Cheese.desktop")),
    "Screenshot": (("gnome-screenshot",), ("org.gnome.Screenshot.desktop",)),
    "Spotify": (("spotify",), ("spotify.desktop", "spotify-launcher.desktop")),
    "System Settings": (("gnome-control-center",), ("org.gnome.Settings.desktop",)),
}

COMMAND_ALIASES = {
    "calculator": ("gnome-calculator",),
    "settings": ("gnome-control-center",),
}

_YDOTOOL_KEYS = {
    "ctrl": 29,
    "control": 29,
    "alt": 56,
    "shift": 42,
    "super": 125,
    "cmd": 125,
    "meta": 125,
    "r": 19,
    "period": 52,
    ".": 52,
    "semicolon": 39,
    ";": 39,
    "print": 99,
}

_WTYPE_MODIFIERS = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "alt": "alt",
    "shift": "shift",
    "super": "logo",
    "cmd": "logo",
    "meta": "logo",
}

_WTYPE_KEYS = {
    "period": ".",
    "semicolon": ";",
}

_XDOTOOL_KEYS = {
    "period": "period",
    ".": "period",
    "semicolon": "semicolon",
    ";": "semicolon",
    "print": "Print",
    "super": "Super",
    "cmd": "Super",
    "meta": "Super",
}


def run_action(config: ButtonConfig, copy_text: Callable[[str], None] | None = None, paste: Callable[[], None] | None = None) -> str:
    action_type = config.action_type
    target = config.target.strip()

    if action_type == "none":
        return "No action configured."
    if action_type == "page":
        return "Switched page."
    if action_type == "media":
        return _run_media_action(target)
    if action_type == "shortcut":
        return _run_shortcut_action(target)
    if not target:
        raise ActionError("The selected button has no target.")
    if action_type == "command":
        try:
            args = shlex.split(target)
        except ValueError as exc:
            raise ActionError(f"Invalid command: {exc}") from exc
        if not args:
            raise ActionError("The selected button has no command.")
        args = list(_translated_command(args))
        subprocess.Popen(args, start_new_session=True)
        return f"Started command: {target}"
    if action_type == "shell":
        subprocess.Popen(target, shell=True, start_new_session=True)
        return f"Started shell command: {target}"
    if action_type == "url":
        url = _normalized_url(target)
        if not webbrowser.open(url, new=2):
            raise ActionError(f"Could not open URL: {url}")
        return f"Opened URL: {url}"
    if action_type == "file":
        translated = _translated_launcher(target)
        if translated:
            subprocess.Popen(translated, start_new_session=True)
            return f"Started: {' '.join(translated)}"
        path = Path(os.path.expanduser(target))
        if not path.exists():
            mac_app = _mac_app_name(target)
            if mac_app:
                raise ActionError(f"No Linux launcher found for macOS app: {mac_app}.")
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


def _run_media_action(target: str) -> str:
    if target == "volume-mute":
        commands = (
            ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "toggle"),
            ("pactl", "set-sink-mute", "@DEFAULT_SINK@", "toggle"),
            ("amixer", "set", "Master", "toggle"),
        )
    elif target == "volume-down":
        commands = (
            ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%-"),
            ("pactl", "set-sink-volume", "@DEFAULT_SINK@", "-5%"),
            ("amixer", "set", "Master", "5%-"),
        )
    elif target == "volume-up":
        commands = (
            ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "5%+"),
            ("pactl", "set-sink-volume", "@DEFAULT_SINK@", "+5%"),
            ("amixer", "set", "Master", "5%+"),
        )
    else:
        raise ActionError(f"Unsupported media action: {target}")
    for command in commands:
        executable = shutil.which(command[0])
        if executable:
            subprocess.Popen([executable, *command[1:]], start_new_session=True)
            return f"Ran media action: {target}"
    raise ActionError("No audio control helper found. Install wireplumber, pulseaudio-utils, or alsa-utils.")


def _run_shortcut_action(target: str) -> str:
    keys = _parse_shortcut(target)
    if not keys:
        raise ActionError("The selected shortcut has no target.")
    if _send_shortcut_with_ydotool(keys) or _send_shortcut_with_wtype(keys) or _send_shortcut_with_xdotool(keys):
        return f"Sent shortcut: {target}"
    raise ActionError("No keyboard helper found. Install ydotool, wtype, or xdotool.")


def _parse_shortcut(target: str) -> list[str]:
    return [part.strip().lower() for part in target.replace(" ", "").split("+") if part.strip()]


def _send_shortcut_with_ydotool(keys: list[str]) -> bool:
    executable = shutil.which("ydotool")
    codes = [_YDOTOOL_KEYS.get(key) for key in keys]
    if not executable or any(code is None for code in codes):
        return False
    down = [f"{code}:1" for code in codes]
    up = [f"{code}:0" for code in reversed(codes)]
    subprocess.run([executable, "key", *down, *up], check=True, env=_paste_env("ydotool"))
    return True


def _send_shortcut_with_wtype(keys: list[str]) -> bool:
    executable = shutil.which("wtype")
    if not executable:
        return False
    modifiers = [key for key in keys[:-1] if key in _WTYPE_MODIFIERS]
    key = _WTYPE_KEYS.get(keys[-1], keys[-1])
    if len(modifiers) != len(keys) - 1 or len(key) != 1:
        return False
    args = [executable]
    for modifier in modifiers:
        args.extend(("-M", _WTYPE_MODIFIERS[modifier]))
    args.append(key)
    for modifier in reversed(modifiers):
        args.extend(("-m", _WTYPE_MODIFIERS[modifier]))
    subprocess.run(args, check=True)
    return True


def _send_shortcut_with_xdotool(keys: list[str]) -> bool:
    executable = shutil.which("xdotool")
    if not executable:
        return False
    shortcut = "+".join(_XDOTOOL_KEYS.get(key, key) for key in keys)
    subprocess.run([executable, "key", shortcut], check=True)
    return True


def _translated_launcher(target: str) -> list[str]:
    app_name = _mac_app_name(target)
    if not app_name:
        return []
    commands, desktop_files = MAC_APP_LAUNCHERS.get(app_name, ((), ()))
    for desktop_file in desktop_files:
        if _desktop_file_exists(desktop_file):
            gio = shutil.which("gio")
            if gio:
                return [gio, "launch", desktop_file]
    command = _first_available_command(commands)
    return list(command) if command else []


def _translated_command(args: list[str]) -> tuple[str, ...]:
    alias = COMMAND_ALIASES.get(args[0])
    if not alias:
        return tuple(args)
    command = _first_available_command(alias)
    if not command:
        return tuple(args)
    return (*command, *args[1:])


def _normalized_url(target: str) -> str:
    if "://" in target:
        return target
    if target.startswith(("mailto:", "tel:")):
        return target
    return f"https://{target}"


def _mac_app_name(target: str) -> str:
    path = target.strip().strip('"')
    if not path.endswith(".app"):
        return ""
    name = Path(path).name.removesuffix(".app")
    return name.strip()


def _first_available_command(commands: tuple[str, ...]) -> tuple[str, ...]:
    index = 0
    while index < len(commands):
        command = commands[index]
        if shutil.which(command):
            return tuple(commands[index:])
        index += 1
    return ()


def _desktop_file_exists(name: str) -> bool:
    for base in (Path.home() / ".local/share/applications", Path("/usr/share/applications")):
        if (base / name).exists():
            return True
    return False


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
