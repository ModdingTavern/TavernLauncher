"""
window.api: the supported way for an addon to talk to TavernKeeper.

    def build_tab(parent, window):
        api = window.api
        api.on_connected(lambda: api.log("hello", "ok"))
        api.run("player list", lambda r: api.log(r.error or str(r.value)))

Everything here runs on the Tk thread. A tab's build function runs again when
the user reorders tabs, so handlers and toolbar buttons added while a tab builds
are cleared before it builds again, and it can just add them every time.
"""
from collections import namedtuple

Player = namedtuple("Player", "id name")

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
        self._building = False
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
        return list(self._w._roster)

    @property
    def target(self):
        """The target player as Player(id, name), or None. id is None for a typed name."""
        var = getattr(self._w, "v_target", None)
        name = var.get().strip() if var is not None else ""
        if not name:
            return None
        for player in self._w._roster:
            if player.name == name:
                return player
        return Player(None, name)

    @property
    def selection(self):
        """Entity ids in the chosen group or ticked in Find & Select. Empty
        means commands act on whatever the server has selected."""
        if not hasattr(self._w, "_group_combo_var"):
            return []
        return list(self._w._active_entity_ids() or [])

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
        if self._building:
            self._buttons.append(button)
        return button

    # Called by the window

    def _add(self, event, fn):
        self._handlers[event].append((fn, self._building))
        return fn

    def _fire(self, event, *args):
        for fn, _ in list(self._handlers[event]):
            try:
                fn(*args)
            except Exception as e:
                self.log(f"[Addon error in on_{event}: {e}]", "err")
                self._w._report_exception()

    def _begin_build(self):
        for event, handlers in self._handlers.items():
            self._handlers[event] = [h for h in handlers if not h[1]]
        for button in self._buttons:
            button.destroy()
        self._buttons = []
        self._building = True

    def _end_build(self):
        self._building = False

    def _ui_ready(self):
        pending, self._pending_log = self._pending_log, []
        for text, tone in pending:
            self.log(text, tone)

    def _target_written(self):
        target = self.target
        if target != self._last_target:
            self._last_target = target
            self._fire("target_changed", target)
