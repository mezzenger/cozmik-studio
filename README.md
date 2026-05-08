# Stream Deck Studio

A GNOME/GTK desktop app for assigning Stream Deck buttons to launcher actions.

Current capabilities:

- Detect and connect to the first attached Stream Deck.
- Edit button label, subtitle, colors, and action type.
- Generate button images and apply them to the device.
- Run launchers from a physical key release or the app's Run button.
- Import native JSON profiles and best-effort Elgato `.streamDeckProfile` or `.StreamDeckProfilesBackup` exports.
- Save the active profile to `~/.config/streamdeck-studio/profile.json`.

Supported launcher actions:

- `command`: run an executable with arguments without shell expansion.
- `shell`: run a command through the shell for pipes, redirects, and shell expansion.
- `url`: open a website in the default browser.
- `file`: open a file or folder with `xdg-open`.
- `text`: copy stored text to the desktop clipboard.

Run it from this checkout:

```bash
python3 -m streamdeck_studio
```

Install a user-local command and desktop launcher:

```bash
./scripts/install-user.sh
```

If the device is not accessible, the app still opens as an offline editor. On Linux, Stream Deck access usually requires the current user to have permission to the HID device through udev rules.

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
6. In Stream Deck Studio, press `Import` and select that file.

For all profiles on the Mac:

1. Open Stream Deck settings.
2. Go to the `Profiles` tab.
3. Use `Backup All` -> `Create Backup...`.
4. Move the `.StreamDeckProfilesBackup` file to this Linux machine.
5. In Stream Deck Studio, press `Import` and select that file.

The importer maps basic URL, file/open, and text actions. Plugin-specific actions, hotkeys, multi-actions, scripts, and linked external assets may need to be recreated or adjusted on Linux.
