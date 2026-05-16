from __future__ import annotations

from datetime import datetime
from typing import Any
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, GObject, Gtk

from . import __app_name__
from .action_icons import action_icons
from .actions import ActionError, copy_text_action, paste_text_action, run_action
from .deck import StreamDeckController
from .diagnostics import profile_diagnostics, redact_target
from .images import render_button_image
from .importers import ImportProfileError, import_profile
from .model import (
    ACTION_TYPES,
    LABEL_POSITIONS,
    MCP_PROFILE_ID,
    MCP_PROFILE_NAME,
    NEW_PROFILE_NAME,
    Profile,
    TUTORIAL_TARGET_PREFIX,
    config_dir,
    create_default_icon_profile,
    delete_profile_by_id,
    ensure_mcp_profile,
    list_profile_ids,
    load_active_profile,
    load_default_profile_id,
    load_profile_by_id,
    profile_id_from_name,
    profile_action_icons_dir,
    profile_is_saved,
    profile_name_exists,
    next_profile_name,
    save_active_profile_id,
    save_default_profile_id,
    save_profile,
    save_profile_by_id,
)


_BRANDING_DIR = Path(__file__).parent / "resources" / "branding"
_BRAND_BANNER_PATH = _BRANDING_DIR / "cozmik-studio-banner.png"


class KeyButton(Gtk.Button):
    def __init__(self, index: int, on_clicked, on_dropped) -> None:
        super().__init__()
        self.index = index
        self.add_css_class("key-button")
        self.set_size_request(96, 96)
        self.connect("clicked", lambda *_args: on_clicked(index))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(6)
        box.set_margin_bottom(6)
        box.set_margin_start(6)
        box.set_margin_end(6)
        self.image = Gtk.Image()
        self.image.set_pixel_size(66)
        self.label = Gtk.Label()
        self.label.set_ellipsize(3)
        self.label.set_max_width_chars(12)
        self.label.add_css_class("key-label")
        box.append(self.image)
        box.append(self.label)
        self.set_child(box)

        drag_source = Gtk.DragSource.new()
        drag_source.set_actions(Gdk.DragAction.MOVE)
        drag_source.connect("prepare", self._prepare_drag)
        drag_source.connect("drag-begin", lambda *_args: self.add_css_class("drag-source"))
        drag_source.connect("drag-end", lambda *_args: self.remove_css_class("drag-source"))
        self.add_controller(drag_source)

        drop_target = Gtk.DropTarget.new(GObject.TYPE_STRING, Gdk.DragAction.MOVE)
        drop_target.connect("enter", self._drop_enter)
        drop_target.connect("leave", lambda *_args: self.remove_css_class("drop-target"))
        drop_target.connect("drop", lambda _target, value, _x, _y: self._drop(value, on_dropped))
        self.add_controller(drop_target)

    def set_preview(self, pixbuf: GdkPixbuf.Pixbuf, label: str) -> None:
        self.image.set_from_pixbuf(pixbuf)
        self.label.set_text(label)
        self.set_tooltip_text(label)

    def _prepare_drag(self, _source, _x: float, _y: float):
        return Gdk.ContentProvider.new_for_value(str(self.index))

    def _drop_enter(self, _target, _x: float, _y: float) -> Gdk.DragAction:
        self.add_css_class("drop-target")
        return Gdk.DragAction.MOVE

    def _drop(self, value: str, on_dropped) -> bool:
        self.remove_css_class("drop-target")
        try:
            source_index = int(value)
        except (TypeError, ValueError):
            return False
        on_dropped(source_index, self.index)
        return True


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title=__app_name__)
        self.set_default_size(980, 640)

        self.startup_message = ""
        self.profile_id, self.profile = self._load_profile()
        self.default_profile_id = load_default_profile_id()
        self.deck = StreamDeckController()
        self.deck.on_key_event(lambda key, pressed: GLib.idle_add(self._log_key_event, key, pressed))
        self.deck.on_key_pressed(lambda key: GLib.idle_add(self._key_pressed, key))
        self.deck.on_key_released(lambda key: GLib.idle_add(self._run_index, key))
        self.deck.on_status_changed(lambda message: GLib.idle_add(self._set_status, message))
        self.selected_index = 0
        self.key_buttons: list[KeyButton] = []
        self._updating_editor = False
        self._suppress_release: set[int] = set()
        self._last_key_event = "No hardware key events yet."
        self._last_action = "No action run yet."
        self._last_import_report = "No import report yet."
        self._undo_stack: list[dict[str, Any]] = []
        self.diagnostics_window = None
        self.diagnostics_view = None
        self._force_quit = False
        self._tray_available = False
        self._tray_hold = False
        self._tray_process: subprocess.Popen | None = None
        self._tray_socket: socket.socket | None = None
        self._tray_socket_path: Path | None = None

        self._build_ui()
        self._start_tray_indicator()
        self._connect_deck()
        if self.startup_message:
            self._set_status(self.startup_message)

    def do_close_request(self):
        self._save_profile(silent=True)
        if self._tray_available and not self._force_quit:
            self._hide_to_tray()
            return True
        self._shutdown_tray_indicator()
        self._save_profile(silent=True)
        self.deck.close()
        return False

    def _build_ui(self) -> None:
        self._install_css()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        header = Adw.HeaderBar()
        root.append(header)
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        title_box.set_valign(Gtk.Align.CENTER)
        if _BRAND_BANNER_PATH.exists():
            brand = Gtk.Image()
            brand.set_from_pixbuf(GdkPixbuf.Pixbuf.new_from_file_at_scale(str(_BRAND_BANNER_PATH), 184, 76, True))
            brand.set_tooltip_text(__app_name__)
            title_box.append(brand)
        title = Adw.WindowTitle(title=__app_name__, subtitle="Button profiles and launchers")
        title_box.append(title)
        header.set_title_widget(title_box)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        content.set_margin_top(12)
        content.set_margin_bottom(12)
        content.set_margin_start(12)
        content.set_margin_end(12)
        root.append(content)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        left.set_hexpand(True)
        content.append(left)

        self.device_label = Gtk.Label(label="Offline editor", xalign=0)
        self.device_label.add_css_class("device-label")
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.set_hexpand(True)
        self.profile_combo.connect("changed", lambda *_args: self._profile_changed())
        profile_click = Gtk.GestureClick()
        profile_click.set_button(3)
        profile_click.connect("pressed", lambda *_args: self._show_profile_name_entry())
        self.profile_combo.add_controller(profile_click)
        self.profile_name_entry = Gtk.Entry(max_length=48)
        self.profile_name_entry.set_placeholder_text("Imported")
        self.profile_name_entry.connect("activate", lambda *_args: self._profile_name_changed())
        profile_name_focus = Gtk.EventControllerFocus()
        profile_name_focus.connect("leave", lambda *_args: self._profile_name_changed())
        self.profile_name_entry.add_controller(profile_name_focus)
        self.page_combo = Gtk.ComboBoxText()
        self.page_combo.set_hexpand(True)
        self.page_combo.connect("changed", lambda *_args: self._page_changed())
        root.insert_child_after(self._top_toolbar(), header)

        self.grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        left.append(self.grid)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        right.set_size_request(320, -1)
        content.append(right)

        editor = Gtk.Frame(label="Button")
        right.append(editor)
        form = Gtk.Grid(column_spacing=8, row_spacing=8)
        form.set_margin_top(10)
        form.set_margin_bottom(10)
        form.set_margin_start(10)
        form.set_margin_end(10)
        editor.set_child(form)

        self.index_label = Gtk.Label(label="1", xalign=0)
        self.label_entry = Gtk.Entry(max_length=48)
        self.subtitle_entry = Gtk.Entry(max_length=48)
        self.label_position_combo = Gtk.ComboBoxText()
        for position in LABEL_POSITIONS:
            self.label_position_combo.append_text(position)
        self.action_combo = Gtk.ComboBoxText()
        for action in ACTION_TYPES:
            self.action_combo.append_text(action)
        self.target_view = Gtk.TextView()
        self.target_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.target_view.set_size_request(-1, 78)
        self.background_button = Gtk.ColorButton()
        self.foreground_button = Gtk.ColorButton()
        self.background_image_entry = Gtk.Entry()
        self.action_image_entry = Gtk.Entry()

        self._attach_row(form, 0, "Number", self.index_label)
        self._attach_row(form, 1, "Label", self.label_entry)
        self._attach_row(form, 2, "Subtitle", self.subtitle_entry)
        self._attach_row(form, 3, "Label Position", self.label_position_combo)
        self._attach_row(form, 4, "Action", self.action_combo)
        self._attach_row(form, 5, "Target", self.target_view)

        target_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        browse = Gtk.Button(label="Browse")
        browse.connect("clicked", lambda *_args: self._browse_target())
        run = Gtk.Button(label="Run")
        run.connect("clicked", lambda *_args: self._run_selected())
        target_buttons.append(browse)
        target_buttons.append(run)
        form.attach(target_buttons, 1, 6, 1, 1)

        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        color_row.append(self.background_button)
        color_row.append(self.foreground_button)
        self._attach_row(form, 7, "Colors", color_row)

        self._attach_row(form, 8, "Background Image", self._image_row(self.background_image_entry, "background"))
        self._attach_row(form, 9, "Action Image", self._image_row(self.action_image_entry, "action"))

        self.status_label = Gtk.Label(xalign=0)
        self.status_label.add_css_class("status-label")
        root.append(self.status_label)

        self.label_entry.connect("changed", lambda *_args: self._editor_changed())
        self.subtitle_entry.connect("changed", lambda *_args: self._editor_changed())
        self.action_combo.connect("changed", lambda *_args: self._editor_changed())
        self.label_position_combo.connect("changed", lambda *_args: self._editor_changed())
        self.target_view.get_buffer().connect("changed", lambda *_args: self._editor_changed())
        self.background_button.connect("color-set", lambda *_args: self._color_changed())
        self.foreground_button.connect("color-set", lambda *_args: self._color_changed())
        self.background_image_entry.connect("changed", lambda *_args: self._editor_changed())
        self.action_image_entry.connect("changed", lambda *_args: self._editor_changed())

        self._rebuild_grid()
        self._refresh_profile_combo()
        self._refresh_page_combo()
        self._select_button(0)
        self._refresh_diagnostics()

    def _top_toolbar(self) -> Gtk.Box:
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("top-toolbar")
        bar.set_margin_top(10)
        bar.set_margin_start(12)
        bar.set_margin_end(12)

        status_group = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        status_group.set_hexpand(True)
        status_group.append(self.device_label)
        profile_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        profile_row.append(Gtk.Label(label="Profile", xalign=0))
        profile_row.append(self.profile_combo)
        profile_row.append(self.profile_name_entry)
        status_group.append(profile_row)
        page_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        page_row.append(Gtk.Label(label="Page", xalign=0))
        page_row.append(self.page_combo)
        status_group.append(page_row)
        bar.append(status_group)

        nav_group = self._toolbar_group()
        nav_group.append(self._icon_button("go-previous-symbolic", "Previous Page", self._previous_page))
        nav_group.append(self._icon_button("go-next-symbolic", "Next Page", self._next_page))
        nav_group.append(self._icon_button("list-add-symbolic", "New Profile", self._new_profile))
        nav_group.append(self._icon_button("help-about-symbolic", "New Tutorial Profile", self._new_tutorial_profile))
        nav_group.append(self._icon_button("user-trash-symbolic", "Delete Profile", self._delete_current_profile))
        nav_group.append(self._icon_button("view-refresh-symbolic", "Reconnect", self._connect_deck))
        bar.append(nav_group)

        edit_group = self._toolbar_group()
        self.undo_button = self._icon_button("edit-undo-symbolic", "Undo", self._undo)
        self.undo_button.set_sensitive(False)
        edit_group.append(self.undo_button)
        edit_group.append(self._icon_button("media-playback-start-symbolic", "Run", self._run_selected))
        edit_group.append(self._icon_button("edit-clear-symbolic", "Clear", self._clear_selected))
        edit_group.append(self._icon_button("document-save-symbolic", "Save", self._save_now))
        bar.append(edit_group)

        file_group = self._toolbar_group()
        file_group.append(self._icon_button("document-open-symbolic", "Import Profile", self._import_profile))
        file_group.append(self._icon_button("document-save-as-symbolic", "Export Profile", self._export_profile))
        file_group.append(self._icon_button("emblem-favorite-symbolic", "Make Default Profile", self._make_default_profile))
        self.mcp_toggle = self._toggle_button("MCP", self._mcp_toggled)
        file_group.append(self.mcp_toggle)
        file_group.append(self._icon_button("dialog-information-symbolic", "Diagnostics", self._show_diagnostics))
        bar.append(file_group)
        return bar

    def _toolbar_group(self) -> Gtk.Box:
        group = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        group.add_css_class("toolbar-group")
        return group

    def _icon_button(self, icon_name: str, tooltip: str, callback) -> Gtk.Button:
        button = Gtk.Button(icon_name=icon_name)
        button.add_css_class("toolbar-button")
        button.set_size_request(43, 32)
        button.set_tooltip_text(tooltip)
        button.connect("clicked", lambda *_args: callback())
        return button

    def _toggle_button(self, label: str, callback) -> Gtk.ToggleButton:
        button_label = Gtk.Label(label=label)
        button_label.add_css_class("file-button-label")
        button = Gtk.ToggleButton()
        button.set_child(button_label)
        button.add_css_class("toolbar-button")
        button.add_css_class("file-button")
        button.set_size_request(43, 32)
        button.set_tooltip_text(f"{label} profile")
        button.connect("toggled", lambda *_args: callback())
        return button

    def _attach_row(self, form: Gtk.Grid, row: int, label: str, widget: Gtk.Widget) -> None:
        form.attach(Gtk.Label(label=label, xalign=0), 0, row, 1, 1)
        widget.set_hexpand(True)
        form.attach(widget, 1, row, 1, 1)

    def _image_row(self, entry: Gtk.Entry, image_kind: str) -> Gtk.Box:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        entry.set_hexpand(True)
        row.append(entry)
        choose = Gtk.Button(label="Choose")
        choose.connect("clicked", lambda *_args, kind=image_kind: self._choose_button_image(kind))
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda *_args, target=entry: target.set_text(""))
        row.append(choose)
        row.append(clear)
        return row

    def _connect_deck(self) -> None:
        info = self.deck.connect_first()
        if info.connected:
            self._match_connected_deck_layout()
            self.device_label.set_text("Connected")
            self.profile.page_ids()
            self._rebuild_grid()
            self.deck.apply_profile(self.profile)
            self._save_profile(silent=True)
        else:
            self.device_label.set_text("Offline editor")
            if info.error:
                self._set_status(info.error)
        self._select_button(min(self.selected_index, self.profile.button_count() - 1))

    def _start_tray_indicator(self) -> None:
        if not _tray_indicator_available():
            self._set_status("Panel icon unavailable: install Ayatana AppIndicator and enable GNOME AppIndicator support.", "error")
            return
        try:
            sock, socket_path = self._create_tray_socket()
            self._tray_socket = sock
            self._tray_socket_path = socket_path
            thread = threading.Thread(target=self._tray_command_loop, daemon=True)
            thread.start()
            self._tray_process = subprocess.Popen(
                [sys.executable, "-m", "streamdeck_studio.tray_indicator", str(os.getpid()), str(socket_path)],
                start_new_session=True,
            )
        except OSError as exc:
            self._set_status(f"Panel icon unavailable: {exc}", "error")
            self._shutdown_tray_indicator()
            return
        self._tray_available = True
        if not self._tray_hold:
            self.get_application().hold()
            self._tray_hold = True

    def _create_tray_socket(self) -> tuple[socket.socket, Path]:
        runtime_dir = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
        socket_path = runtime_dir / f"cozmik-studio-{os.getpid()}.sock"
        socket_path.unlink(missing_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(socket_path))
        sock.listen(4)
        sock.settimeout(0.5)
        return sock, socket_path

    def _tray_command_loop(self) -> None:
        while True:
            sock = self._tray_socket
            if sock is None:
                return
            try:
                client, _address = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with client:
                try:
                    command = client.recv(64).decode("utf-8", errors="replace").strip()
                except OSError:
                    continue
            if command:
                GLib.idle_add(self._handle_tray_command, command)

    def _handle_tray_command(self, command: str) -> bool:
        if command == "show":
            self._show_from_tray()
        elif command == "hide":
            self._hide_to_tray()
        elif command == "quit":
            self._quit_from_tray()
        return False

    def _show_from_tray(self) -> None:
        self.set_visible(True)
        self.present()
        self._set_status("Cozmik Studio restored from panel.", "success")

    def _hide_to_tray(self) -> None:
        self.set_visible(False)
        self._set_status("Cozmik Studio is running in the panel.", "success")

    def _quit_from_tray(self) -> None:
        self._force_quit = True
        self._save_profile(silent=True)
        self.deck.close()
        self._shutdown_tray_indicator()
        self.get_application().quit()

    def _shutdown_tray_indicator(self) -> None:
        self._tray_available = False
        if self._tray_socket is not None:
            try:
                self._tray_socket.close()
            except OSError:
                pass
            self._tray_socket = None
        if self._tray_socket_path is not None:
            self._tray_socket_path.unlink(missing_ok=True)
            self._tray_socket_path = None
        if self._tray_process is not None and self._tray_process.poll() is None:
            self._tray_process.terminate()
        self._tray_process = None
        if self._tray_hold:
            self.get_application().release()
            self._tray_hold = False

    def _rebuild_grid(self) -> None:
        child = self.grid.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.grid.remove(child)
            child = next_child
        self.key_buttons.clear()
        for index in range(self.profile.button_count()):
            button = KeyButton(index, self._select_button, self._move_button)
            self.key_buttons.append(button)
            self.grid.attach(button, index % self.profile.columns, index // self.profile.columns, 1, 1)
        self._refresh_all_previews()

    def _move_button(self, source_index: int, target_index: int) -> None:
        if source_index == target_index:
            self._select_button(target_index)
            return
        if source_index < 0 or target_index < 0:
            return
        if source_index >= self.profile.button_count() or target_index >= self.profile.button_count():
            return
        self._push_undo()
        self.profile.swap_buttons(source_index, target_index)
        self._refresh_preview(source_index)
        self._refresh_preview(target_index)
        self._select_button(target_index)
        self.deck.apply_profile(self.profile)
        self._save_profile(silent=True)
        self._set_status(f"Moved button {source_index + 1} to {target_index + 1}.", "success")

    def _select_button(self, index: int) -> None:
        if index < 0 or index >= self.profile.button_count():
            return
        self.selected_index = index
        self._updating_editor = True
        for button in self.key_buttons:
            button.remove_css_class("selected")
            if button.index == index:
                button.add_css_class("selected")
        config = self.profile.get_button(index)
        self.index_label.set_text(str(index + 1))
        self._sync_profile_name_entry()
        self.label_entry.set_text(config.label)
        self.subtitle_entry.set_text(config.subtitle)
        self.label_position_combo.set_active(
            LABEL_POSITIONS.index(config.label_position) if config.label_position in LABEL_POSITIONS else 0
        )
        self.action_combo.set_active(ACTION_TYPES.index(config.action_type) if config.action_type in ACTION_TYPES else 0)
        self._set_text_view(config.target)
        self._set_color(self.background_button, config.background)
        self._set_color(self.foreground_button, config.foreground)
        self.background_image_entry.set_text(config.background_image_path)
        self.action_image_entry.set_text(config.action_image_path)
        self._updating_editor = False
        self._refresh_diagnostics()

    def _editor_changed(self) -> None:
        if not self.key_buttons or self._updating_editor:
            return
        self._push_undo()
        config = self.profile.get_button(self.selected_index)
        config.label = self.label_entry.get_text()
        config.subtitle = self.subtitle_entry.get_text()
        config.label_position = self.label_position_combo.get_active_text() or "bottom"
        config.action_type = self.action_combo.get_active_text() or "none"
        config.target = self._get_text_view()
        config.background = _rgba_to_hex(self.background_button.get_rgba())
        config.foreground = _rgba_to_hex(self.foreground_button.get_rgba())
        config.background_image_path = self.background_image_entry.get_text().strip()
        config.action_image_path = self.action_image_entry.get_text().strip()
        self._refresh_preview(self.selected_index)
        self.deck.apply_button(self.profile, self.selected_index)
        self._save_profile(silent=True)
        if self._is_unnamed_profile(self.profile):
            self._show_profile_name_entry()

    def _page_changed(self) -> None:
        if self._updating_editor:
            return
        active = self.page_combo.get_active_id()
        if not active or active == self.profile.current_page:
            return
        self.profile.set_current_page(active)
        self._rebuild_grid()
        self._select_button(0)
        self.deck.apply_profile(self.profile)
        self._save_profile(silent=True)
        self._set_status(f"Page: {self.profile.page_names.get(active, active)}")

    def _profile_changed(self) -> None:
        if self._updating_editor:
            return
        active = self.profile_combo.get_active_id()
        if not active or active == self.profile_id:
            return
        try:
            self._save_profile(silent=True)
            self.profile = load_profile_by_id(active)
            self.profile_id = active
            save_active_profile_id(active)
            layout_changed = self._match_connected_deck_layout()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._set_status(f"Could not switch profile: {exc}", "error")
            self._refresh_profile_combo()
            return
        self._undo_stack.clear()
        self._update_undo_state()
        self._refresh_page_combo()
        self._rebuild_grid()
        self._select_button(0)
        self.deck.apply_profile(self.profile)
        if layout_changed:
            self._save_profile(silent=True)
        self._set_status(f"Profile: {self.profile.name}", "success")
        self._refresh_diagnostics()

    def _match_connected_deck_layout(self) -> bool:
        if not self.deck.info.connected:
            return False
        if self.profile.rows == self.deck.info.rows and self.profile.columns == self.deck.info.columns:
            return False
        self.profile.set_layout(self.deck.info.rows, self.deck.info.columns)
        return True

    def _refresh_profile_combo(self) -> None:
        self._updating_editor = True
        self.profile_combo.remove_all()
        seen_active = False
        self.default_profile_id = load_default_profile_id()
        for profile_id in list_profile_ids():
            try:
                profile = load_profile_by_id(profile_id)
            except (OSError, json.JSONDecodeError, ValueError):
                continue
            self.profile_combo.append(profile_id, self._profile_display_name(profile_id, profile))
            seen_active = seen_active or profile_id == self.profile_id
        if not seen_active:
            self.profile_combo.append(self.profile_id, self._profile_display_name(self.profile_id, self.profile))
        self.profile_combo.set_active_id(self.profile_id)
        self._sync_profile_name_entry()
        self._updating_editor = False
        self._refresh_mcp_toggle()

    def _show_profile_name_entry(self) -> None:
        self.profile_name_entry.set_visible(True)
        self.profile_name_entry.grab_focus()
        self.profile_name_entry.set_position(-1)

    def _sync_profile_name_entry(self) -> None:
        if not hasattr(self, "profile_name_entry"):
            return
        is_placeholder = self._is_imported_placeholder(self.profile) or self._is_unnamed_profile(self.profile)
        self.profile_name_entry.set_text("" if is_placeholder else self.profile.name)
        self.profile_name_entry.set_visible(is_placeholder)

    def _profile_name_changed(self) -> None:
        if self._updating_editor:
            return
        name = self.profile_name_entry.get_text().strip()
        if not name:
            self._sync_profile_name_entry()
            return
        if name == self.profile.name:
            self.profile_name_entry.set_visible(False)
            return
        if profile_name_exists(name, exclude_profile_id=self.profile_id):
            self.profile_name_entry.set_text(self.profile.name if not self._is_unnamed_profile(self.profile) else "")
            self.profile_name_entry.set_visible(True)
            self.profile_name_entry.grab_focus()
            self._set_status(f"Profile name already exists: {name}. Delete that profile before reusing the name.", "error")
            return
        self.profile.name = name
        self._save_profile(silent=True)
        self._refresh_profile_combo()
        self.profile_name_entry.set_visible(False)
        self._set_status(f"Renamed profile: {name}", "success")

    def _new_profile(self) -> None:
        self._create_default_profile(next_profile_name(), show_name_entry=True)

    def _new_tutorial_profile(self) -> None:
        name = next_profile_name("Tutorial Profile")
        if self._create_default_profile(name, show_name_entry=False, page_id="tutorials"):
            self._set_status(f"Tutorial profile created: {name}", "success")

    def _create_default_profile(self, name: str, show_name_entry: bool, page_id: str = "main") -> bool:
        try:
            self._save_profile(silent=True)
            self.profile = create_default_icon_profile(name, self.profile.rows, self.profile.columns)
            self.profile_id = profile_id_from_name(name)
            if page_id in self.profile.pages:
                self.profile.set_current_page(page_id)
            save_profile_by_id(self.profile_id, self.profile)
            save_active_profile_id(self.profile_id)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._set_status(f"Could not create profile: {exc}", "error")
            return False
        self._undo_stack.clear()
        self._update_undo_state()
        self._refresh_profile_combo()
        self._refresh_page_combo()
        self._rebuild_grid()
        self._select_button(0)
        self.deck.apply_profile(self.profile)
        if show_name_entry:
            self._show_profile_name_entry()
            self._set_status("New profile created. Enter a profile name.", "success")
        self._refresh_diagnostics()
        return True

    def _delete_current_profile(self) -> None:
        dialog = Gtk.MessageDialog(
            transient_for=self,
            modal=True,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.CANCEL,
            text=f"Delete profile '{self._profile_display_name(self.profile_id, self.profile)}'?",
        )
        dialog.add_button("Delete", Gtk.ResponseType.ACCEPT)
        dialog.connect("response", self._on_delete_profile_response)
        dialog.present()

    def _on_delete_profile_response(self, dialog: Gtk.MessageDialog, response: int) -> None:
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT:
            return
        deleted_name = self._profile_display_name(self.profile_id, self.profile)
        try:
            delete_profile_by_id(self.profile_id)
            self._load_profile_after_delete()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._set_status(f"Could not delete profile: {exc}", "error")
            return
        self._undo_stack.clear()
        self._update_undo_state()
        self._refresh_profile_combo()
        self._refresh_page_combo()
        self._rebuild_grid()
        self._select_button(0)
        self.deck.apply_profile(self.profile)
        self._set_status(f"Deleted profile: {deleted_name}", "success")
        self._refresh_diagnostics()

    def _load_profile_after_delete(self) -> None:
        remaining = list_profile_ids()
        saved_remaining = [profile_id for profile_id in remaining if profile_is_saved(profile_id)]
        if not saved_remaining:
            self.profile_id = "default"
            self.profile = create_default_icon_profile(NEW_PROFILE_NAME, self.profile.rows, self.profile.columns)
            save_active_profile_id(self.profile_id)
            return
        next_id = self.default_profile_id if self.default_profile_id in saved_remaining else saved_remaining[0]
        self.profile_id = next_id
        self.profile = load_profile_by_id(next_id)
        save_active_profile_id(next_id)

    def _make_default_profile(self) -> None:
        if self._is_imported_placeholder(self.profile):
            self.profile.name = "Default"
        self.default_profile_id = self.profile_id
        save_default_profile_id(self.profile_id)
        self._save_profile(silent=True)
        self._refresh_profile_combo()
        self._set_status(f"Default profile: {self._profile_display_name(self.profile_id, self.profile)}", "success")

    def _profile_display_name(self, profile_id: str, profile: Profile) -> str:
        name = profile.name.strip()
        if profile_id == self.default_profile_id:
            if not name or name.lower() in {"default", "imported"}:
                return "Default"
            return f"{name} (Default)"
        if self._is_imported_placeholder(profile):
            return "Imported"
        return name or "Untitled"

    def _is_imported_placeholder(self, profile: Profile) -> bool:
        return profile.name.strip().lower() == "imported"

    def _is_unnamed_profile(self, profile: Profile) -> bool:
        return profile.name.strip().casefold().startswith(NEW_PROFILE_NAME.casefold())

    def _refresh_mcp_toggle(self) -> None:
        if not hasattr(self, "mcp_toggle"):
            return
        self._updating_editor = True
        self.mcp_toggle.set_active(self.profile_id == MCP_PROFILE_ID)
        self._updating_editor = False

    def _refresh_page_combo(self) -> None:
        self._updating_editor = True
        self.page_combo.remove_all()
        for page_id in self.profile.page_ids():
            self.page_combo.append(page_id, self.profile.page_names.get(page_id, page_id))
        self.page_combo.set_active_id(self.profile.current_page)
        self._updating_editor = False

    def _color_changed(self) -> None:
        self._editor_changed()

    def _refresh_all_previews(self) -> None:
        for index in range(self.profile.button_count()):
            self._refresh_preview(index)

    def _refresh_preview(self, index: int) -> None:
        if index >= len(self.key_buttons):
            return
        config = self.profile.get_button(index)
        pixbuf = _pixbuf_from_pil(render_button_image(config, (144, 144)))
        self.key_buttons[index].set_preview(pixbuf, config.label)

    def _browse_target(self) -> None:
        action_type = self.action_combo.get_active_text()
        if action_type == "page":
            self._choose_page_target()
            return
        if action_type not in {"file", "command"}:
            self._set_status("Browse is available for file, command, and page actions.")
            return
        dialog = Gtk.FileChooserNative.new("Choose target", self, Gtk.FileChooserAction.OPEN, "Choose", "Cancel")
        dialog.connect("response", self._on_file_chosen)
        dialog.show()

    def _on_file_chosen(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                self._set_text_view(file.get_path())
        dialog.destroy()

    def _choose_button_image(self, image_kind: str) -> None:
        if image_kind == "action":
            self._show_action_image_gallery()
            return
        self._choose_image_file(image_kind)

    def _choose_image_file(self, image_kind: str) -> None:
        dialog = Gtk.FileChooserNative.new("Choose image", self, Gtk.FileChooserAction.OPEN, "Choose", "Cancel")
        dialog.connect("response", lambda dlg, response, kind=image_kind: self._on_button_image_chosen(dlg, response, kind))
        dialog.show()

    def _show_action_image_gallery(self) -> None:
        window = Gtk.Window(title="Choose Action Image", transient_for=self, modal=True)
        window.set_default_size(620, 520)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        window.set_child(root)

        toolbar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        browse = Gtk.Button(label="Browse File")
        browse.connect("clicked", lambda *_args: (window.close(), self._choose_image_file("action")))
        toolbar.append(browse)
        clear = Gtk.Button(label="Clear")
        clear.connect("clicked", lambda *_args: (self.action_image_entry.set_text(""), window.close()))
        toolbar.append(clear)
        root.append(toolbar)

        notebook = Gtk.Notebook()
        notebook.set_vexpand(True)
        root.append(notebook)

        grouped_icons: dict[str, list[Any]] = {}
        for option in action_icons(self.profile_id):
            grouped_icons.setdefault(option.group, []).append(option)

        for group in sorted(grouped_icons, key=self._action_icon_group_sort_key):
            options = grouped_icons[group]
            scrolled = Gtk.ScrolledWindow()
            scrolled.set_vexpand(True)
            flow = Gtk.FlowBox()
            flow.set_selection_mode(Gtk.SelectionMode.NONE)
            flow.set_max_children_per_line(5)
            flow.set_column_spacing(10)
            flow.set_row_spacing(10)
            scrolled.set_child(flow)
            for option in options:
                flow.insert(self._action_icon_gallery_button(option, window), -1)
            notebook.append_page(scrolled, Gtk.Label(label=group))

        window.present()

    def _action_icon_group_sort_key(self, group: str) -> tuple[int, str]:
        if group == "Default":
            return (0, "")
        return (1, group.casefold())

    def _action_icon_gallery_button(self, option: Any, window: Gtk.Window) -> Gtk.Button:
        button = Gtk.Button()
        button.set_tooltip_text(option.name)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(4)
        box.set_margin_bottom(6)
        box.set_margin_start(4)
        box.set_margin_end(4)
        preview = Gtk.Image()
        preview.set_pixel_size(66)
        try:
            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(option.path), 66, 66, True)
            preview.set_from_pixbuf(pixbuf)
        except GLib.Error:
            preview.set_from_icon_name("image-missing-symbolic")
        box.append(preview)
        button.set_child(box)
        button.connect("clicked", lambda *_args, path=option.path: (self.action_image_entry.set_text(str(path)), window.close()))
        return button

    def _on_button_image_chosen(self, dialog: Gtk.FileChooserNative, response: int, image_kind: str) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                if image_kind == "background":
                    self.background_image_entry.set_text(file.get_path())
                else:
                    try:
                        self.action_image_entry.set_text(str(self._import_action_icon_file(Path(file.get_path()))))
                    except OSError as exc:
                        self._set_status(f"Could not import action icon: {exc}", "error")
        dialog.destroy()

    def _import_action_icon_file(self, source: Path) -> Path:
        target_directory = profile_action_icons_dir(self.profile_id)
        target_directory.mkdir(parents=True, exist_ok=True)
        stem = self._safe_asset_stem(source.stem) or "icon"
        suffix = source.suffix.lower() if source.suffix else ".png"
        target = target_directory / f"{stem}{suffix}"
        counter = 2
        while target.exists() and not source.samefile(target):
            target = target_directory / f"{stem}-{counter}{suffix}"
            counter += 1
        if target.exists() and source.samefile(target):
            return target
        shutil.copy2(source, target)
        return target

    def _safe_asset_stem(self, value: str) -> str:
        return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-")

    def _run_selected(self) -> None:
        self._run_index(self.selected_index)

    def _run_index(self, index: int) -> bool:
        if index < 0 or index >= self.profile.button_count():
            return False
        if index in self._suppress_release:
            self._suppress_release.discard(index)
            self._log(f"release key={index} suppressed")
            return False
        try:
            config = self.profile.get_button(index)
            self._log(f"release key={index} label={config.label!r} action={config.action_type} target={redact_target(config)!r}")
            tutorial_result = self._show_tutorial_if_needed(config)
            if tutorial_result:
                if tutorial_result == "opened":
                    self._last_action = f"release key={index}: opened tutorial {config.label!r}"
                    self._set_status(f"Tutorial: {config.label}", "success")
                else:
                    self._last_action = f"release key={index}: tutorial failed"
                self._refresh_diagnostics()
                return False
            if config.action_type == "text":
                message = paste_text_action(config, paste=self._paste)
                self._last_action = f"release key={index}: {message}"
                self._set_status(message)
                self._refresh_diagnostics()
                return False
            if config.action_type == "page":
                self._switch_to_page(config.target)
                return False
            message = run_action(config, copy_text=self._copy_text, paste=self._paste)
            self._last_action = f"release key={index}: {message}"
            self._set_status(message)
        except ActionError as exc:
            self._last_action = f"release key={index}: {exc}"
            self._set_status(str(exc))
        except Exception as exc:
            self._last_action = f"release key={index}: {exc}"
            self._set_status(f"Action failed: {exc}")
        self._refresh_diagnostics()
        return False

    def _key_pressed(self, index: int) -> bool:
        if index < 0 or index >= self.profile.button_count():
            return False
        try:
            config = self.profile.get_button(index)
            self._log(f"press key={index} label={config.label!r} action={config.action_type} target={redact_target(config)!r}")
            tutorial_result = self._show_tutorial_if_needed(config)
            if tutorial_result:
                self._suppress_release.add(index)
                if tutorial_result == "opened":
                    self._last_action = f"press key={index}: opened tutorial {config.label!r}"
                    self._set_status(f"Tutorial: {config.label}", "success")
                else:
                    self._last_action = f"press key={index}: tutorial failed"
            elif config.action_type == "text":
                message = copy_text_action(config, copy_text=self._copy_text)
                self._last_action = f"press key={index}: {message}"
                self._set_status(message)
            elif config.action_type == "page":
                self._suppress_release.add(index)
                self._last_action = f"press key={index}: switching page"
                self._switch_to_page(config.target)
        except ActionError as exc:
            self._last_action = f"press key={index}: {exc}"
            self._set_status(str(exc))
        except Exception as exc:
            self._last_action = f"press key={index}: {exc}"
            self._set_status(f"Action failed: {exc}")
        self._refresh_diagnostics()
        return False

    def _show_tutorial_if_needed(self, config: Any) -> str:
        if config.action_type != "tutorial" and not (
            config.action_type == "text" and config.target.startswith(TUTORIAL_TARGET_PREFIX)
        ):
            return ""
        if not config.target.startswith(TUTORIAL_TARGET_PREFIX):
            self._set_status("Tutorial target is missing or invalid.", "error")
            return "error"
        try:
            slides = json.loads(config.target[len(TUTORIAL_TARGET_PREFIX) :])
        except json.JSONDecodeError as exc:
            self._set_status(f"Tutorial is not readable: {exc}", "error")
            return "error"
        if not isinstance(slides, list) or not slides:
            self._set_status("Tutorial has no slides.", "error")
            return "error"
        normalized = []
        for slide in slides:
            if not isinstance(slide, dict):
                continue
            title = str(slide.get("title", "")).strip()
            body = str(slide.get("body", "")).strip()
            if title or body:
                normalized.append({"title": title or config.label, "body": body})
        if not normalized:
            self._set_status("Tutorial has no readable slides.", "error")
            return "error"
        self._show_tutorial_slideshow(config.label or "Tutorial", config.subtitle, normalized)
        return "opened"

    def _show_tutorial_slideshow(self, title: str, subtitle: str, slides: list[dict[str, str]]) -> None:
        window = Gtk.Window(title=title, transient_for=self, modal=True)
        window.set_default_size(560, 420)
        window.add_css_class("tutorial-window")

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        root.set_margin_top(18)
        root.set_margin_bottom(16)
        root.set_margin_start(18)
        root.set_margin_end(18)
        window.set_child(root)

        header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        eyebrow = Gtk.Label(label=subtitle or "TUTORIAL", xalign=0)
        eyebrow.add_css_class("tutorial-eyebrow")
        header.append(eyebrow)
        heading = Gtk.Label(label=title, xalign=0)
        heading.add_css_class("tutorial-heading")
        heading.set_wrap(True)
        header.append(heading)
        root.append(header)

        stack = Gtk.Stack()
        stack.set_vexpand(True)
        stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        stack.set_transition_duration(260)
        root.append(stack)

        for index, slide in enumerate(slides):
            page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            page.add_css_class("tutorial-slide")
            page.set_margin_top(18)
            page.set_margin_bottom(18)
            page.set_margin_start(18)
            page.set_margin_end(18)
            slide_title = Gtk.Label(label=slide["title"], xalign=0)
            slide_title.add_css_class("tutorial-slide-title")
            slide_title.set_wrap(True)
            body = Gtk.Label(label=slide["body"], xalign=0)
            body.add_css_class("tutorial-slide-body")
            body.set_wrap(True)
            body.set_vexpand(True)
            page.append(slide_title)
            page.append(body)
            stack.add_named(page, str(index))

        progress = Gtk.ProgressBar()
        root.append(progress)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        counter = Gtk.Label(xalign=0)
        counter.set_hexpand(True)
        counter.add_css_class("tutorial-counter")
        previous = Gtk.Button(label="Previous")
        next_button = Gtk.Button(label="Next")
        close = Gtk.Button(label="Close")
        footer.append(counter)
        footer.append(previous)
        footer.append(next_button)
        footer.append(close)
        root.append(footer)

        state = {"index": 0, "timer": 0}

        def update() -> None:
            current = int(state["index"])
            stack.set_visible_child_name(str(current))
            counter.set_text(f"Slide {current + 1} of {len(slides)}")
            progress.set_fraction((current + 1) / len(slides))
            previous.set_sensitive(current > 0)
            next_button.set_label("Replay" if current == len(slides) - 1 else "Next")

        def set_index(index: int) -> None:
            state["index"] = max(0, min(index, len(slides) - 1))
            update()

        def advance() -> bool:
            current = int(state["index"])
            if current >= len(slides) - 1:
                return True
            set_index(current + 1)
            return True

        def stop_timer() -> None:
            timer_id = int(state.get("timer", 0))
            if timer_id:
                GLib.source_remove(timer_id)
                state["timer"] = 0

        previous.connect("clicked", lambda *_args: set_index(int(state["index"]) - 1))
        next_button.connect("clicked", lambda *_args: set_index(0 if int(state["index"]) == len(slides) - 1 else int(state["index"]) + 1))
        close.connect("clicked", lambda *_args: window.close())
        window.connect("close-request", lambda *_args: (stop_timer(), False)[1])
        state["timer"] = GLib.timeout_add_seconds(7, advance)
        update()
        window.present()

    def _log_key_event(self, index: int, pressed: bool) -> bool:
        self._last_key_event = f"key={index} state={'pressed' if pressed else 'released'}"
        self._log(f"raw key={index} state={'pressed' if pressed else 'released'}")
        self._refresh_diagnostics()
        return False

    def _save_now(self) -> None:
        if self._save_profile(silent=False):
            self.deck.apply_profile(self.profile)
            self._set_status("Profile saved and applied.", "success")

    def _clear_selected(self) -> None:
        self._push_undo()
        self.profile.clear_button(self.selected_index)
        self._select_button(self.selected_index)
        self._refresh_preview(self.selected_index)
        self.deck.apply_button(self.profile, self.selected_index)
        self._save_profile(silent=True)
        self._set_status(f"Button {self.selected_index + 1} cleared.")

    def _import_profile(self) -> None:
        dialog = Gtk.FileChooserNative.new("Import profile", self, Gtk.FileChooserAction.OPEN, "Import", "Cancel")
        dialog.connect("response", self._on_import_chosen)
        dialog.show()

    def _on_import_chosen(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                try:
                    self._push_undo()
                    self.profile = import_profile(Path(file.get_path()))
                    self.profile_id = self._profile_id_for_import(self.profile.name)
                    save_active_profile_id(self.profile_id)
                    save_profile_by_id(self.profile_id, self.profile)
                    self._refresh_profile_combo()
                    self._refresh_page_combo()
                    self._rebuild_grid()
                    self._select_button(0)
                    self.deck.apply_profile(self.profile)
                    self._save_profile(silent=True)
                    report = profile_diagnostics(self.profile)
                    self._last_import_report = report.render()
                    self._last_action = f"Imported {Path(file.get_path()).name}: {report.short_summary()}"
                    self._refresh_diagnostics()
                    self._set_status(f"Imported {file.get_path()}: {report.short_summary()}.")
                except (ImportProfileError, OSError, json.JSONDecodeError, ValueError) as exc:
                    self._set_status(f"Import failed: {exc}")
        dialog.destroy()

    def _mcp_toggled(self) -> None:
        if self._updating_editor:
            return
        if self.profile_id == MCP_PROFILE_ID:
            self._refresh_mcp_toggle()
            return
        self._use_mcp_profile()

    def _use_mcp_profile(self) -> None:
        try:
            self._save_profile(silent=True)
            self.profile = ensure_mcp_profile(self.profile.rows, self.profile.columns)
            self.profile_id = MCP_PROFILE_ID
            save_active_profile_id(self.profile_id)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self._set_status(f"Could not create MCP profile: {exc}", "error")
            return
        self._undo_stack.clear()
        self._update_undo_state()
        self._refresh_profile_combo()
        self._refresh_mcp_toggle()
        self._refresh_page_combo()
        self._rebuild_grid()
        self._select_button(0)
        self.deck.apply_profile(self.profile)
        self._save_profile(silent=True)
        self._set_status(f"Using blank profile: {MCP_PROFILE_NAME}", "success")
        self._refresh_diagnostics()

    def _export_profile(self) -> None:
        dialog = Gtk.FileChooserNative.new("Export profile", self, Gtk.FileChooserAction.SAVE, "Export", "Cancel")
        dialog.set_current_name("streamdeck-profile.json")
        dialog.connect("response", self._on_export_chosen)
        dialog.show()

    def _on_export_chosen(self, dialog: Gtk.FileChooserNative, response: int) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                try:
                    save_profile(self.profile, Path(file.get_path()))
                    self._set_status(f"Exported {file.get_path()}.", "success")
                except OSError as exc:
                    self._set_status(f"Export failed: {exc}", "error")
        dialog.destroy()

    def _show_diagnostics(self) -> None:
        if self.diagnostics_window:
            self._refresh_diagnostics()
            self.diagnostics_window.present()
            return
        window = Gtk.Window(title="Diagnostics", transient_for=self)
        window.set_default_size(620, 520)
        window.connect("close-request", self._diagnostics_closed)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        window.set_child(root)

        self.diagnostics_view = Gtk.TextView()
        self.diagnostics_view.set_editable(False)
        self.diagnostics_view.set_cursor_visible(False)
        self.diagnostics_view.set_monospace(True)
        self.diagnostics_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        scrolled.set_child(self.diagnostics_view)
        root.append(scrolled)

        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        refresh = Gtk.Button(label="Refresh")
        refresh.connect("clicked", lambda *_args: self._refresh_diagnostics())
        close = Gtk.Button(label="Close")
        close.connect("clicked", lambda *_args: window.close())
        buttons.append(refresh)
        buttons.append(close)
        root.append(buttons)

        self.diagnostics_window = window
        self._refresh_diagnostics()
        window.present()

    def _diagnostics_closed(self, *_args) -> bool:
        self.diagnostics_window = None
        self.diagnostics_view = None
        return False

    def _load_profile(self) -> tuple[str, Profile]:
        try:
            return load_active_profile()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.startup_message = f"Could not load saved profile: {exc}"
            return "default", Profile()

    def _push_undo(self) -> None:
        snapshot = self.profile.to_dict()
        if self._undo_stack and self._undo_stack[-1] == snapshot:
            return
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > 100:
            self._undo_stack.pop(0)
        self._update_undo_state()

    def _undo(self) -> None:
        if not self._undo_stack:
            self._set_status("Nothing to undo.")
            return
        try:
            self.profile = Profile.from_dict(self._undo_stack.pop())
        except (TypeError, ValueError) as exc:
            self._set_status(f"Undo failed: {exc}")
            self._update_undo_state()
            return
        self._refresh_page_combo()
        self._rebuild_grid()
        self._select_button(min(self.selected_index, self.profile.button_count() - 1))
        self.deck.apply_profile(self.profile)
        self._save_profile(silent=True)
        self._update_undo_state()
        self._set_status("Undid last change.")
        self._refresh_diagnostics()

    def _update_undo_state(self) -> None:
        if hasattr(self, "undo_button"):
            self.undo_button.set_sensitive(bool(self._undo_stack))

    def _save_profile(self, silent: bool) -> bool:
        try:
            save_profile_by_id(self.profile_id, self.profile)
            save_active_profile_id(self.profile_id)
            return True
        except OSError as exc:
            if not silent:
                self._set_status(f"Could not save profile: {exc}")
            return False

    def _set_status(self, message: str, tone: str = "") -> bool:
        self._log(f"status {message}")
        self.status_label.remove_css_class("status-success")
        self.status_label.remove_css_class("status-error")
        if tone == "success":
            self.status_label.add_css_class("status-success")
        elif tone == "error":
            self.status_label.add_css_class("status-error")
        self.status_label.set_text(message)
        return False

    def _get_text_view(self) -> str:
        buffer = self.target_view.get_buffer()
        start, end = buffer.get_bounds()
        return buffer.get_text(start, end, True)

    def _set_text_view(self, text: str) -> None:
        self.target_view.get_buffer().set_text(text)

    def _switch_to_page(self, page_id: str) -> None:
        if not page_id:
            self._set_status("This page button is not linked yet. Select it, click Browse, then choose a page.")
            return
        if page_id == "__previous__":
            self._previous_page()
            return
        if page_id == "__next__":
            self._next_page()
            return
        if page_id not in self.profile.pages:
            self._set_status("Page target is not available.")
            return
        self.profile.set_current_page(page_id)
        self._log(f"switch page={page_id} name={self.profile.page_names.get(page_id, page_id)!r}")
        self._refresh_page_combo()
        self._rebuild_grid()
        self._select_button(0)
        self.deck.apply_profile(self.profile)
        self._save_profile(silent=True)
        self._set_status(f"Page: {self.profile.page_names.get(page_id, page_id)}")
        self._refresh_diagnostics()

    def _refresh_diagnostics(self) -> None:
        if not self.diagnostics_view:
            return
        page_id = self.profile.current_page
        page_name = self.profile.page_names.get(page_id, page_id)
        config = self.profile.get_button(self.selected_index)
        helpers = ", ".join(_helper_status())
        lines = [
            f"Device: {self.device_label.get_text() if hasattr(self, 'device_label') else 'Unknown'}",
            f"Profile: {self.profile.name}",
            f"Profile ID: {self.profile_id}",
            f"Layout: {self.profile.rows} x {self.profile.columns} ({self.profile.button_count()} buttons)",
            f"Page: {page_name}",
            f"Page ID: {page_id}",
            f"Selected: {self.selected_index} (row {self.selected_index // self.profile.columns}, column {self.selected_index % self.profile.columns})",
            f"Label: {config.label or '-'}",
            f"Action: {config.action_type}",
            f"Target: {redact_target(config)}",
            f"Last key: {self._last_key_event}",
            f"Last action: {self._last_action}",
            f"Helpers: {helpers}",
            "",
            self._last_import_report,
        ]
        self.diagnostics_view.get_buffer().set_text("\n".join(lines))

    def _log(self, message: str) -> None:
        try:
            log_path = config_dir() / "events.log"
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
        except OSError:
            pass

    def _previous_page(self) -> None:
        page_ids = self.profile.page_ids()
        if not page_ids:
            return
        index = page_ids.index(self.profile.current_page) if self.profile.current_page in page_ids else 0
        self._switch_to_page(page_ids[(index - 1) % len(page_ids)])

    def _next_page(self) -> None:
        page_ids = self.profile.page_ids()
        if not page_ids:
            return
        index = page_ids.index(self.profile.current_page) if self.profile.current_page in page_ids else 0
        self._switch_to_page(page_ids[(index + 1) % len(page_ids)])

    def _choose_page_target(self) -> None:
        menu = Gtk.Popover()
        menu.set_parent(self)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        menu.set_child(box)
        for page_id in self.profile.page_ids():
            button = Gtk.Button(label=self.profile.page_names.get(page_id, page_id))
            button.connect("clicked", lambda _button, pid=page_id: (self._set_text_view(pid), menu.popdown()))
            box.append(button)
        menu.popup()

    def _profile_id_for_import(self, name: str) -> str:
        base = name.lower().replace(" ", "-") or "imported"
        profile_id = "".join(char for char in base if char.isalnum() or char == "-").strip("-") or "imported"
        existing = set(list_profile_ids())
        if profile_id not in existing or profile_id == self.profile_id:
            return profile_id
        suffix = 2
        while f"{profile_id}-{suffix}" in existing:
            suffix += 1
        return f"{profile_id}-{suffix}"

    def _copy_text(self, text: str) -> None:
        if _copy_text_with_cli(text):
            return
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)

    def _paste(self) -> None:
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

    def _set_color(self, button: Gtk.ColorButton, value: str) -> None:
        rgba = Gdk.RGBA()
        if not rgba.parse(value):
            rgba.parse("#1f2937")
        button.set_rgba(rgba)

    def _install_css(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(
            b"""
            .top-toolbar {
                padding: 6px 8px;
                background-color: #1e293b;
                border-radius: 7px;
                border: 1px solid #0f172a;
            }
            .toolbar-group {
                padding: 1px;
                background-color: #334155;
                border-radius: 7px;
                border: 1px solid #475569;
            }
            .toolbar-button {
                min-width: 43px;
                min-height: 32px;
                padding: 0;
                background-color: #475569;
                color: #f8fafc;
                border: 1px solid #64748b;
                border-radius: 5px;
                -gtk-icon-size: 20px;
            }
            .toolbar-button label {
                color: #f8fafc;
                font-weight: 700;
                font-size: 13px;
            }
            .toolbar-button .file-button-label {
                color: #f8fafc;
                font-weight: 700;
            }
            .file-button {
                min-width: 43px;
                min-height: 32px;
            }
            .toolbar-button:hover { background-color: #64748b; }
            .toolbar-button:active {
                background-color: #334155;
                border-color: #94a3b8;
                box-shadow: inset 0 2px 4px rgba(15, 23, 42, 0.25);
                transform: translateY(1px);
            }
            .device-label { font-weight: 700; font-size: 13px; color: #f8fafc; }
            .top-toolbar label { color: #f8fafc; }
            .status-label {
                min-height: 18px;
                padding: 2px 10px;
                color: #1e293b;
                background-color: #f8fafc;
                border-top: 1px solid #cbd5e1;
                font-weight: 600;
                font-size: 12px;
            }
            .status-label.status-success {
                color: #064e3b;
                background-color: #d1fae5;
                border-top-color: #10b981;
            }
            .status-label.status-error {
                color: #7f1d1d;
                background-color: #fee2e2;
                border-top-color: #ef4444;
            }
            .key-button { border-radius: 7px; padding: 0; }
            .key-button.selected { border: 2px solid #0f766e; background: #ecfdf5; }
            .key-button.drag-source { opacity: 0.55; }
            .key-button.drop-target {
                border: 2px solid #2563eb;
                background: #eff6ff;
            }
            .key-label { font-weight: 600; font-size: 12px; }
            .tutorial-window {
                background: #f8fafc;
            }
            .tutorial-eyebrow {
                color: #0f766e;
                font-size: 12px;
                font-weight: 800;
                letter-spacing: 0;
            }
            .tutorial-heading {
                color: #0f172a;
                font-size: 25px;
                font-weight: 800;
            }
            .tutorial-slide {
                background: #ffffff;
                border: 1px solid #cbd5e1;
                border-radius: 8px;
            }
            .tutorial-slide-title {
                color: #123c69;
                font-size: 19px;
                font-weight: 800;
            }
            .tutorial-slide-body {
                color: #1e293b;
                font-size: 15px;
                line-height: 1.35;
            }
            .tutorial-counter {
                color: #475569;
                font-weight: 700;
                font-size: 12px;
            }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def _pixbuf_from_pil(image) -> GdkPixbuf.Pixbuf:
    image = image.convert("RGBA")
    width, height = image.size
    data = GLib.Bytes.new(image.tobytes())
    return GdkPixbuf.Pixbuf.new_from_bytes(
        data,
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        width,
        height,
        width * 4,
    )


def _rgba_to_hex(rgba: Gdk.RGBA) -> str:
    red = max(0, min(255, round(rgba.red * 255)))
    green = max(0, min(255, round(rgba.green * 255)))
    blue = max(0, min(255, round(rgba.blue * 255)))
    return f"#{red:02x}{green:02x}{blue:02x}"


def _paste_env(tool: str) -> dict[str, str] | None:
    if tool != "ydotool":
        return None
    env = os.environ.copy()
    socket = Path(f"/run/user/{os.getuid()}/.ydotool_socket")
    if socket.exists():
        env.setdefault("YDOTOOL_SOCKET", str(socket))
    return env


def _copy_text_with_cli(text: str) -> bool:
    commands = (
        ["wl-copy"],
        ["xclip", "-selection", "clipboard"],
        ["xsel", "--clipboard", "--input"],
    )
    for command in commands:
        executable = shutil.which(command[0])
        if not executable:
            continue
        subprocess.run([executable, *command[1:]], input=text, text=True, check=True)
        return True
    return False


def _helper_status() -> list[str]:
    helpers = []
    for name in ("wl-copy", "ydotool", "wtype", "xdotool", "xdg-open", "gio"):
        helpers.append(f"{name}={'yes' if shutil.which(name) else 'no'}")
    socket = Path(f"/run/user/{os.getuid()}/.ydotool_socket")
    helpers.append(f"ydotool_socket={'yes' if socket.exists() else 'no'}")
    return helpers


def _tray_indicator_available() -> bool:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "streamdeck_studio.tray_indicator", "--check"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def run() -> int:
    app = Adw.Application(application_id="dev.local.CozmikStudio")

    def activate(application: Adw.Application) -> None:
        for window in application.get_windows():
            if isinstance(window, MainWindow):
                window._show_from_tray()
                return
        window = MainWindow(application)
        window.set_icon_name("cozmik-studio")
        window.present()

    app.connect("activate", activate)
    return app.run(None)
