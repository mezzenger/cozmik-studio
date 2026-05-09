from __future__ import annotations

from io import BytesIO
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import gi

gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gtk", "4.0")

from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk

from .action_icons import action_icons
from .actions import ActionError, copy_text_action, paste_text_action, run_action
from .deck import StreamDeckController
from .diagnostics import profile_diagnostics, redact_target
from .images import render_button_image
from .importers import ImportProfileError, import_profile
from .model import ACTION_TYPES, Profile, config_dir, load_profile, save_profile


class KeyButton(Gtk.Button):
    def __init__(self, index: int, on_clicked) -> None:
        super().__init__()
        self.index = index
        self.add_css_class("key-button")
        self.set_size_request(124, 132)
        self.connect("clicked", lambda *_args: on_clicked(index))

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_margin_top(8)
        box.set_margin_bottom(8)
        box.set_margin_start(8)
        box.set_margin_end(8)
        self.image = Gtk.Image()
        self.image.set_pixel_size(88)
        self.label = Gtk.Label()
        self.label.set_ellipsize(3)
        self.label.set_max_width_chars(14)
        self.label.add_css_class("key-label")
        box.append(self.image)
        box.append(self.label)
        self.set_child(box)

    def set_preview(self, pixbuf: GdkPixbuf.Pixbuf, label: str) -> None:
        self.image.set_from_pixbuf(pixbuf)
        self.label.set_text(label)
        self.set_tooltip_text(label)


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application) -> None:
        super().__init__(application=app, title="Stream Deck Studio")
        self.set_default_size(1120, 720)

        self.startup_message = ""
        self.profile = self._load_profile()
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

        self._build_ui()
        self._connect_deck()
        if self.startup_message:
            self._set_status(self.startup_message)

    def do_close_request(self):
        self._save_profile(silent=True)
        self.deck.close()
        return False

    def _build_ui(self) -> None:
        self._install_css()
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_content(root)

        header = Adw.HeaderBar()
        root.append(header)

        for label, callback in (
            ("Save", self._save_now),
            ("Reconnect", self._connect_deck),
            ("Previous", self._previous_page),
            ("Next", self._next_page),
            ("Run", self._run_selected),
            ("Clear", self._clear_selected),
            ("Import", self._import_profile),
            ("Export", self._export_profile),
        ):
            button = Gtk.Button(label=label)
            button.connect("clicked", lambda _button, cb=callback: cb())
            header.pack_start(button) if label in {"Save", "Reconnect", "Previous", "Next"} else header.pack_end(button)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.set_margin_top(16)
        content.set_margin_bottom(16)
        content.set_margin_start(16)
        content.set_margin_end(16)
        root.append(content)

        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        left.set_hexpand(True)
        content.append(left)

        self.device_label = Gtk.Label(label="No Stream Deck connected", xalign=0)
        self.device_label.add_css_class("device-label")
        left.append(self.device_label)

        page_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page_row.append(Gtk.Label(label="Page", xalign=0))
        self.page_combo = Gtk.ComboBoxText()
        self.page_combo.set_hexpand(True)
        self.page_combo.connect("changed", lambda *_args: self._page_changed())
        page_row.append(self.page_combo)
        left.append(page_row)

        self.grid = Gtk.Grid(column_spacing=10, row_spacing=10)
        left.append(self.grid)

        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        right.set_size_request(380, -1)
        content.append(right)

        editor = Gtk.Frame(label="Button")
        right.append(editor)
        form = Gtk.Grid(column_spacing=10, row_spacing=10)
        form.set_margin_top(14)
        form.set_margin_bottom(14)
        form.set_margin_start(14)
        form.set_margin_end(14)
        editor.set_child(form)

        self.index_label = Gtk.Label(label="1", xalign=0)
        self.label_entry = Gtk.Entry(max_length=48)
        self.subtitle_entry = Gtk.Entry(max_length=48)
        self.action_combo = Gtk.ComboBoxText()
        for action in ACTION_TYPES:
            self.action_combo.append_text(action)
        self.target_view = Gtk.TextView()
        self.target_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.target_view.set_size_request(-1, 110)
        self.background_button = Gtk.ColorButton()
        self.foreground_button = Gtk.ColorButton()
        self.background_image_entry = Gtk.Entry()
        self.action_image_entry = Gtk.Entry()

        self._attach_row(form, 0, "Number", self.index_label)
        self._attach_row(form, 1, "Label", self.label_entry)
        self._attach_row(form, 2, "Subtitle", self.subtitle_entry)
        self._attach_row(form, 3, "Action", self.action_combo)
        self._attach_row(form, 4, "Target", self.target_view)

        target_buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        browse = Gtk.Button(label="Browse")
        browse.connect("clicked", lambda *_args: self._browse_target())
        run = Gtk.Button(label="Run")
        run.connect("clicked", lambda *_args: self._run_selected())
        target_buttons.append(browse)
        target_buttons.append(run)
        form.attach(target_buttons, 1, 5, 1, 1)

        color_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        color_row.append(self.background_button)
        color_row.append(self.foreground_button)
        self._attach_row(form, 6, "Colors", color_row)

        self._attach_row(form, 7, "Background Image", self._image_row(self.background_image_entry, "background"))
        self._attach_row(form, 8, "Action Image", self._image_row(self.action_image_entry, "action"))

        diagnostics = Gtk.Frame(label="Diagnostics")
        right.append(diagnostics)
        diagnostics_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        diagnostics_box.set_margin_top(12)
        diagnostics_box.set_margin_bottom(12)
        diagnostics_box.set_margin_start(12)
        diagnostics_box.set_margin_end(12)
        diagnostics.set_child(diagnostics_box)
        self.diagnostics_view = Gtk.TextView()
        self.diagnostics_view.set_editable(False)
        self.diagnostics_view.set_cursor_visible(False)
        self.diagnostics_view.set_monospace(True)
        self.diagnostics_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.diagnostics_view.set_size_request(-1, 220)
        diagnostics_box.append(self.diagnostics_view)
        refresh_diagnostics = Gtk.Button(label="Refresh Diagnostics")
        refresh_diagnostics.connect("clicked", lambda *_args: self._refresh_diagnostics())
        diagnostics_box.append(refresh_diagnostics)

        self.status_label = Gtk.Label(xalign=0)
        self.status_label.add_css_class("status-label")
        root.append(self.status_label)

        self.label_entry.connect("changed", lambda *_args: self._editor_changed())
        self.subtitle_entry.connect("changed", lambda *_args: self._editor_changed())
        self.action_combo.connect("changed", lambda *_args: self._editor_changed())
        self.target_view.get_buffer().connect("changed", lambda *_args: self._editor_changed())
        self.background_button.connect("color-set", lambda *_args: self._color_changed())
        self.foreground_button.connect("color-set", lambda *_args: self._color_changed())
        self.background_image_entry.connect("changed", lambda *_args: self._editor_changed())
        self.action_image_entry.connect("changed", lambda *_args: self._editor_changed())

        self._rebuild_grid()
        self._refresh_page_combo()
        self._select_button(0)
        self._refresh_diagnostics()

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
            if self.profile.button_count() != info.key_count:
                self.profile.set_layout(info.rows, info.columns)
            self.device_label.set_text(f"{info.name} - {info.rows} x {info.columns}")
            self.profile.page_ids()
            self._rebuild_grid()
            self.deck.apply_profile(self.profile)
            self._save_profile(silent=True)
        else:
            self.device_label.set_text(f"Offline editor - {self.profile.rows} x {self.profile.columns}")
            if info.error:
                self._set_status(info.error)
        self._select_button(min(self.selected_index, self.profile.button_count() - 1))

    def _rebuild_grid(self) -> None:
        child = self.grid.get_first_child()
        while child:
            next_child = child.get_next_sibling()
            self.grid.remove(child)
            child = next_child
        self.key_buttons.clear()
        for index in range(self.profile.button_count()):
            button = KeyButton(index, self._select_button)
            self.key_buttons.append(button)
            self.grid.attach(button, index % self.profile.columns, index // self.profile.columns, 1, 1)
        self._refresh_all_previews()

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
        self.label_entry.set_text(config.label)
        self.subtitle_entry.set_text(config.subtitle)
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
        config = self.profile.get_button(self.selected_index)
        config.label = self.label_entry.get_text()
        config.subtitle = self.subtitle_entry.get_text()
        config.action_type = self.action_combo.get_active_text() or "none"
        config.target = self._get_text_view()
        config.background = _rgba_to_hex(self.background_button.get_rgba())
        config.foreground = _rgba_to_hex(self.foreground_button.get_rgba())
        config.background_image_path = self.background_image_entry.get_text().strip()
        config.action_image_path = self.action_image_entry.get_text().strip()
        self._refresh_preview(self.selected_index)
        self.deck.apply_button(self.profile, self.selected_index)
        self._save_profile(silent=True)

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

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_vexpand(True)
        root.append(scrolled)
        flow = Gtk.FlowBox()
        flow.set_selection_mode(Gtk.SelectionMode.NONE)
        flow.set_max_children_per_line(5)
        flow.set_column_spacing(10)
        flow.set_row_spacing(10)
        scrolled.set_child(flow)

        for option in action_icons():
            button = Gtk.Button()
            button.set_tooltip_text(option.name)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            box.set_margin_top(8)
            box.set_margin_bottom(8)
            box.set_margin_start(8)
            box.set_margin_end(8)
            preview = Gtk.Image()
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(option.path), 56, 56, True)
                preview.set_from_pixbuf(pixbuf)
            except GLib.Error:
                preview.set_from_icon_name("image-missing-symbolic")
            label = Gtk.Label(label=option.name)
            label.set_max_width_chars(12)
            label.set_ellipsize(3)
            box.append(preview)
            box.append(label)
            button.set_child(box)
            button.connect("clicked", lambda *_args, path=option.path: (self.action_image_entry.set_text(str(path)), window.close()))
            flow.insert(button, -1)

        window.present()

    def _on_button_image_chosen(self, dialog: Gtk.FileChooserNative, response: int, image_kind: str) -> None:
        if response == Gtk.ResponseType.ACCEPT:
            file = dialog.get_file()
            if file and file.get_path():
                if image_kind == "background":
                    self.background_image_entry.set_text(file.get_path())
                else:
                    self.action_image_entry.set_text(file.get_path())
        dialog.destroy()

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
            if config.action_type == "text":
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

    def _log_key_event(self, index: int, pressed: bool) -> bool:
        self._last_key_event = f"key={index} state={'pressed' if pressed else 'released'}"
        self._log(f"raw key={index} state={'pressed' if pressed else 'released'}")
        self._refresh_diagnostics()
        return False

    def _save_now(self) -> None:
        if self._save_profile(silent=False):
            self.deck.apply_profile(self.profile)
            self._set_status("Profile saved and applied.")

    def _clear_selected(self) -> None:
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
                    self.profile = import_profile(Path(file.get_path()))
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
                    self._set_status(f"Exported {file.get_path()}.")
                except OSError as exc:
                    self._set_status(f"Export failed: {exc}")
        dialog.destroy()

    def _load_profile(self) -> Profile:
        try:
            return load_profile()
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            self.startup_message = f"Could not load saved profile: {exc}"
            return Profile()

    def _save_profile(self, silent: bool) -> bool:
        try:
            save_profile(self.profile)
            return True
        except OSError as exc:
            if not silent:
                self._set_status(f"Could not save profile: {exc}")
            return False

    def _set_status(self, message: str) -> bool:
        self._log(f"status {message}")
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
        if not hasattr(self, "diagnostics_view"):
            return
        page_id = self.profile.current_page
        page_name = self.profile.page_names.get(page_id, page_id)
        config = self.profile.get_button(self.selected_index)
        helpers = ", ".join(_helper_status())
        lines = [
            f"Device: {self.device_label.get_text() if hasattr(self, 'device_label') else 'Unknown'}",
            f"Profile: {self.profile.name}",
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
            .device-label { font-weight: 700; font-size: 16px; }
            .status-label { padding: 8px 16px; color: #475569; }
            .key-button { border-radius: 8px; padding: 0; }
            .key-button.selected { border: 2px solid #0f766e; background: #ecfdf5; }
            .key-label { font-weight: 600; }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )


def _pixbuf_from_pil(image) -> GdkPixbuf.Pixbuf:
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    loader = GdkPixbuf.PixbufLoader.new_with_type("png")
    loader.write(buffer.getvalue())
    loader.close()
    return loader.get_pixbuf()


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


def run() -> int:
    app = Adw.Application(application_id="dev.local.StreamDeckStudio")

    def activate(application: Adw.Application) -> None:
        window = MainWindow(application)
        window.present()

    app.connect("activate", activate)
    return app.run(None)
