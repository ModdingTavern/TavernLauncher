"""Optional client add-on hooks, registered before ClientLauncher is created."""
_actions = {}
_before_launch = {}


def register_launcher_action(key, label, callback):
    """callback(launcher); enabling an add-on adds its button to the main launcher."""
    _actions[key] = (label, callback)


def register_before_launch_hook(key, callback):
    """callback(host, game_exe, log_fn), after validation/auth and before Popen.

    Runs in the launch worker for normal and headless joins, including localhost.
    An optional add-on failure is reported without preventing the game launch.
    """
    _before_launch[key] = callback


def build_launcher_actions(parent, launcher):
    from tavern_shared.theme import _btn
    for label, callback in list(_actions.values()):
        _btn(parent, label, lambda cb=callback: cb(launcher),
             font=("Segoe UI", 9), pady=5, padx=10).pack(side="left", padx=(6, 0))


def run_before_launch_hooks(host, game_exe, log_fn):
    for key, callback in list(_before_launch.items()):
        try:
            callback(host, game_exe, log_fn)
        except Exception:
            # Add-ons can handle their own detailed errors. Do not log credentials.
            log_fn("[" + key + "] Could not prepare the add-on. Open its settings and reconnect.")
