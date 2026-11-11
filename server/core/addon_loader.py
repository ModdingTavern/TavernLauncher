"""
server/core/addon_loader.py -- identical mechanism to
client/core/addon_loader.py (kept as two separate small files rather
than one shared one purely so each side's addons_dir() can compute its
own "next to THIS .exe" path independently without either side needing
to import anything from the other's package tree).
"""
import os
import sys
import json
import importlib
import traceback

from tavern_shared.paths import _tavern_data_dir


def addons_dir():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "addons")


def _enabled_addons_file():
    # See client/core/addon_loader.py's identical comment -- kept
    # separate deliberately.
    return os.path.join(_tavern_data_dir(), "server_enabled_addons.json")


def discover_addons():
    d = addons_dir()
    if not os.path.isdir(d):
        return []
    return sorted(
        name for name in os.listdir(d)
        if os.path.isdir(os.path.join(d, name)) and not name.startswith("_")
    )


def load_enabled_addon_names():
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


# What happened to each enabled addon at startup, for the Addons window:
# name -> {"state": "loaded" | "failed" | "nothing", "message", "detail"}
LOAD_RESULTS = {}


def load_enabled_addons(side, log_error):
    enabled = load_enabled_addon_names()
    d = addons_dir()
    parent = os.path.dirname(d)
    if parent not in sys.path:
        sys.path.insert(0, parent)

    for name in discover_addons():
        if name not in enabled:
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
