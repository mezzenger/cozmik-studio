from __future__ import annotations

import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import time
import webbrowser
from collections.abc import Callable

from .model import ButtonConfig
from .plugins import PluginError, command_for_action, get_plugin_action, load_plugin_config, parse_plugin_target


class ActionError(RuntimeError):
    pass


MAC_APP_LAUNCHERS = {
    "Amazon Kindle": (("kindle",), ()),
    "Books": (("foliate", "gnome-books"), ()),
    "Calculator": (("gnome-calculator", "kcalc"), ("org.gnome.Calculator.desktop",)),
    "Elgato Stream Deck": (
        ("cozmik-studio", "streamdeck-studio"),
        ("dev.local.CozmikStudio.desktop", "cozmik-studio.desktop", "streamdeck-studio.desktop"),
    ),
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
    "leftctrl": 29,
    "rightctrl": 97,
    "alt": 56,
    "leftalt": 56,
    "rightalt": 100,
    "shift": 42,
    "leftshift": 42,
    "rightshift": 54,
    "super": 125,
    "leftmeta": 125,
    "rightmeta": 126,
    "cmd": 125,
    "meta": 125,
    "r": 19,
    "period": 52,
    ".": 52,
    "semicolon": 39,
    ";": 39,
    "print": 99,
}

_BUILTIN_EVDEV_KEY_CODES = {
    "esc": 1,
    "1": 2,
    "2": 3,
    "3": 4,
    "4": 5,
    "5": 6,
    "6": 7,
    "7": 8,
    "8": 9,
    "9": 10,
    "0": 11,
    "minus": 12,
    "equal": 13,
    "backspace": 14,
    "tab": 15,
    "q": 16,
    "w": 17,
    "e": 18,
    "r": 19,
    "t": 20,
    "y": 21,
    "u": 22,
    "i": 23,
    "o": 24,
    "p": 25,
    "leftbrace": 26,
    "rightbrace": 27,
    "enter": 28,
    "leftctrl": 29,
    "a": 30,
    "s": 31,
    "d": 32,
    "f": 33,
    "g": 34,
    "h": 35,
    "j": 36,
    "k": 37,
    "l": 38,
    "semicolon": 39,
    "apostrophe": 40,
    "grave": 41,
    "leftshift": 42,
    "backslash": 43,
    "z": 44,
    "x": 45,
    "c": 46,
    "v": 47,
    "b": 48,
    "n": 49,
    "m": 50,
    "comma": 51,
    "dot": 52,
    "slash": 53,
    "rightshift": 54,
    "kpasterisk": 55,
    "leftalt": 56,
    "space": 57,
    "capslock": 58,
    "f1": 59,
    "f2": 60,
    "f3": 61,
    "f4": 62,
    "f5": 63,
    "f6": 64,
    "f7": 65,
    "f8": 66,
    "f9": 67,
    "f10": 68,
    "numlock": 69,
    "scrolllock": 70,
    "kp7": 71,
    "kp8": 72,
    "kp9": 73,
    "kpminus": 74,
    "kp4": 75,
    "kp5": 76,
    "kp6": 77,
    "kpplus": 78,
    "kp1": 79,
    "kp2": 80,
    "kp3": 81,
    "kp0": 82,
    "kpdot": 83,
    "f11": 87,
    "f12": 88,
    "kpenter": 96,
    "rightctrl": 97,
    "kpslash": 98,
    "sysrq": 99,
    "rightalt": 100,
    "home": 102,
    "up": 103,
    "pageup": 104,
    "left": 105,
    "right": 106,
    "end": 107,
    "down": 108,
    "pagedown": 109,
    "insert": 110,
    "delete": 111,
    "leftmeta": 125,
    "rightmeta": 126,
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
    if action_type == "tutorial":
        return "Opened tutorial."
    if action_type == "media":
        return _run_media_action(target)
    if action_type == "shortcut":
        return _run_shortcut_action(target)
    if action_type == "keys":
        return _run_key_press_action(target, "key presses")
    if not target:
        raise ActionError("The selected button has no target.")
    if action_type == "plugin":
        return _run_plugin_action(target)
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


def _run_plugin_action(target: str) -> str:
    try:
        plugin_id, action_id, settings = parse_plugin_target(target)
    except PluginError as exc:
        raise ActionError(str(exc)) from exc
    action = get_plugin_action(plugin_id, action_id)
    if not action:
        raise ActionError(f"Plugin action not found: {plugin_id}.{action_id}")
    merged_settings = {**load_plugin_config(plugin_id), **settings}
    command = command_for_action(action, merged_settings)
    try:
        if action.shell:
            if isinstance(command, list):
                command = " ".join(shlex.quote(part) for part in command)
            subprocess.Popen(command, shell=True, cwd=action.plugin_dir, start_new_session=True)
        else:
            args = shlex.split(command) if isinstance(command, str) else command
            if not args:
                raise ActionError(f"Plugin action has no command: {action.qualified_id}")
            subprocess.Popen(args, cwd=action.plugin_dir, start_new_session=True)
    except OSError as exc:
        raise ActionError(f"Plugin action failed: {exc}") from exc
    return f"Ran plugin action: {action.plugin_name} / {action.label}"


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


def _run_key_press_action(target: str, description: str) -> str:
    steps = _parse_key_press_script(target)
    if not steps:
        raise ActionError(f"The selected {description} action has no target.")
    if _send_key_press_steps_with_ydotool(steps) or _send_key_press_steps_with_xdotool(steps):
        return f"Sent {description}: {target}"
    raise ActionError("No keyboard helper found. Install ydotool or xdotool.")


def _run_shortcut_action(target: str) -> str:
    keys = _parse_shortcut(target)
    if not keys:
        raise ActionError("The selected shortcut has no target.")
    if _send_shortcut_with_ydotool(keys) or _send_shortcut_with_wtype(keys) or _send_shortcut_with_xdotool(keys):
        return f"Sent shortcut: {target}"
    raise ActionError("No keyboard helper found. Install ydotool, wtype, or xdotool.")


def _parse_shortcut(target: str) -> list[str]:
    return [part.strip().lower() for part in target.replace(" ", "").split("+") if part.strip()]


def _parse_key_press_script(target: str) -> list[tuple[str, list[str] | float]]:
    steps: list[tuple[str, list[str] | float]] = []
    for raw_group in target.split(","):
        group = raw_group.strip()
        if not group:
            continue
        keys: list[str] = []
        held_keys: list[str] = []
        for raw_token in group.split("+"):
            token = raw_token.strip().lower()
            if not token:
                continue
            delay = _parse_delay_token(token)
            if delay is not None:
                if keys:
                    steps.append(("down", keys.copy()))
                    held_keys.extend(keys)
                    keys.clear()
                steps.append(("delay", delay))
                continue
            keys.extend(_key_aliases(token))
        if keys:
            steps.append(("tap", keys))
        if held_keys:
            steps.append(("up", held_keys))
    return steps


def _parse_delay_token(token: str) -> float | None:
    if token == "delay":
        return 0.5
    if not token.startswith("delay "):
        return None
    try:
        delay = float(token.split(None, 1)[1])
    except ValueError:
        return 0.0
    return max(0.0, delay)


def _key_aliases(key: str) -> list[str]:
    aliases = {
        "control": ["leftctrl"],
        "ctrl": ["leftctrl"],
        "alt": ["leftalt"],
        "shift": ["leftshift"],
        "super": ["leftmeta"],
        "cmd": ["leftmeta"],
        "meta": ["leftmeta"],
        "win": ["leftmeta"],
        "windows": ["leftmeta"],
        "return": ["enter"],
        "esc": ["escape"],
        "escape": ["esc"],
        "spacebar": ["space"],
        "plus": ["kpplus"],
        "+": ["kpplus"],
        "comma": ["comma"],
        ",": ["comma"],
        "numpad_divide": ["kpslash"],
        "numpad_multiply": ["kpasterisk"],
        "numpad_minus": ["kpminus"],
        "numpad_plus": ["kpplus"],
        "numpad_enter": ["kpenter"],
        "numpad_decimal": ["kpdot"],
        "numpad_0": ["kp0"],
        "numpad_1": ["kp1"],
        "numpad_2": ["kp2"],
        "numpad_3": ["kp3"],
        "numpad_4": ["kp4"],
        "numpad_5": ["kp5"],
        "numpad_6": ["kp6"],
        "numpad_7": ["kp7"],
        "numpad_8": ["kp8"],
        "numpad_9": ["kp9"],
        "\"": ["leftshift", "apostrophe"],
    }
    return aliases.get(key, [key])


def _send_key_press_steps_with_ydotool(steps: list[tuple[str, list[str] | float]]) -> bool:
    executable = shutil.which("ydotool")
    if not executable:
        return False
    key_codes = _evdev_key_codes()
    pressed: list[int] = []
    command: list[str] = [executable, "key"]
    try:
        for operation, payload in steps:
            if operation == "delay":
                if len(command) > 2:
                    subprocess.run(command, check=True, env=_paste_env("ydotool"))
                    command = [executable, "key"]
                time.sleep(float(payload))
                continue
            codes = [_key_code_for_ydotool(key, key_codes) for key in payload]  # type: ignore[arg-type]
            if any(code is None for code in codes):
                _release_ydotool_keys(executable, pressed)
                return False
            typed_codes = [int(code) for code in codes if code is not None]
            if operation == "down":
                command.extend(f"{code}:1" for code in typed_codes)
                pressed.extend(typed_codes)
            elif operation == "up":
                command.extend(f"{code}:0" for code in reversed(typed_codes))
                for code in typed_codes:
                    if code in pressed:
                        pressed.remove(code)
            else:
                command.extend(f"{code}:1" for code in typed_codes)
                command.extend(f"{code}:0" for code in reversed(typed_codes))
        command.extend(_release_events(pressed))
        if len(command) > 2:
            subprocess.run(command, check=True, env=_paste_env("ydotool"))
    except (OSError, subprocess.CalledProcessError):
        _release_ydotool_keys(executable, pressed)
        return False
    return True


def _release_ydotool_keys(executable: str, codes: list[int]) -> None:
    releases = _release_events(codes)
    if releases:
        try:
            subprocess.run([executable, "key", *releases], check=True, env=_paste_env("ydotool"))
        except (OSError, subprocess.CalledProcessError):
            pass


def _release_events(codes: list[int]) -> list[str]:
    return [f"{code}:0" for code in reversed(codes)]


def _key_code_for_ydotool(key: str, key_codes: dict[str, int]) -> int | None:
    legacy = _YDOTOOL_KEYS.get(key)
    if legacy is not None:
        return legacy
    return key_codes.get(key.lower().replace("-", "_"))


def _evdev_key_codes() -> dict[str, int]:
    aliases = {
        "escape": "esc",
        "return": "enter",
        "period": "dot",
        ".": "dot",
        "print": "sysrq",
    }
    codes: dict[str, int] = dict(_BUILTIN_EVDEV_KEY_CODES)
    header = Path("/usr/include/linux/input-event-codes.h")
    try:
        text = header.read_text(encoding="utf-8")
    except OSError:
        text = ""
    for name, value in re.findall(r"^#define\s+KEY_([A-Z0-9_]+)\s+(0x[0-9a-fA-F]+|\d+)\b", text, re.MULTILINE):
        key = name.lower()
        codes[key] = int(value, 0)
    for alias, canonical in aliases.items():
        if canonical in codes:
            codes[alias] = codes[canonical]
    return codes


def _send_key_press_steps_with_xdotool(steps: list[tuple[str, list[str] | float]]) -> bool:
    executable = shutil.which("xdotool")
    if not executable:
        return False
    for operation, payload in steps:
        if operation == "delay":
            time.sleep(float(payload))
            continue
        shortcut = "+".join(_key_name_for_xdotool(key) for key in payload)  # type: ignore[arg-type]
        if operation == "down":
            subprocess.run([executable, "keydown", shortcut], check=True)
        elif operation == "up":
            subprocess.run([executable, "keyup", shortcut], check=True)
        else:
            subprocess.run([executable, "key", shortcut], check=True)
    return True


def _key_name_for_xdotool(key: str) -> str:
    aliases = {
        "leftctrl": "ctrl",
        "leftalt": "alt",
        "leftshift": "shift",
        "leftmeta": "Super",
        "esc": "Escape",
        "kpplus": "KP_Add",
        "kpslash": "KP_Divide",
        "kpasterisk": "KP_Multiply",
        "kpminus": "KP_Subtract",
        "kpenter": "KP_Enter",
        "kpdot": "KP_Decimal",
        "capslock": "Caps_Lock",
    }
    if key in aliases:
        return aliases[key]
    if key.startswith("kp") and key[2:].isdigit():
        return f"KP_{key[2:]}"
    return _XDOTOOL_KEYS.get(key, key)


def _send_shortcut_with_ydotool(keys: list[str]) -> bool:
    executable = shutil.which("ydotool")
    key_codes = _evdev_key_codes()
    codes = [_key_code_for_ydotool(key, key_codes) for key in keys]
    if not executable or any(code is None for code in codes):
        return False
    typed_codes = [int(code) for code in codes if code is not None]
    down = [f"{code}:1" for code in typed_codes]
    up = [f"{code}:0" for code in reversed(typed_codes)]
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
