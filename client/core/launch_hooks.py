"""
Hooks for addons around a game launch.

Post-auth hooks run after a successful auth handshake and before the game
starts (custom_models syncs asset bundles there). A hook that takes an
is_local argument runs for every server and is told when the server is on
this PC. An older fn(host, log_fn) hook is skipped for this PC: custom_models'
resync clears the CustomAssets folder a local server is reading.

Launch hooks see every game the launcher starts: joins, headless joins, the
main menu, and anything an addon starts through launcher.spawn_game().
"""
import inspect

_hooks = []
_launch_hooks = {}


class LaunchContext:
    """One game launch. kind is "join", "headless", "menu" or an addon's own
    word. A before hook may change argv (argv[0] is the game exe) or call
    cancel(reason); an after hook also gets proc."""

    def __init__(self, kind, argv, host=None, port=None, label=None, user=None, platform=None):
        self.kind = kind
        self.argv = list(argv)
        self.host = host
        self.port = port
        self.label = label
        self.user = user
        self.platform = platform
        self.proc = None
        self.cancelled = None

    def cancel(self, reason):
        self.cancelled = str(reason) or "Stopped by an addon."


def register_post_auth_hook(fn):
    """fn(host, log_fn) or fn(host, log_fn, is_local) runs once per join,
    right after "Welcomed as <username>" and before the game starts."""
    _hooks.append(fn)


def register_launch_hook(key, before=None, after=None):
    """before(ctx) runs just before a game starts, after(ctx) once it has.
    Registering the same key again replaces the earlier pair."""
    _launch_hooks[key] = (before, after)


def _takes_is_local(fn):
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(p.name == "is_local" or p.kind == p.VAR_KEYWORD for p in params)


def run_post_auth_hooks(host, log_fn, is_local=False):
    for fn in _hooks:
        if _takes_is_local(fn):
            fn(host, log_fn, is_local=is_local)
        elif not is_local:
            fn(host, log_fn)


def run_launch_hooks(stage, ctx, log_fn):
    """stage is "before" or "after". A hook that raises is reported and
    skipped: only ctx.cancel() stops a launch."""
    for key, (before, after) in list(_launch_hooks.items()):
        fn = before if stage == "before" else after
        if fn is None:
            continue
        try:
            fn(ctx)
        except Exception as e:
            log_fn(f"[{key}] {stage}-launch hook failed: {e}", "err")
        if stage == "before" and ctx.cancelled:
            return
