# Cozmik Studio

![Cozmik Studio logo](Images/Cozmik_Studio_banner.png)

A GNOME/GTK desktop app for assigning Stream Deck buttons to launcher actions.

Current capabilities:

- Detect and connect to the first attached Stream Deck.
- Choose between saved profiles from the top toolbar.
- Edit button label, subtitle, colors, and action type.
- Generate button images and apply them to the device.
- Configure an idle-time animated GIF screensaver from the bundled starter pack or your own GIFs.
- Run launchers from a physical key release or the app's Run button.
- Import native JSON profiles and best-effort Elgato `.streamDeckProfile` or `.StreamDeckProfilesBackup` exports.
- Save profiles under `~/.config/streamdeck-studio/profiles/`.
- Create a blank `MCP Deck` profile and expose its buttons through a local MCP server.
- Create a public-safe `Tutorial Profile` with interactive slideshow explainers for common setup and troubleshooting topics.

Supported launcher actions:

- `command`: run an executable with arguments without shell expansion.
- `shell`: run a command through the shell for pipes, redirects, and shell expansion.
- `url`: open a website in the default browser.
- `file`: open a file or folder with `xdg-open`.
- `text`: copy stored text to the desktop clipboard.
- `plugin`: run an installed Cozmik plugin action.

Run it from this checkout:

```bash
python3 -m streamdeck_studio
```

Start hidden in the tray when panel icon support is available, otherwise start minimized:

```bash
python3 -m streamdeck_studio --minimized
```

You can also set this persistently in the app with `Config` -> `Start minimized`. The same global settings tile includes a `Dark or Light` theme preference for future app-wide theme handling.

## MCP Deck

Press `MCP` in the toolbar to create and switch to a blank profile named `MCP Deck`. Configure buttons in that profile the same way as any other deck.

Run the MCP server for an AI agent with:

```bash
cozmik-studio-mcp
```

The server exposes `get_profile`, `list_buttons`, and `activate_button`. `activate_button` uses 1-based button numbers and runs the configured action from the saved `MCP Deck` profile.

## Plugins

Cozmik Studio includes a browseable plugin library in the toolbar. Install a bundled plugin from the library, then assign one of its actions to a button with action type `plugin`.

Some bundled plugins are re-engineered from high-star GitHub projects where Cozmik has a practical Linux integration path. Those entries remain installable Cozmik plugins; source links are shown only as provenance.

Installed plugins live under:

```text
~/.config/streamdeck-studio/plugins/<plugin-id>/plugin.json
```

A plugin manifest defines actions that can be assigned to buttons. Use `Browse` beside the Target field to choose an installed plugin action, or set the target manually as `plugin_id.action_id`.

Workflow from the UI:

1. Open Plugin Library from the toolbar.
2. Install a plugin.
3. Press Configure when the plugin needs login, API keys, or device connection settings.
4. Select a button.
5. Set Action to `plugin`.
6. Click Browse next to Target.
7. Press Use on an installed plugin action.

Actions that need settings fill the Target field with editable JSON. Replace placeholder values such as `LONG_LIVED_TOKEN`, entity names, device names, and commands before pressing Run.

Configuration values are stored locally under `~/.config/streamdeck-studio/plugins/<plugin-id>/config.json`. Treat these files as private because service tokens and passwords may be stored there.

Example manifest:

```json
{
  "id": "demo",
  "name": "Demo",
  "actions": [
    {
      "id": "hello",
      "label": "Say Hello",
      "command": ["notify-send", "Hello from Cozmik"]
    }
  ]
}
```

Plugin actions may also receive settings through a JSON target:

```json
{"plugin": "demo", "action": "hello", "settings": {"name": "Ada"}}
```

Manifest command arguments can use `{plugin_dir}`, `{settings_json}`, `{home}`, and simple setting placeholders such as `{url}`, `{path}`, or `{message}`. Set `"shell": true` only for actions that intentionally need shell features.

For the bundled Home Assistant plugin, use a JSON target such as:

```json
{"plugin": "home-assistant", "action": "toggle", "settings": {"base_url": "http://homeassistant.local:8123", "token": "LONG_LIVED_TOKEN", "domain": "light", "entity_id": "light.office"}}
```

The expanded Desktop Tools plugin includes common session, screenshot, GNOME settings, file/folder, browser, clipboard, notification, and Do Not Disturb actions. For configurable actions, use the JSON template inserted by `Use on selected button`; for example:

```json
{"plugin": "desktop-tools", "action": "open-url", "settings": {"url": "https://example.com"}}
```

Smart-light plugins currently include:

- `WLED`: local network control through the WLED JSON API. Configure the WLED host, then use Turn On, Turn Off, Brightness, Preset, or Open Web UI.
- `Tuya Cloud`: configuration page for Tuya Cloud project credentials, data center, linked app account, and default device ID.
- `Smart Life`: configuration page for Smart Life accounts linked through a Tuya Smart Home PaaS cloud project.
- `YoLink`: configuration page for YoLink UAID/secret credentials and API URL.
- `Sengled Home`: configuration page for Sengled account credentials. Public API support is unofficial and may be unreliable.
- `Sunco Smart Lighting`: configuration page for Sunco credentials, with optional Tuya credentials for Smart Life/Tuya-backed bulbs.

## Tutorial Profile

Use the `New Tutorial Profile` toolbar button to create a clean starter profile and jump straight to its Tutorials page. Tutorial buttons open slideshow-style explainers in the desktop app, covering profiles, pages, actions, images, imports, hardware access, MCP, privacy, backups, and troubleshooting.

Install a user-local command and desktop launcher:

```bash
./scripts/install-user.sh
```

The installer also registers the Cozmik Studio desktop icon from `Images/Cozmik_Studio_icon.png` through `packaging/icons/cozmik-studio.png`. The installed launcher is named `dev.local.CozmikStudio.desktop` so GNOME can match the running app to its icon.

If the device is not accessible, the app still opens as an offline editor. On Linux, Stream Deck access usually requires the current user to have permission to the HID device through udev rules.

## Profile Privacy

Cozmik Studio saves runtime profiles locally under `~/.config/streamdeck-studio/`. Button targets can contain private file paths, URLs, commands, pasted text, or other sensitive values. Do not commit or share local profile JSON, exported profiles, or copied profile assets unless you have reviewed and sanitized them first.

## Device permissions

If the app reports `Could not open HID device`, install the included udev rule:

```bash
sudo cp packaging/udev/70-streamdeck-studio.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

Then unplug and reconnect the Stream Deck, or log out and back in.

## Text Paste Actions

Text actions copy the configured text to the clipboard and then paste it into the focused app. On GNOME/Wayland this needs `ydotool`:

```bash
sudo pacman -S --needed ydotool
systemctl --user enable --now ydotool.service
```

If paste still fails after installing, log out and back in so the package's uinput device rule is applied.

## Import from macOS Stream Deck

For a single profile on the Mac:

1. Open the Elgato Stream Deck app.
2. Use the profile dropdown under the device name.
3. Choose `Edit Profiles`.
4. Right-click the profile and choose `Export`.
5. Move the resulting `.streamDeckProfile` file to this Linux machine.
6. In Cozmik Studio, press `Import` and select that file.

For all profiles on the Mac:

1. Open Stream Deck settings.
2. Go to the `Profiles` tab.
3. Use `Backup All` -> `Create Backup...`.
4. Move the `.StreamDeckProfilesBackup` file to this Linux machine.
5. In Cozmik Studio, press `Import` and select that file.

The importer maps basic URL, file/open, and text actions. Plugin-specific actions, hotkeys, multi-actions, scripts, and linked external assets may need to be recreated or adjusted on Linux.
