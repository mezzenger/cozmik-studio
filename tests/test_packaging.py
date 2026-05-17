from pathlib import Path
import tomllib


def test_bundled_screensavers_are_package_data():
    project = tomllib.loads(Path("pyproject.toml").read_text())
    package_data = project["tool"]["setuptools"]["package-data"]["streamdeck_studio"]

    assert "resources/screensavers/*" in package_data


def test_package_discovery_is_limited_to_app_package():
    project = tomllib.loads(Path("pyproject.toml").read_text())

    assert project["tool"]["setuptools"]["packages"]["find"]["include"] == ["streamdeck_studio*"]


def test_bundled_screensaver_gifs_live_in_package_resources():
    screensavers = Path("streamdeck_studio/resources/screensavers")

    assert sorted(path.name for path in screensavers.glob("*.gif")) == [
        "cozmik_audio_wave_idle.gif",
        "cozmik_comet_resting_idle.gif",
        "cozmik_neon_grid_idle.gif",
        "cozmik_orbit_buttons_idle.gif",
        "cozmik_starfield_idle.gif",
        "cozmik_terminal_rain_idle.gif",
    ]
