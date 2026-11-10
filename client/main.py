"""
Client launcher entry point. Loads whichever addons the user has
actually enabled (see the in-app Addons window / client/core/
addon_loader.py) BEFORE building the main window, so every enabled
addon has already registered its tabs/hooks by the time
ClientLauncher._build_ui() runs. Hooks that need the finished window use
tavern_shared.app_ready.register_app_ready.

Addons are no longer baked in at build time -- this .exe is always
"core only"; addons/ is a plain folder of .py files expected to sit
right next to it, loaded dynamically at startup based on what's saved
in client_enabled_addons.json.
"""
import sys
import os
import threading
import traceback

# So `import tavern_shared`, `import client.core...` all resolve
# regardless of the exe's own working directory.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _addon_log_path():
    base = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
    path = os.path.join(base, "TheModdingTavern")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return os.path.join(path, "addon_load_errors.log")


def _write_error_log(err_text):
    # sys.stderr is None in a --windowed PyInstaller build (no console
    # attached) -- writing to it unconditionally raises its own
    # AttributeError before ever reaching the actual file write.
    if sys.stderr is not None:
        try:
            sys.stderr.write(err_text)
        except Exception:
            pass
    try:
        with open(_addon_log_path(), "a", encoding="utf-8") as f:
            f.write(err_text + "\n")
    except Exception:
        pass


def _log_thread_exception(args):
    # A crash in a background thread (ticket polling, a launch, the
    # console client) otherwise vanishes without a trace in a windowed build.
    if args.exc_type is SystemExit:
        return
    name = args.thread.name if args.thread is not None else "?"
    _write_error_log(f"Uncaught error in thread {name}:\n" + "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)))


threading.excepthook = _log_thread_exception

from client.core import addon_loader
addon_loader.load_enabled_addons("client", _write_error_log)

from client.core.launcher_window import ClientLauncher, _updater

if __name__ == "__main__":
    if _updater is not None:
        _updater.finish_update_if_requested()  # never returns if this launch is finishing an update
        _updater.cleanup_previous_update()
    app = ClientLauncher()

    # Tkinter catches exceptions raised inside ANY callback (button
    # clicks, window construction triggered by one, etc.) with its own
    # default handler, which just prints to stderr -- invisible in a
    # --windowed build. Routing it through the same log file closes
    # that gap for anything happening after startup too.
    def _log_callback_exception(exc, val, tb):
        _write_error_log("".join(traceback.format_exception(exc, val, tb)))
    app.report_callback_exception = _log_callback_exception

    app.mainloop()
