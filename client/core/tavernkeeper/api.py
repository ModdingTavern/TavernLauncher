"""
window.api: the supported way for an addon to talk to TavernKeeper.

    def build_tab(parent, window):
        api = window.api
        api.on_connected(lambda: api.log("hello", "ok"))
        api.run("player list", lambda r: api.log(r.error or str(r.value)))

Everything here runs on the Tk thread. A tab is built once, when TavernKeeper
connects; Reorder Tabs only moves it. A tab whose build raises shows an error
card instead, and the handlers and toolbar buttons it added are removed.
"""
from client.core.tavernkeeper.models import Player

TONES = {"ok": "ok", "warn": "warn", "err": "err", "cyan": "cyan", "normal": ""}


class Result:
    """What a console command came back with.

    ok         the server answered and reported no error
    value      the command's structured result, or None
    text       the server's reply text, "" when it was only a type name
    error      why it failed, None when ok
    timed_out  no answer arrived in time
    void       ok, and the command had nothing to return
    raw        the reply text as sent, None when the command never went out
    """

    __slots__ = ("ok", "value", "text", "error", "timed_out", "void", "raw")

    def __init__(self, raw, value, error, timed_out=False):
        self.raw = raw
        self.value = value
        self.error = error
        self.timed_out = timed_out
        self.ok = error is None and not timed_out
        self.text = "" if raw is None or raw.startswith("System.") else raw
        self.void = self.ok and value in (None, "") and self.text in ("", "Success")

    @classmethod
    def from_reply(cls, reply):
        return cls(reply["result_string"], reply["result_data"], reply["error"], reply["timed_out"])

    @classmethod
    def failed(cls, reason):
        return cls(None, None, reason)

    def __repr__(self):
        return (f"Result(ok={self.ok}, value={self.value!r}, text={self.text!r}, "
                f"error={self.error!r}, timed_out={self.timed_out}, void={self.void})")


class TavernKeeperApi:
    def __init__(self, window):
        self._w = window
        self._handlers = {"connected": [], "disconnected": [], "target_changed": []}
        self._buttons = []
        self._build_start = None
        self._last_target = None
        self._pending_log = []

    # Commands

    def send(self, cmd):
        """Send without waiting for the answer. False if it could not be sent."""
        return self._w._send(cmd)

    def run(self, cmd, on_result, timeout=20.0, quiet=False):
        """Send and call on_result(Result). quiet keeps it out of the log."""
        self._w._run_command(cmd, on_result, timeout=timeout, quiet=quiet)

    def log(self, text, tone="normal"):
        """Write a line to the console output. Tones: normal, ok, warn, err, cyan."""
        if not text.endswith("\n"):
            text += "\n"
        if hasattr(self._w, "out"):
            self._w._append_log(text, TONES.get(tone, ""))
        else:
            self._pending_log.append((text, tone))

    # State

    @property
    def is_connected(self):
        return self._w._connected

    @property
    def players(self):
        """The last player list, as Player(id, name). id is None if the server gave none."""
        return list(self._w.models.roster.players)

    @property
    def target(self):
        """The target player as Player(id, name), or None. id is None for a typed name."""
        var = getattr(self._w, "v_target", None)
        name = var.get().strip() if var is not None else ""
        if not name:
            return None
        return self._w.models.roster.find(name) or Player(None, name)

    @property
    def selection(self):
        """Entity ids the Build tab is working on: its chosen group, else the
        ticked rows, else the one object selected. Empty if there is none."""
        selection = self._w.models.selection
        if selection.active_ids():
            return list(selection.active_ids())
        return [selection.current[0]] if selection.current else []

    # Events

    def on_connected(self, fn):
        """fn() after connecting and after every reconnect."""
        return self._add("connected", fn)

    def on_disconnected(self, fn):
        """fn(reason) when the connection is lost."""
        return self._add("disconnected", fn)

    def on_target_changed(self, fn):
        """fn(target) when the target player changes. target can be None."""
        return self._add("target_changed", fn)

    # Toolbar

    def add_toolbar_button(self, text, command, style="normal"):
        """Add a button to the header bar. Call it from a tab's build function."""
        from tavern_shared.theme import _btn
        if not hasattr(self._w, "_toolbar"):
            raise RuntimeError("the toolbar exists only once TavernKeeper is connected")
        button = _btn(self._w._toolbar, text, command, style, font=("Segoe UI", 8), pady=3, padx=8)
        button.pack(side="left", padx=(0, 8))
        if self._build_start is not None:
            self._buttons.append(button)
        return button

    # Called by the window

    def _add(self, event, fn):
        self._handlers[event].append(fn)
        return fn

    def _fire(self, event, *args):
        for fn in list(self._handlers[event]):
            try:
                fn(*args)
            except Exception as e:
                self.log(f"[Addon error in on_{event}: {e}]", "err")
                self._w._report_exception()

    def _begin_build(self):
        self._build_start = {event: len(fns) for event, fns in self._handlers.items()}
        self._buttons = []

    def _end_build(self, failed=False):
        if failed:
            for event, count in self._build_start.items():
                del self._handlers[event][count:]
            for button in self._buttons:
                button.destroy()
        self._build_start = None
        self._buttons = []

    def _ui_ready(self):
        pending, self._pending_log = self._pending_log, []
        for text, tone in pending:
            self.log(text, tone)

    def _target_written(self):
        target = self.target
        if target != self._last_target:
            self._last_target = target
            self._fire("target_changed", target)
