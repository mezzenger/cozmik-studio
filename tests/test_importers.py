import json
import zipfile

from streamdeck_studio.importers import import_profile


def test_import_native_json_profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "name": "Native",
                "rows": 3,
                "columns": 5,
                "buttons": {"0": {"label": "Docs", "action_type": "url", "target": "https://example.com"}},
            }
        )
    )

    profile = import_profile(path)

    assert profile.get_button(0).label == "Docs"
    assert profile.get_button(0).action_type == "url"


def test_import_elgato_like_zip_profile(tmp_path):
    path = tmp_path / "mac.streamDeckProfile"
    payload = {
        "Actions": [
            {
                "UUID": "com.elgato.streamdeck.system.website",
                "Title": "Docs",
                "Settings": {"URL": "https://example.com"},
                "Position": {"row": 0, "column": 0},
            }
        ]
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(payload))

    profile = import_profile(path)

    assert profile.get_button(0).label == "Docs"
    assert profile.get_button(0).action_type == "url"
    assert profile.get_button(0).target == "https://example.com"


def test_import_elgato_backup_selects_main_profile(tmp_path):
    path = tmp_path / "backup.StreamDeckProfilesBackup"
    secondary = {
        "Name": "Profile 1",
        "Controllers": [
            {
                "Actions": {
                    "0,0": {
                        "UUID": "com.elgato.streamdeck.system.text",
                        "States": [{"Title": "Wrong"}],
                        "Settings": {"Text": "secondary"},
                    }
                }
            }
        ],
    }
    main_root = {"Name": "MAIN"}
    main_page = {
        "Name": "MAIN",
        "Controllers": [
            {
                "Actions": {
                    "0,0": {
                        "UUID": "com.elgato.streamdeck.system.website",
                        "States": [{"Title": "Docs"}],
                        "Settings": {"URL": "https://example.com"},
                    }
                }
            }
        ],
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("SECONDARY.sdProfile/manifest.json", json.dumps(secondary))
        archive.writestr("MAIN.sdProfile/manifest.json", json.dumps(main_root))
        archive.writestr("MAIN.sdProfile/Profiles/MAINPAGE/manifest.json", json.dumps(main_page))

    profile = import_profile(path)

    assert profile.current_page == "MAINPAGE"
    assert profile.get_button(0).label == "Docs"
    assert profile.get_button(0).action_type == "url"


def test_import_elgato_v3_uses_page_order_without_changing_orientation(tmp_path):
    path = tmp_path / "main.streamDeckProfile"
    root = {
        "Name": "MAIN",
        "Pages": {
            "Current": "page-2",
            "Pages": ["page-1", "page-2", "page-3"],
        },
    }
    page_1 = {
        "Controllers": [
            {
                "Actions": {
                    "0,1": {
                        "UUID": "com.elgato.streamdeck.profile.openchild",
                        "States": [{"Title": "Folder"}],
                        "Settings": {"ProfileUUID": "folder-1"},
                    },
                    "4,2": {
                        "UUID": "com.elgato.streamdeck.page.next",
                        "States": [{"Title": "Next Page"}],
                        "Settings": {},
                    },
                }
            }
        ]
    }
    page_2 = {
        "Controllers": [
            {
                "Actions": {
                    "0,2": {
                        "UUID": "com.elgato.streamdeck.page.previous",
                        "States": [{"Title": "Previous Page"}],
                        "Settings": {},
                    }
                }
            }
        ]
    }
    page_3 = {"Controllers": [{"Actions": {}}]}
    folder = {
        "Controllers": [
            {
                "Actions": {
                    "0,0": {
                        "UUID": "com.elgato.streamdeck.profile.backtoparent",
                        "States": [{"Title": "Parent Folder"}],
                        "Settings": {},
                    }
                }
            }
        ]
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ROOT.sdProfile/manifest.json", json.dumps(root))
        archive.writestr("ROOT.sdProfile/Profiles/PAGE-1/manifest.json", json.dumps(page_1))
        archive.writestr("ROOT.sdProfile/Profiles/PAGE-2/manifest.json", json.dumps(page_2))
        archive.writestr("ROOT.sdProfile/Profiles/PAGE-3/manifest.json", json.dumps(page_3))
        archive.writestr("ROOT.sdProfile/Profiles/FOLDER-1/manifest.json", json.dumps(folder))

    profile = import_profile(path)

    assert profile.rows == 3
    assert profile.columns == 5
    assert profile.current_page == "PAGE-2"
    assert profile.pages["PAGE-1"]["5"].label == "Folder"
    assert profile.pages["PAGE-1"]["5"].target == "FOLDER-1"
    assert profile.pages["PAGE-1"]["14"].target == "PAGE-2"
    assert profile.pages["PAGE-2"]["10"].target == "PAGE-1"
    assert profile.pages["FOLDER-1"]["0"].target == "PAGE-1"


def test_import_elgato_multimedia_and_known_hotkeys(tmp_path):
    path = tmp_path / "main.streamDeckProfile"
    payload = {
        "Controllers": [
            {
                "Actions": {
                    "0,0": {
                        "UUID": "com.elgato.streamdeck.system.multimedia",
                        "States": [{"Title": "Multimedia"}],
                        "Settings": {"actionIdx": 5},
                    },
                    "1,0": {
                        "UUID": "com.elgato.streamdeck.system.hotkey",
                        "States": [{"Title": "Screen Shot"}],
                        "Settings": {"Hotkeys": []},
                    },
                    "2,0": {
                        "UUID": "com.elgato.streamdeck.system.hotkey",
                        "States": [{"Title": "Emoji Keyboard"}],
                        "Settings": {"Hotkeys": []},
                    },
                }
            }
        ]
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(payload))

    profile = import_profile(path)

    assert profile.get_button(0).label == "Volume Up"
    assert profile.get_button(0).action_type == "media"
    assert profile.get_button(0).target == "volume-up"
    assert profile.get_button(1).action_type == "command"
    assert profile.get_button(1).target == "gnome-screenshot -i"
    assert profile.get_button(2).action_type == "shortcut"
    assert profile.get_button(2).target == "ctrl+period"


def test_import_elgato_state_image_as_action_image(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    path = tmp_path / "main.streamDeckProfile"
    image_bytes = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    payload = {
        "Controllers": [
            {
                "Actions": {
                    "0,0": {
                        "UUID": "com.elgato.streamdeck.system.website",
                        "States": [{"Title": "Docs", "Image": "Images/icon.png"}],
                        "Settings": {"URL": "https://example.com"},
                    }
                }
            }
        ]
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(payload))
        archive.writestr("Images/icon.png", image_bytes)

    profile = import_profile(path)

    assert profile.get_button(0).image_path == ""
    assert profile.get_button(0).action_image_path.endswith("icon.png")
