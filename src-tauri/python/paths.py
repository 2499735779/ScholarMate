"""Resolve where ScholarMate keeps its files.

The location file lives in the operating system's configuration directory, which
never moves, so the database and the PDF folders can live on any drive the user
picks. Nothing here writes to the data directory itself.
"""

import json
import os
from pathlib import Path

import platformdirs

APP = "com.scholarmate.desktop"
# The launcher passes the same directory Tauri uses, so both sides always agree.
# Roaming matches Tauri's app_config_dir on Windows; the setting is ignored on
# macOS and Linux, where the platform paths already line up.
CONFIG_DIR = Path(
    os.environ.get("SCHOLARMATE_CONFIG_DIR")
    or platformdirs.PlatformDirs(APP, appauthor=False, roaming=True).user_config_dir
)
LOCATION_FILE = CONFIG_DIR / "storage.json"
APP_DIRS = platformdirs.PlatformDirs("ScholarMate", appauthor=False)


def default_data_dir():
    return Path(APP_DIRS.user_data_dir)


def downloads_dir():
    folder = Path(platformdirs.user_downloads_dir())
    return folder if folder.is_dir() else Path.home() / "Downloads"


def default_download_dir():
    return downloads_dir() / "ScholarMate"


def location():
    try:
        saved = json.loads(LOCATION_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return saved if isinstance(saved, dict) else {}


def write_location(**values):
    saved = location()
    for key, value in values.items():
        text = str(value or "").strip()
        if text:
            saved[key] = text
        else:
            saved.pop(key, None)
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        LOCATION_FILE.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass  # A read-only config directory must not break the running app.
    return saved


def mounted(path):
    """A path on an unplugged drive is not usable this session."""
    drive = Path(path).drive
    return not drive or Path(drive + os.sep).exists()


def scheduled(key, fallback):
    saved = str(location().get(key) or "").strip()
    if not saved:
        return fallback()
    candidate = Path(saved)
    return candidate if mounted(candidate) else fallback()


def data_dir():
    override = os.environ.get("SCHOLARMATE_DATA_DIR")
    if override:
        return Path(override)
    return scheduled("data_dir", default_data_dir)


def download_dir():
    return scheduled("download_dir", default_download_dir)


def system_drive():
    return (os.environ.get("SystemDrive") or Path.home().anchor.rstrip("\\/") or "C:") + os.sep

