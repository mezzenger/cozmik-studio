# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the GTK app
python3 -m streamdeck_studio

# Run minimized to tray
python3 -m streamdeck_studio --minimized

# Run the MCP server (stdio JSON-RPC)
python3 -m streamdeck_studio.mcp_server

# Run all tests
pytest

# Run a single test file or function
pytest tests/test_model.py
pytest tests/test_model.py::test_fn

# Install user-local launchers and desktop entry (from checkout)
./scripts/install-user.sh
```

Dependencies: `Pillow`, `streamdeck` (HID), GTK4/Libadwaita via `gi`.

## Architecture

### Module responsibilities

| Module | Role |
|---|---|
| `model.py` | `Profile` + `ButtonConfig` dataclasses; all profile I/O under `~/.config/streamdeck-studio/`; app settings; constants |
| `gtk_ui.py` | GTK4/Libadwaita window, button grid, editor panel, toolbar, drag-and-drop, dialogs |
| `deck.py` | `StreamDeckController` — HID connection, background animation/screensaver thread, key-event dispatch |
| `actions.py` | Executes button actions; wraps `ydotool`/`xdotool`/`wtype` for keyboard/text actions |
| `images.py` | Pillow-based button image rendering, GIF frame support, HID-native format conversion |
| `plugins.py` | Plugin manifest loading, library browsing, install/uninstall, config persistence |
| `plugin_helpers.py` | Plugin command building and argument interpolation (`{settings_json}`, `{home}`, etc.) |
| `mcp_server.py` | Stdio JSON-RPC MCP server (`get_profile`, `list_buttons`, `activate_button`) |
| `importers.py` | Best-effort Elgato `.streamDeckProfile` / `.StreamDeckProfilesBackup` import |
| `action_icons.py` | Action-type → bundled icon path mapping |
| `diagnostics.py` | Profile diagnostic summaries; redacts sensitive targets for display |
| `tray_indicator.py` | AppIndicator / system tray integration |

### Key data flow

1. `model.py` loads `Profile` JSON from `~/.config/streamdeck-studio/profiles/<id>.json`. The active and default profile IDs are separate pointer files in the same config dir.
2. `gtk_ui.py` holds the live `Profile` and `profile_id` in memory, calls `save_profile_by_id` on edits.
3. `deck.py` receives the `Profile` via `apply_profile()` and renders button images using `images.py` in a background thread. Physical key events fire registered callbacks in `gtk_ui.py`.
4. `gtk_ui.py` calls `actions.py` on key release (or the Run button). `actions.py` invokes `plugins.py` for `plugin` action type.
5. `mcp_server.py` is standalone — it reads the saved `mcp-deck` profile directly and calls `actions.py`. It never shares state with a running GTK app.

### Profile structure

A `Profile` has named **pages** (`pages: dict[str, dict[str, ButtonConfig]]`). Each page maps string button indices (`"0"`, `"1"`, …) to `ButtonConfig`. `Profile.current_page` and `Profile.buttons` always mirror each other — `buttons` is a direct reference into `pages[current_page]`.

Button layout is `rows × columns` (default 3×5 = 15 keys). Index 0 is top-left, indices increment left-to-right then top-to-bottom.

### Action types

`none` · `command` · `shell` · `url` · `file` · `text` · `page` · `media` · `shortcut` · `keys` · `plugin` · `tutorial`

- `text`: copies to clipboard on press, pastes on release using `ydotool`/`wtype`/`xdotool` (Wayland needs `ydotool`).
- `shortcut`: single chord (e.g. `ctrl+alt+t`). `keys`: multi-step sequence with `delay` tokens.
- `plugin`: target is either `plugin_id.action_id` or a JSON object `{"plugin": "...", "action": "...", "settings": {...}}`.
- `tutorial`: target is `cozmik-tutorial:` + JSON-encoded slides array (inline in the button config).
- `page`: target is a page ID within the same profile.

### Plugins

Installed plugins live at `~/.config/streamdeck-studio/plugins/<plugin-id>/plugin.json`. The bundled library manifests are in `streamdeck_studio/resources/plugin-library/`. Plugin config (API keys, credentials) is stored in `~/.config/streamdeck-studio/plugins/<plugin-id>/config.json`.

### Runtime config files

| Path | Purpose |
|---|---|
| `~/.config/streamdeck-studio/profiles/<id>.json` | Saved profile |
| `~/.config/streamdeck-studio/active-profile` | Last-active profile ID (plain text) |
| `~/.config/streamdeck-studio/default-profile` | Startup default profile ID (plain text) |
| `~/.config/streamdeck-studio/settings.json` | App settings (`start_minimized`, `theme_mode`) |

Profile IDs are kebab-case slugs derived from the profile name. The `default` profile also mirrors to the legacy `profile.json` path for backwards compatibility.

### HID device access

The app opens in offline editor mode if no Stream Deck is found. To grant access:

```bash
sudo cp packaging/udev/70-streamdeck-studio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules && sudo udevadm trigger
```

### Profile privacy

Profiles contain private file paths, URLs, commands, and text snippets. Never commit files from `~/.config/streamdeck-studio/` or exported `.streamDeckProfile`/`.StreamDeckProfilesBackup` files.
