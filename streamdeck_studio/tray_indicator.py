from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("AyatanaAppIndicator3", "0.1")

from gi.repository import AyatanaAppIndicator3, GLib, Gtk


APP_ID = "dev.local.CozmikStudio.tray"
ICON_NAME = "cozmik-studio"


def main() -> int:
    if len(sys.argv) == 2 and sys.argv[1] == "--check":
        return 0
    if len(sys.argv) != 3:
        return 2
    try:
        parent_pid = int(sys.argv[1])
    except ValueError:
        return 2
    socket_path = Path(sys.argv[2])

    indicator = AyatanaAppIndicator3.Indicator.new(
        APP_ID,
        ICON_NAME,
        AyatanaAppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AyatanaAppIndicator3.IndicatorStatus.ACTIVE)
    indicator.set_title("Cozmik Studio")
    indicator.set_menu(_menu(socket_path))

    GLib.timeout_add_seconds(3, _parent_is_running, parent_pid)
    Gtk.main()
    return 0


def _menu(socket_path: Path) -> Gtk.Menu:
    menu = Gtk.Menu()
    for label, command in (
        ("Show Cozmik Studio", "show"),
        ("Hide Cozmik Studio", "hide"),
        ("Quit", "quit"),
    ):
        item = Gtk.MenuItem(label=label)
        item.connect("activate", lambda _item, cmd=command: _send_command(socket_path, cmd))
        menu.append(item)
    menu.show_all()
    return menu


def _send_command(socket_path: Path, command: str) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(socket_path))
            client.sendall(command.encode("utf-8"))
    except OSError:
        Gtk.main_quit()


def _parent_is_running(parent_pid: int) -> bool:
    try:
        os.kill(parent_pid, 0)
    except OSError:
        Gtk.main_quit()
        return False
    return True


if __name__ == "__main__":
    raise SystemExit(main())
