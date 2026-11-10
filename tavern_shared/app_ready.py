"""
register_app_ready(fn): fn(app) runs once the launcher window is fully
built (addon buttons and tabs included), in the Client and the Server
launcher alike. An addon that needs the window registers here instead of
wrapping _finish_dark_window, theme._btn or Tk.mainloop to find it.
"""
_ready = []


def register_app_ready(fn):
    _ready.append(fn)


def run_app_ready(app, log_fn):
    """A hook that raises is reported in the launcher's log; the others still run."""
    for fn in list(_ready):
        try:
            fn(app)
        except Exception as e:
            name = getattr(fn, "__module__", None) or getattr(fn, "__name__", "addon")
            log_fn(f"[{name}] app-ready hook failed: {e}", "err")
