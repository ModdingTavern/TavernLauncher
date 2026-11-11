"""Optional client add-on hooks, registered before ClientLauncher is created.

Buttons are placed by key, never by their text. Built-in keys: patch and
mods (row "mods"); saved, community, tickets, remote_console and
tavernkeeper (row "servers"); check, join and menu (the main row). An
addon's own key works as an after= target for the next addon.
launcher.button(key) returns any of these buttons once the window exists.
register_app_ready(fn) calls fn(launcher) once the window is fully built.
"""
from tavern_shared.app_ready import register_app_ready  # noqa: F401  (re-exported for addons)
_actions = {}
_main_buttons = {}
_before_launch = {}


def register_launcher_action(key, label, callback, after=None, row="servers"):
    """callback(launcher). A small button, at the end of its row unless
    after= names a button in that row. row is "servers" (under Destination)
    or "mods" (beside Patch and Mods)."""
    _actions[key] = (label, callback, row, after)


def register_main_button(key, label, command, after=None):
    """command(launcher). A big button in the row with Check Server and
    Join Server, at the end unless after= names one there."""
    _main_buttons[key] = (label, command, after)


def register_before_launch_hook(key, callback):
    """callback(host, game_exe, log_fn), after validation/auth and before Popen.

    Runs on the launcher's own thread for normal and headless joins, including
    localhost; not for the main menu. An optional add-on failure is reported
    without preventing the game launch. launch_hooks.register_launch_hook sees
    every launch, gets the arguments and the process, and can stop a launch.
    """
    _before_launch[key] = callback


def _guarded(key, fn, launcher):
    def run():
        try:
            fn(launcher)
        except Exception as e:
            launcher._print(f"[{key}] {e}", "err")
    return run


def build_launcher_actions(launcher):
    """Makes every addon button, then packs each one after its target once
    that target is in place. A target that is missing, hidden or in another
    row puts the button at the end of its own row."""
    from tavern_shared.theme import _btn
    rows, named = launcher._button_rows, launcher._named_buttons
    todo = []
    for key, (label, callback, row, after) in list(_actions.items()):
        b = _btn(rows.get(row, rows["servers"]), label, _guarded(key, callback, launcher),
                 font=("Segoe UI", 9), pady=5, padx=10)
        todo.append((key, b, after, {"side": "left", "padx": (6, 0)}))
    for key, (label, command, after) in list(_main_buttons.items()):
        b = _btn(rows["main"], label, _guarded(key, command, launcher),
                 font=("Georgia", 12, "bold"), pady=14)
        todo.append((key, b, after, {"side": "left", "fill": "x", "expand": True, "padx": (4, 0)}))
    for key, b, _, _ in todo:
        named.setdefault(key, b)
    while todo:
        placed = False
        for item in list(todo):
            key, b, after, opts = item
            target = named.get(after) if after else None
            if after and (target is None or target.master is not b.master):
                continue
            if target is not None and target.winfo_manager() != "pack":
                continue
            b.pack(after=target, **opts) if target is not None else b.pack(**opts)
            todo.remove(item)
            placed = True
        if not placed:
            for key, b, _, opts in todo:
                b.pack(**opts)
            break


def run_before_launch_hooks(host, game_exe, log_fn):
    for key, callback in list(_before_launch.items()):
        try:
            callback(host, game_exe, log_fn)
        except Exception:
            # Add-ons can handle their own detailed errors. Do not log credentials.
            log_fn("[" + key + "] Could not prepare the add-on. Open its settings and reconnect.")
