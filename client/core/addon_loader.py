"""
client/core/addon_loader.py -- replaces the build-time "import
client.core._enabled_addons" with a runtime scan + dynamic load, so
which addons run is a *user* choice made in the running app, not a
choice baked in at PyInstaller build time.
"""
import os
import sys
import json
import importlib
import traceback

from tavern_shared.paths import _tavern_data_dir


def addons_dir():
    """The addons/ folder is expected to sit next to the running .exe --
    same convention Patch/ already uses via _app_dir(). In a frozen
    PyInstaller build, sys.executable IS the .exe itself; in dev (running
    client/main.py directly), it's the folder this whole project lives in."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "addons")


def _enabled_addons_file():
    # Deliberately separate from server's equivalent file -- someone
    # running both client.exe and server.exe on the same machine (e.g.
    # to test-join their own server) might reasonably want a different
    # addon set on each side. If they DO want them in sync, that's just
    # ticking the same boxes in both Addons windows; nothing forces it.
    return os.path.join(_tavern_data_dir(), "client_enabled_addons.json")


def discover_addons():
    """Every addon subfolder actually present on disk right now -- this
    is "what's available", independent of what's currently turned on."""
    d = addons_dir()
    if not os.path.isdir(d):
        return []
    return sorted(
        name for name in os.listdir(d)
        if os.path.isdir(os.path.join(d, name)) and not name.startswith("_")
    )


def load_enabled_addon_names():
    """What the user has actually chosen to enable, via the Addons window
    (see addon_manager.py) -- persisted independently of which specific
    addons happen to exist on disk, so re-enabling one you'd previously
    turned off (without ever having removed the folder) doesn't require
    re-discovering/re-checking it."""
    try:
        with open(_enabled_addons_file(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data) if isinstance(data, list) else set()
    except Exception:
        return set()


def save_enabled_addon_names(names):
    try:
        os.makedirs(os.path.dirname(_enabled_addons_file()), exist_ok=True)
        with open(_enabled_addons_file(), "w", encoding="utf-8") as f:
            json.dump(sorted(names), f, indent=2)
    except Exception:
        pass


# Addons that are part of the launcher now. Loading one as well would add a second tab or button.
BUILT_IN = {
    "prefabloader": "Prefab Loader is built into TavernKeeper now as its Prefabs tab, so the addon was not loaded. "
                    "You can delete the addons/prefabloader folder.",
    "mainmenu": "The Main Menu button is built into the launcher now, so the addon was not loaded. "
                "You can delete the addons/mainmenu folder.",
}

# What happened to each enabled addon at startup, for the Addons window:
# name -> {"state": "loaded" | "failed" | "built_in" | "nothing", "message", "detail"}
LOAD_RESULTS = {}


def load_enabled_addons(side, log_error):
    """Loads addons/<name>/<side>.py for every enabled addon that has a
    file for this side. Uses normal importlib.import_module (addons/ is
    a real package), so multi-file addons work correctly too."""
    enabled = load_enabled_addon_names()
    d = addons_dir()
    parent = os.path.dirname(d)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for name in discover_addons():
        if name not in enabled:
            continue
        if name in BUILT_IN:
            log_error(BUILT_IN[name])
            LOAD_RESULTS[name] = {"state": "built_in", "message": BUILT_IN[name], "detail": ""}
            continue
        file_path = os.path.join(d, name, f"{side}.py")
        if not os.path.isfile(file_path):
            LOAD_RESULTS[name] = {"state": "nothing", "message": f"Has no {side}.py, so there is nothing to load here.",
                                  "detail": ""}
            continue
        try:
            importlib.import_module(f"addons.{name}.{side}")
            LOAD_RESULTS[name] = {"state": "loaded", "message": "Loaded.", "detail": ""}
        except Exception as e:
            detail = traceback.format_exc()
            log_error(f"Failed to load addon '{name}' ({side}.py):\n{detail}")
            LOAD_RESULTS[name] = {"state": "failed", "message": f"Failed to load: {type(e).__name__}: {e}",
                                  "detail": detail}
