"""Console tokens: named tokens for moderators, bots and tools, each with its
own list of commands. Everything goes through TavernLib's token commands on
the owner's own console, so the server has to be running. TavernLib keeps
the tokens and enforces them; this window only asks it."""
import datetime
import json
import queue
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, MONO,
    _btn, _mk_scrollbar, _mk_combobox,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.ws_console_client import WsConsoleClient
from tavern_shared.console_commands import CONSOLE_COMMANDS
from server.core.data_store import CONSOLE_TOKEN_FILE

NEVER_GIVEN = ("token", "repeat")
NAMED_ROLES = {"offline", "play_offline", "server_access_pre_alpha", "game_access_public",
               "debug_features", "database_admin", "reuse_refresh_tokens"}
NAME_MAX = 32

VIEWER = ["help", "player list", "player list-detailed", "player detailed", "player count",
          "player list-stats", "player check-stat", "player get-home", "player banlist"]
PRESETS = {
    "moderator": VIEWER + ["player kick", "player ban", "player unban", "player message",
                           "player teleport", "player kill", "player inventory"],
    "builder": VIEWER + ["select", "spawn", "wacky destroy", "player teleport"],
    "viewer": VIEWER,
}
PRESET_LABELS = [("full", "Full admin"), ("moderator", "Moderator"), ("builder", "Builder"),
                 ("viewer", "Viewer"), ("custom", "Custom")]
PRESET_HINTS = {
    "full": "Runs every command but token and repeat, mods' commands included.",
    "moderator": "Sees players, and kicks, bans, messages and teleports them.",
    "builder": "Selects, moves, spawns and removes objects.",
    "viewer": "Looks only: player lists, stats and the ban list.",
    "custom": "Only what is ticked below.",
}
EXPIRY = [("Never", 0), ("1 day", 1), ("7 days", 7), ("30 days", 30), ("90 days", 90), ("1 year", 365)]
KEEP = "Keep as it is"
GLYPH = {"off": "☐", "on": "☑", "some": "▣"}
STATUS_COLORS = {"active": GREEN, "expired": AMBER, "revoked": MUTED}
EVENTS = {"connect": "connected", "disconnect": "left", "command": "ran", "bad_login": "refused login"}


def _never_given(path):
    return any(path == p or path.startswith(p + " ") for p in NEVER_GIVEN)


def _q(text):
    return '"%s"' % text


def _last_line(text):
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _when(value, none="never"):
    if not value:
        return none
    try:
        utc = datetime.datetime.strptime(str(value)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return str(value)
    return utc.replace(tzinfo=datetime.timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")


def _get(part, key):
    if not isinstance(part, dict):
        return None
    return part.get(key, part.get(key[0].lower() + key[1:]))


def _out_of_reach(part):
    """True for what a limited token could never run: client-only commands,
    ones the remote console refuses, and ones that need a role only the
    owner and full tokens carry (server_owner)."""
    for req in _get(part, "Requirements") or []:
        kind = str(_get(req, "TypeId") or "")
        if kind.endswith(("ClientOnlyAttribute", "NotAllowedInRemoteAttribute")):
            return True
        if kind.endswith("WithPermissionOnlyAttribute") and not set(_get(req, "Roles") or []) <= NAMED_ROLES:
            return True
    return False


def _answer(res):
    """(text, problem) from a console reply. A refusal is a problem."""
    if res.get("error"):
        return "", res["error"]
    text = res.get("result_string") or ""
    if isinstance(res.get("result_data"), str):
        text = res["result_data"]
    if text.startswith("Refused:"):
        return "", text[len("Refused:"):].strip()
    return text, None


class _Node:
    def __init__(self, path, name, desc, parent):
        self.path, self.name, self.desc, self.parent = path, name, desc or "", parent
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()


class CommandTree:
    """The server's commands as modules and commands, and which are ticked.
    A ticked module gives everything in it, commands a mod adds later too."""

    def __init__(self, roots):
        self.roots = sorted(roots, key=lambda n: n.name)
        self.index = {n.path: n for r in self.roots for n in r.walk()}
        self.on = dict.fromkeys(self.index, False)

    @classmethod
    def from_modules(cls, modules):
        def walk(module, parent):
            name = (_get(module, "Name") or "").strip().lower()
            if not name or _out_of_reach(module):
                return None
            path = name if parent is None else parent.path + " " + name
            if _never_given(path):
                return None
            node = _Node(path, name, _get(module, "Description"), parent)
            kids = {}
            for command in _get(module, "Commands") or []:
                cname = (_get(command, "Name") or "").strip().lower()
                if cname and not _out_of_reach(command) and not _never_given(path + " " + cname):
                    kids[cname] = _Node(path + " " + cname, cname, _get(command, "Description"), node)
            for sub in _get(module, "Submodules") or []:
                child = walk(sub, node)
                if child:
                    same = kids.get(child.name)
                    if same and not child.desc:
                        child.desc = same.desc
                    kids[child.name] = child
            node.children = sorted(kids.values(), key=lambda n: n.name)
            return node
        return cls([n for n in (walk(m, None) for m in modules or []) if n])

    @classmethod
    def from_paths(cls, paths):
        """Fallback when the server can't list its commands: the launcher's own list."""
        nodes = {}
        for path in sorted(paths, key=lambda p: p.count(" ")):
            words = path.split(" ")
            for i in range(1, len(words) + 1):
                sub = " ".join(words[:i])
                if sub not in nodes and not _never_given(sub):
                    parent = nodes.get(" ".join(words[:i - 1])) if i > 1 else None
                    if i > 1 and parent is None:
                        break
                    nodes[sub] = _Node(sub, words[i - 1], "", parent)
                    if parent:
                        parent.children.append(nodes[sub])
        for n in nodes.values():
            n.children.sort(key=lambda c: c.name)
        return cls([n for n in nodes.values() if n.parent is None])

    def state(self, node):
        if self.on[node.path]:
            return "on"
        if any(self.on[d.path] for d in node.walk()):
            return "some"
        return "off"

    def _settle(self, node):
        if node.children:
            for child in node.children:
                self._settle(child)
            self.on[node.path] = all(self.on[c.path] for c in node.children)

    def load(self, paths):
        """Ticks these paths. Returns the ones this server doesn't have."""
        self.on = dict.fromkeys(self.index, False)
        missing = []
        for path in paths:
            node = self.index.get(" ".join(path.lower().split()))
            if node is None:
                missing.append(path)
                continue
            for d in node.walk():
                self.on[d.path] = True
        for root in self.roots:
            self._settle(root)
        return missing

    def set(self, node, value):
        for d in node.walk():
            self.on[d.path] = value
        up = node.parent
        while up is not None:
            self.on[up.path] = all(self.on[c.path] for c in up.children)
            up = up.parent

    def toggle(self, node):
        self.set(node, not self.on[node.path])

    def granted(self):
        out = []

        def walk(node):
            if self.on[node.path]:
                out.append(node.path)
            else:
                for child in node.children:
                    walk(child)
        for root in self.roots:
            walk(root)
        return out

    def preset_paths(self, key):
        """A preset's paths as this server would store them."""
        saved = dict(self.on)
        self.load([p for p in PRESETS.get(key, []) if p in self.index])
        out = self.granted()
        self.on = saved
        return out


class TokensWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Console Tokens")
        self.configure(bg=BG)
        self.geometry("940x660")
        self.minsize(820, 560)
        self.resizable(True, True)
        _set_window_icon(self)
        if ttk.Style().theme_use() != "clam":
            ttk.Style().theme_use("clam")
        self._client = None
        self._closed = False
        self._busy = False
        self._tree = None
        self._tree_locked = False
        self._tokens = {}
        self._selected = None
        self._mode = "none"
        self._dirty = False
        self._missing = []
        self._log_win = None
        self._jobs = queue.Queue()
        self._results = queue.Queue()
        threading.Thread(target=self._work, daemon=True).start()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _finish_dark_window(self)
        self._poll()
        self._connect()

    # ---- console ------------------------------------------------------------

    def _work(self):
        """Runs console requests one at a time off the Tk thread. Answers go
        back through a queue that _poll empties on the Tk thread."""
        while True:
            job = self._jobs.get()
            if job is None:
                return
            fn, done = job
            try:
                result = fn()
            except Exception as e:
                result = {"error": str(e) or type(e).__name__}
            self._results.put((done, result))

    def _poll(self):
        if self._closed:
            return
        while True:
            try:
                done, result = self._results.get_nowait()
            except queue.Empty:
                break
            done(result)
        self.after(50, self._poll)

    def ask(self, cmd, done, timeout=30):
        client = self._client
        if client is None:
            done({"error": "Not connected"})
            return
        self._jobs.put((lambda: client.request(cmd, timeout=timeout, show=False), done))

    def _connect(self):
        self._set_connection("Connecting…", MUTED, False)
        try:
            with open(CONSOLE_TOKEN_FILE) as f:
                token = f.read().strip()
        except OSError:
            self._offline("No console token yet. Open the server, then press Reconnect.")
            return
        client = WsConsoleClient()

        def go():
            ok, msg = client.connect("127.0.0.1", token, on_disc=lambda reason: self._results.put(
                (lambda r: self._on_lost(client, r), reason)))
            return {"ok": ok, "msg": msg}

        def done(res):
            if not res.get("ok"):
                client.disconnect()
                self._offline("Can't reach the server's console (%s). Open the server, then press Reconnect."
                              % (res.get("msg") or res.get("error")))
                return
            self._client = client
            self.ask("token whoami", self._on_whoami)
        self._jobs.put((go, done))

    def _on_whoami(self, res):
        data = res.get("result_data")
        if not isinstance(data, dict) or data.get("id") != "owner":
            text, problem = _answer(res)
            if not problem and isinstance(data, dict):
                problem = "console_token.txt isn't the owner token"
            self._offline("This server can't manage named tokens: %s. They need TavernLib 1.5.4 or newer."
                          % (problem or text or "no answer"))
            return
        self._set_connection("● Connected", GREEN, True)
        self.ask("help modules", self._on_modules, timeout=60)

    def _on_modules(self, res):
        data = res.get("result_data")
        tree = CommandTree.from_modules(data) if isinstance(data, list) else None
        if tree is None or not tree.roots:
            tree = CommandTree.from_paths(CONSOLE_COMMANDS.keys())
            self._say("The server didn't list its commands, so mods' commands are missing from the list.", AMBER)
        self._tree = tree
        self._refresh_list(select="owner")

    def _on_lost(self, client, reason):
        if client is self._client:
            self._client = None
            self._offline("Lost the server's console (%s). Open the server, then press Reconnect." % reason)

    def _offline(self, message):
        if self._client is not None:
            self._client.disconnect()
            self._client = None
        self._set_connection("Offline", MUTED, False)
        self._say(message, RED)
        self._tokens = {}
        self._selected = None
        self._dirty = False
        self._list.delete(*self._list.get_children())
        self._set_mode("none")
        self._title_var.set("Not connected")

    def _reconnect(self):
        if self._client is not None:
            self._client.disconnect()
            self._client = None
        self._connect()

    # ---- layout -------------------------------------------------------------

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🔑  Console Tokens", bg=SURF, fg=AMBER,
                 font=("Georgia", 12, "bold")).pack(side="left", padx=16, pady=8)
        self._reconnect_btn = _btn(h, "Reconnect", self._reconnect, font=("Segoe UI", 8), padx=8, pady=2)
        self._conn_var = tk.StringVar(value="")
        self._conn_lbl = tk.Label(h, textvariable=self._conn_var, bg=SURF, fg=MUTED, font=("Segoe UI", 9))
        self._conn_lbl.pack(side="right", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        foot = tk.Frame(self, bg=BG)
        foot.pack(side="bottom", fill="x", padx=14, pady=(0, 10))
        self._msg = tk.Label(foot, text="", bg=BG, fg=MUTED, font=("Segoe UI", 9),
                             anchor="w", justify="left")
        self._msg.pack(fill="x")
        foot.bind("<Configure>", lambda e: self._msg.config(wraplength=max(200, e.width - 8)))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=14, pady=10)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        self._build_list(body)
        self._build_editor(body)

    def _style_tree(self):
        style = ttk.Style()
        style.configure("Tok.Treeview", background=SURF, fieldbackground=SURF, foreground=PARCH,
                        rowheight=24, borderwidth=0, font=("Segoe UI", 9),
                        bordercolor=SURF, lightcolor=SURF, darkcolor=SURF)
        style.configure("Tok.Treeview.Heading", background=SURF2, foreground=AMBER, font=("Georgia", 9, "bold"),
                        relief="flat", bordercolor=BORDER, lightcolor=SURF2, darkcolor=SURF2)
        style.map("Tok.Treeview.Heading", background=[("active", AMBERDIM)])
        style.layout("Tok.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.map("Tok.Treeview", background=[("selected", AMBERDIM)], foreground=[("selected", "#ffd080")])

    def _boxed_tree(self, parent, **kw):
        self._style_tree()
        box = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        tree = ttk.Treeview(box, style="Tok.Treeview", **kw)
        sb = _mk_scrollbar(box, tree.yview)
        sb.pack(side="right", fill="y")
        tree.config(yscrollcommand=sb.set)
        tree.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        return box, tree

    def _build_list(self, body):
        left = tk.Frame(body, bg=BG, width=240)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        left.pack_propagate(False)
        tk.Label(left, text="TOKENS", bg=BG, fg=MUTED, font=("Georgia", 8, "bold")).pack(anchor="w", pady=(0, 4))
        bottom = tk.Frame(left, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self._new_btn = _btn(bottom, "＋ New token", self._new_token, "primary",
                             font=("Segoe UI", 9, "bold"), pady=6)
        self._new_btn.pack(fill="x", pady=(8, 4))
        self._refresh_btn = _btn(bottom, "↻ Refresh", lambda: self._refresh_list(), font=("Segoe UI", 9), pady=5)
        self._refresh_btn.pack(fill="x")
        self.v_show_revoked = tk.BooleanVar(value=False)
        tk.Checkbutton(bottom, text="Show revoked tokens", variable=self.v_show_revoked,
                       command=self._fill_list, bg=BG, fg=MUTED, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER, font=("Segoe UI", 8),
                       highlightthickness=0, bd=0).pack(anchor="w", pady=(6, 0))
        box, self._list = self._boxed_tree(left, columns=("state",), show="tree", selectmode="browse")
        box.pack(fill="both", expand=True)
        self._list.column("#0", width=150, stretch=True)
        self._list.column("state", width=70, stretch=False, anchor="e")
        for status, color in STATUS_COLORS.items():
            self._list.tag_configure(status, foreground=color)
        self._list.tag_configure("owner", foreground=AMBER)
        self._list.bind("<<TreeviewSelect>>", self._on_list_select)

    def _build_editor(self, body):
        right = tk.Frame(body, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        self._editor = right

        top = tk.Frame(right, bg=BG)
        top.pack(fill="x")
        self._title_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._title_var, bg=BG, fg=AMBER,
                 font=("Georgia", 14, "bold"), anchor="w").pack(fill="x")
        self._info_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._info_var, bg=BG, fg=MUTED, font=("Segoe UI", 8),
                 anchor="w", justify="left").pack(fill="x", pady=(0, 6))

        self._name_row = tk.Frame(right, bg=BG)
        tk.Label(self._name_row, text="NAME", bg=BG, fg=MUTED, font=("Georgia", 8, "bold")).pack(anchor="w")
        nf = tk.Frame(self._name_row, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        nf.pack(fill="x", pady=(2, 0))
        self.v_name = tk.StringVar()
        self.v_name.trace_add("write", lambda *_: self._mark_dirty())
        self._name_entry = tk.Entry(nf, textvariable=self.v_name, bg=SURF, fg=PARCH, insertbackground=AMBER,
                                    relief="flat", font=("Segoe UI", 10), bd=5)
        self._name_entry.pack(fill="x")
        tk.Label(self._name_row, text="Who or what it's for, such as a moderator's name. "
                                      "Letters, numbers, spaces, - and _.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(anchor="w")

        self._owner_note = tk.Label(right, bg=BG, fg=PARCH, font=("Segoe UI", 9), justify="left", anchor="w",
                                    text="The owner token runs everything and can't be limited. The launcher and "
                                         "its Console use it, and the header's Copy Console Token copies it.\n\n"
                                         "Give everyone else a named token instead: if one leaks, revoke just that one.")
        self._owner_note.bind("<Configure>", lambda e: self._owner_note.config(wraplength=max(200, e.width - 8)))

        self._access = tk.Frame(right, bg=BG)
        tk.Label(self._access, text="WHAT IT MAY RUN", bg=BG, fg=MUTED,
                 font=("Georgia", 8, "bold")).pack(anchor="w", pady=(8, 2))
        pr = tk.Frame(self._access, bg=BG)
        pr.pack(fill="x")
        self.v_preset = tk.StringVar(value="moderator")
        self._preset_btns = {}
        for key, label in PRESET_LABELS:
            b = tk.Radiobutton(pr, text=label, value=key, variable=self.v_preset, command=self._on_preset,
                               indicatoron=0, bg=SURF2, fg=PARCH, selectcolor=AMBERDIM,
                               activebackground=AMBERDIM, activeforeground="#ffd080",
                               disabledforeground=BORDER, relief="flat", bd=0, padx=10, pady=4,
                               font=("Segoe UI", 9), cursor="hand2", highlightthickness=0)
            b.pack(side="left", padx=(0, 4))
            self._preset_btns[key] = b
        self._preset_hint = tk.Label(self._access, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w")
        self._preset_hint.pack(fill="x", pady=(2, 4))

        sf = tk.Frame(self._access, bg=BG)
        sf.pack(fill="x", pady=(0, 4))
        tk.Label(sf, text="Find", bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="left", padx=(0, 6))
        ff = tk.Frame(sf, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        ff.pack(side="left", fill="x", expand=True)
        self.v_find = tk.StringVar()
        self.v_find.trace_add("write", lambda *_: self._fill_tree())
        tk.Entry(ff, textvariable=self.v_find, bg=SURF, fg=PARCH, insertbackground=AMBER,
                 relief="flat", font=("Segoe UI", 9), bd=4).pack(fill="x")
        _btn(sf, "Tick all", lambda: self._tick_all(True), font=("Segoe UI", 8), padx=8, pady=3).pack(side="left", padx=(6, 0))
        _btn(sf, "Clear", lambda: self._tick_all(False), font=("Segoe UI", 8), padx=8, pady=3).pack(side="left", padx=(4, 0))

        box, self._cmds = self._boxed_tree(self._access, columns=("desc",), show="tree headings",
                                           selectmode="none", height=6)
        box.pack(fill="both", expand=True)
        self._cmds.heading("#0", text="Command", anchor="w")
        self._cmds.heading("desc", text="What it does", anchor="w")
        self._cmds.column("#0", width=230, stretch=False)
        self._cmds.column("desc", width=300, stretch=True)
        self._cmds.tag_configure("module", font=("Segoe UI", 9, "bold"))
        self._cmds.tag_configure("locked", foreground=MUTED)
        self._cmds.bind("<Button-1>", self._on_tree_click)
        self._cmds.bind("<Double-Button-1>", self._on_tree_double)
        self._cmds.bind("<space>", self._on_tree_space)
        self._notes = tk.Label(self._access, text="", bg=BG, fg=AMBER, font=("Segoe UI", 8),
                               anchor="w", justify="left")
        self._notes.pack(fill="x", pady=(4, 0))
        self._notes.bind("<Configure>", lambda e: self._notes.config(wraplength=max(200, e.width - 8)))
        rule = tk.Label(self._access, text="Not listed: token and repeat, and what only the owner and full "
                                           "tokens can run. Changes apply at once: nobody needs a new token "
                                           "after a save.",
                        bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left")
        rule.pack(fill="x")
        rule.bind("<Configure>", lambda e: rule.config(wraplength=max(200, e.width - 8)))

        self._expiry_row = tk.Frame(right, bg=BG)
        tk.Label(self._expiry_row, text="EXPIRES", bg=BG, fg=MUTED,
                 font=("Georgia", 8, "bold")).pack(side="left", padx=(0, 8))
        ef = tk.Frame(self._expiry_row, bg=BG, width=200, height=40)
        ef.pack(side="left")
        ef.pack_propagate(False)
        self.v_expiry = tk.StringVar(value="Never")
        self._expiry_box = _mk_combobox(ef, self.v_expiry, [label for label, _ in EXPIRY])
        self.v_expiry.trace_add("write", lambda *_: self._mark_dirty())

        self._actions = tk.Frame(right, bg=BG)
        self._save_btn = _btn(self._actions, "Save changes", self._save, "primary",
                              font=("Segoe UI", 9, "bold"), padx=14, pady=6)
        self._cancel_btn = _btn(self._actions, "Cancel", self._cancel_new, font=("Segoe UI", 9), padx=12, pady=6)
        self._copy_btn = _btn(self._actions, "📋 Copy token", self._copy_token, font=("Segoe UI", 9), padx=12, pady=6)
        self._rotate_btn = _btn(self._actions, "New text", self._rotate, font=("Segoe UI", 9), padx=12, pady=6)
        self._revoke_btn = _btn(self._actions, "Revoke", self._revoke, "danger", font=("Segoe UI", 9), padx=12, pady=6)
        self._log_btn = _btn(self._actions, "📜 Log", self._open_log, font=("Segoe UI", 9), padx=12, pady=6)

    # ---- token list -----------------------------------------------------------

    def _refresh_list(self, select=None):
        if self._client is None:
            return
        keep = select or self._selected

        def done(res):
            data = res.get("result_data")
            tokens = data.get("tokens") if isinstance(data, dict) else None
            if tokens is None:
                _, problem = _answer(res)
                self._say("Couldn't read the tokens: %s" % (problem or "no answer"), RED)
                return
            self._tokens = {t.get("id"): t for t in tokens if t.get("id")}
            self._fill_list(keep)
        self.ask("token list", done)

    def _fill_list(self, keep=None):
        if self._client is None or self._tree is None:
            return
        keep = keep or self._selected
        self._list.delete(*self._list.get_children())
        self._list.insert("", "end", iid="owner", text="★  Owner token", values=("",), tags=("owner",))
        for tid, t in self._tokens.items():
            status = t.get("status") or "active"
            if status == "revoked" and not self.v_show_revoked.get() and tid != keep:
                continue
            open_now = t.get("sessions") or 0
            state = "%d open" % open_now if open_now and status == "active" else status
            self._list.insert("", "end", iid=tid, text="●  " + (t.get("name") or tid),
                              values=(state,), tags=(status,))
        if self._mode == "new":
            return
        target = keep if keep and self._list.exists(keep) else "owner"
        self._selected = None
        self._list.selection_set(target)
        self._list.see(target)
        self._show(target)

    def _on_list_select(self, _event=None):
        sel = self._list.selection()
        if not sel or sel[0] == self._selected:
            return
        if self._dirty and not messagebox.askyesno("Unsaved changes",
                                                   "Leave without saving your changes?", parent=self):
            if self._selected and self._list.exists(self._selected):
                self._list.selection_set(self._selected)
            return
        self._show(sel[0])

    # ---- editor ---------------------------------------------------------------

    def _set_mode(self, mode):
        self._mode = mode
        for w in (self._name_row, self._owner_note, self._access, self._expiry_row, self._actions):
            w.pack_forget()
        for b in (self._save_btn, self._cancel_btn, self._copy_btn, self._rotate_btn, self._revoke_btn, self._log_btn):
            b.pack_forget()
        online = self._client is not None and self._tree is not None
        self._new_btn.config(state="normal" if online and mode != "new" else "disabled")
        self._refresh_btn.config(state="normal" if online else "disabled")
        if mode == "none":
            self._title_var.set("")
            self._info_var.set("")
            return
        self._actions.pack(side="bottom", fill="x", pady=(10, 0))
        if mode in ("token", "new"):
            self._expiry_row.pack(side="bottom", fill="x", pady=(8, 0))
        if mode == "new":
            self._name_row.pack(fill="x")
        if mode == "owner":
            self._owner_note.pack(fill="x", pady=(4, 0))
        else:
            self._access.pack(fill="both", expand=True)
        if mode == "new":
            self._save_btn.config(text="Create token")
            self._save_btn.pack(side="left")
            self._cancel_btn.pack(side="left", padx=(6, 0))
            return
        if mode == "token":
            self._save_btn.config(text="Save changes")
            self._save_btn.pack(side="left", padx=(0, 6))
        if mode in ("token", "owner"):
            self._copy_btn.pack(side="left", padx=(0, 6))
            self._rotate_btn.pack(side="left", padx=(0, 6))
        if mode == "token":
            self._revoke_btn.pack(side="left")
        self._log_btn.pack(side="right")

    def _show(self, tid):
        self._selected = tid
        self._dirty = False
        self._missing = []
        if tid == "owner":
            self._set_mode("owner")
            self._title_var.set("Owner token")
            self._info_var.set("Full access, always  ·  in console_token.txt")
            return
        t = self._tokens.get(tid)
        if t is None:
            self._set_mode("none")
            return
        status = t.get("status") or "active"
        self._set_mode("token" if status != "revoked" else "revoked")
        self._title_var.set(t.get("name") or tid)
        self._info_var.set("  ·  ".join([
            status, "id " + tid, "made " + _when(t.get("created")),
            "expires " + _when(t.get("expires")), "last used " + _when(t.get("last_used")),
            "%d open now" % (t.get("sessions") or 0)]))
        full = (t.get("preset") or "").lower() == "full"
        preset = (t.get("preset") or "custom").lower()
        self.v_preset.set(preset if preset in PRESET_HINTS else "custom")
        self._missing = [] if full else self._tree.load(t.get("access") or [])
        if full:
            self._tree.load([])
        self._expiry_box.config(values=[KEEP] + [label for label, _ in EXPIRY])
        self.v_expiry.set(KEEP)
        self._lock_presets(full=full, existing=True, revoked=status == "revoked")
        self._fill_tree()
        self._dirty = False

    def _new_token(self):
        if self._dirty and not messagebox.askyesno("Unsaved changes",
                                                   "Leave without saving your changes?", parent=self):
            return
        self._selected = None
        self._list.selection_remove(*self._list.selection())
        self._set_mode("new")
        self._title_var.set("New token")
        self._info_var.set("Pick what it may run, then Create token. You get its text to hand over.")
        self.v_name.set("")
        self.v_preset.set("moderator")
        self._tree.load(self._tree.preset_paths("moderator"))
        self._missing = []
        self._expiry_box.config(values=[label for label, _ in EXPIRY])
        self.v_expiry.set("Never")
        self._lock_presets(full=False, existing=False, revoked=False)
        self._fill_tree()
        self._dirty = False
        self._name_entry.focus_set()

    def _cancel_new(self):
        self._dirty = False
        self._mode = "none"
        self._fill_list("owner")

    def _lock_presets(self, full, existing, revoked):
        self._tree_locked = revoked or (existing and full) or self.v_preset.get() == "full"
        for key, b in self._preset_btns.items():
            if revoked:
                ok = False
            elif existing:
                ok = (key == "full") == full
            else:
                ok = True
            b.config(state="normal" if ok else "disabled")
        hint = PRESET_HINTS.get(self.v_preset.get(), "")
        if existing and not revoked:
            hint += ("  A full token can't be limited; make a new one." if full
                     else "  A limited token can't become full; make a new one.")
        if revoked:
            hint = "Revoked for good. Its text no longer works."
        self._preset_hint.config(text=hint)

    def _on_preset(self):
        key = self.v_preset.get()
        if key == "full":
            self._tree.load([])
        elif key != "custom":
            self._tree.load(self._tree.preset_paths(key))
        self._tree_locked = key == "full"
        self._preset_hint.config(text=PRESET_HINTS.get(key, ""))
        self._missing = []
        self._fill_tree()
        self._mark_dirty()

    def _mark_dirty(self):
        if self._mode in ("token", "new"):
            self._dirty = True

    # ---- command tree -----------------------------------------------------------

    def _fill_tree(self):
        tree = self._tree
        self._cmds.delete(*self._cmds.get_children())
        if tree is None:
            return
        find = self.v_find.get().strip().lower()
        locked = self._tree_locked

        def matches(node):
            return not find or find in node.path or find in node.desc.lower()

        def shown(node):
            return matches(node) or any(shown(c) for c in node.children)

        def add(node, parent, forced):
            if not (forced or shown(node)):
                return
            tags = ["module"] if node.children else []
            if locked:
                tags.append("locked")
            self._cmds.insert(parent, "end", iid=node.path, text=self._label(node),
                              values=(node.desc,), tags=tags,
                              open=bool(find) and not matches(node))
            for child in node.children:
                add(child, node.path, forced or (bool(find) and matches(node)))

        for root in tree.roots:
            add(root, "", False)
        self._update_notes()

    def _label(self, node):
        if self._tree_locked and self.v_preset.get() == "full":
            return "%s  %s" % (GLYPH["on"], node.name)
        return "%s  %s" % (GLYPH[self._tree.state(node)], node.name)

    def _relabel(self):
        for path in self._tree.index:
            if self._cmds.exists(path):
                self._cmds.item(path, text=self._label(self._tree.index[path]))
        self._update_notes()

    def _toggle(self, path):
        if self._tree_locked or self._mode not in ("token", "new"):
            return
        node = self._tree.index.get(path)
        if node is None:
            return
        self._tree.toggle(node)
        self._match_preset()
        self._relabel()
        self._mark_dirty()

    def _on_tree_click(self, event):
        if "indicator" in self._cmds.identify_element(event.x, event.y):
            return None
        row = self._cmds.identify_row(event.y)
        if row:
            self._cmds.focus(row)
            self._toggle(row)
        return "break"

    def _on_tree_double(self, event):
        """The first click of a double click ticked the row: undo that, and
        open or close a module instead."""
        if "indicator" in self._cmds.identify_element(event.x, event.y):
            return None
        row = self._cmds.identify_row(event.y)
        if row:
            self._toggle(row)
            if self._cmds.get_children(row):
                self._cmds.item(row, open=not self._cmds.item(row, "open"))
        return "break"

    def _on_tree_space(self, _event):
        row = self._cmds.focus()
        if row:
            self._toggle(row)
        return "break"

    def _tick_all(self, on):
        """Everything, or with a search only what it found."""
        if self._tree_locked or self._mode not in ("token", "new"):
            return
        find = self.v_find.get().strip().lower()

        def walk(iid):
            node = self._tree.index[iid]
            if find in node.path or find in node.desc.lower():
                self._tree.set(node, on)
            else:
                for child in self._cmds.get_children(iid):
                    walk(child)
        if find:
            for iid in self._cmds.get_children():
                walk(iid)
        else:
            self._tree.load([r.path for r in self._tree.roots] if on else [])
        self._match_preset()
        self._relabel()
        self._mark_dirty()

    def _match_preset(self):
        granted = set(self._tree.granted())
        for key in ("moderator", "builder", "viewer"):
            if granted == set(self._tree.preset_paths(key)):
                self.v_preset.set(key)
                break
        else:
            self.v_preset.set("custom")
        self._preset_hint.config(text=PRESET_HINTS.get(self.v_preset.get(), ""))

    def _update_notes(self):
        notes = []
        if self._missing:
            notes.append("Not on this server, left out when you save: " + ", ".join(self._missing))
        granted = self._tree.granted() if self._tree else []
        if self.v_preset.get() == "full" or any(p in ("websocket", "websocket subscribe") for p in granted):
            notes.append("websocket subscribe lets it watch everything on the server, every command anyone runs included.")
        self._notes.config(text="\n".join(notes))

    # ---- actions ----------------------------------------------------------------

    def _expiry_days(self):
        label = self.v_expiry.get()
        if label == KEEP:
            return -1
        return dict(EXPIRY).get(label, 0)

    def _access_text(self):
        if self.v_preset.get() == "full":
            return "full"
        return ",".join(self._tree.granted())

    def _run(self, cmd, done, busy_text):
        if self._busy:
            self._say("Still waiting for the server to answer the last change.", AMBER)
            return
        self._busy = True
        self._say(busy_text, MUTED)

        def finish(res):
            self._busy = False
            done(res)
        self.ask(cmd, finish)

    def _save(self):
        access = self._access_text()
        if not access:
            self._say("Tick at least one command or module.", RED)
            return
        preset = self.v_preset.get()
        days = self._expiry_days()
        if self._mode == "new":
            name = " ".join(self.v_name.get().split())
            if not name or len(name) > NAME_MAX or not re.fullmatch(r"[A-Za-z0-9 _-]+", name):
                self._say("A name has letters, numbers, spaces, - and _, up to %d." % NAME_MAX, RED)
                return
            cmd = "token create %s %s %d %s" % (_q(name), _q(access), max(days, 0), preset)

            def created(res):
                text, problem = _answer(res)
                if problem:
                    self._say("Not created: " + problem, RED)
                    return
                m = re.search(r"\(([a-z0-9]+)\)", text)
                self._dirty = False
                self._mode = "none"
                self._say("Created %s." % name, GREEN)
                _TokenTextDialog(self, "Token for " + name,
                                 "Give this to %s. They paste it as the console token in TavernKeeper or "
                                 "Remote Console, with this server's address. Anyone holding it can run "
                                 "what you ticked, so send it privately. Copy token shows it again later." % name,
                                 _last_line(text))
                self._refresh_list(select=m.group(1) if m else None)
            self._run(cmd, created, "Creating %s…" % name)
            return
        tid = self._selected
        name = self._title_var.get()
        if access == "full":
            cmd = "token edit %s full %d" % (tid, days)
        else:
            cmd = "token edit %s %s %d %s" % (tid, _q(access), days, preset)

        def saved(res):
            text, problem = _answer(res)
            if problem:
                self._say("Not saved: " + problem, RED)
                return
            if self._selected == tid:
                self._dirty = False
            self._say("Saved %s. It applies now, to open sessions too." % name, GREEN)
            self._refresh_list(select=tid)
        self._run(cmd, saved, "Saving %s…" % name)

    def _copy(self, text, what):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._say("Copied %s. Send it privately." % what, GREEN)

    def _copy_token(self):
        if self._selected == "owner":
            try:
                with open(CONSOLE_TOKEN_FILE) as f:
                    self._copy(f.read().strip(), "the owner token")
            except OSError as e:
                self._say("Couldn't read console_token.txt: %s" % e, RED)
            return
        tid, name = self._selected, self._title_var.get()

        def shown(res):
            text, problem = _answer(res)
            if problem:
                self._say("Couldn't get the token: " + problem, RED)
                return
            self._copy(_last_line(text), name + "'s token")
        self._run("token show %s" % tid, shown, "Getting %s's token…" % name)

    def _rotate(self):
        if self._selected == "owner":
            if not messagebox.askyesno(
                    "New owner token",
                    "Give the owner token new text?\n\nEvery bot and tool that uses the owner token stops "
                    "working until you give it the new one, and every other owner console closes, "
                    "this launcher's Console window included. This window stays connected.",
                    icon="warning", parent=self):
                return
            cmd, who = "token rotate owner", "the owner token"
        else:
            name = self._title_var.get()
            if not messagebox.askyesno(
                    "New token text",
                    "Give %s new token text?\n\nThe old text stops working and its open sessions close. "
                    "Its access stays the same." % name, parent=self):
                return
            cmd, who = "token rotate %s" % self._selected, name
        tid = self._selected

        def rotated(res):
            text, problem = _answer(res)
            if problem:
                self._say("No new text: " + problem, RED)
                return
            self._say("%s%s has new text. The old text no longer works." % (who[0].upper(), who[1:]), GREEN)
            lead = ("The new owner token. console_token.txt has it too, so Copy Console Token copies it."
                    if tid == "owner" else
                    "%s's new token. Send it to them privately; the old one no longer works." % who)
            _TokenTextDialog(self, "New text for " + who, lead, _last_line(text))
            self._refresh_list(select=tid)
        self._run(cmd, rotated, "Making new text for %s…" % who)

    def _revoke(self):
        tid, name = self._selected, self._title_var.get()
        if not messagebox.askyesno(
                "Revoke token",
                "Revoke %s for good?\n\nIts text stops working and its open sessions close. "
                "This can't be undone; you can make a new token for them later." % name,
                icon="warning", parent=self):
            return

        def revoked(res):
            text, problem = _answer(res)
            if problem:
                self._say("Not revoked: " + problem, RED)
                return
            self._say(text or "Revoked %s." % name, GREEN)
            self._refresh_list(select=tid)
        self._run("token revoke %s" % tid, revoked, "Revoking %s…" % name)

    def _open_log(self):
        if self._log_win and self._log_win.winfo_exists():
            self._log_win.show_token(self._selected)
            self._log_win.lift()
            return
        self._log_win = TokenLogWindow(self, self._selected)

    # ---- small things -------------------------------------------------------------

    def _set_connection(self, text, color, online):
        self._conn_var.set(text)
        self._conn_lbl.config(fg=color)
        if online or text == "Connecting…":
            self._reconnect_btn.pack_forget()
        else:
            self._reconnect_btn.pack(side="right", padx=(0, 4))

    def _say(self, text, color=MUTED):
        self._msg.config(text=text, fg=color)

    def tokens(self):
        return self._tokens

    def _on_close(self):
        self._closed = True
        self._jobs.put(None)
        if self._client is not None:
            self._client.disconnect()
            self._client = None
        self.destroy()


class _TokenTextDialog(tk.Toplevel):
    def __init__(self, parent, title, lead, text):
        super().__init__(parent)
        _start_hidden(self)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        _set_window_icon(self)
        tk.Label(self, text=lead, bg=BG, fg=PARCH, font=("Segoe UI", 9), justify="left",
                 wraplength=480).pack(anchor="w", padx=16, pady=(14, 8))
        f = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        f.pack(fill="x", padx=16)
        v = tk.StringVar(value=text)
        tk.Entry(f, textvariable=v, state="readonly", readonlybackground=SURF, fg=PARCH,
                 relief="flat", font=MONO, bd=6, width=64).pack(fill="x")
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=16, pady=12)
        self._copy_btn = _btn(row, "📋 Copy", lambda: self._copy(text), "primary",
                              font=("Segoe UI", 9, "bold"), padx=14, pady=5)
        self._copy_btn.pack(side="left")
        _btn(row, "Done", self.destroy, font=("Segoe UI", 9), padx=14, pady=5).pack(side="right")
        self.transient(parent)
        _finish_dark_window(self)
        self.grab_set()

    def _copy(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._copy_btn.config(text="✓ Copied")


class TokenLogWindow(tk.Toplevel):
    """What each token did: logins, refused logins and every command, newest last."""

    def __init__(self, tokens_window, token_id=None):
        super().__init__(tokens_window)
        _start_hidden(self)
        self._tw = tokens_window
        self.title("Console Token Log")
        self.configure(bg=BG)
        self.geometry("900x460")
        self.minsize(640, 300)
        _set_window_icon(self)
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(top, text="SHOW", bg=BG, fg=MUTED, font=("Georgia", 8, "bold")).pack(side="left", padx=(0, 6))
        ff = tk.Frame(top, bg=BG, width=240, height=40)
        ff.pack(side="left")
        ff.pack_propagate(False)
        self.v_who = tk.StringVar()
        self._who = _mk_combobox(ff, self.v_who, [])
        self._who.bind("<<ComboboxSelected>>", lambda e: self._load())
        _btn(top, "↻ Refresh", self._load, font=("Segoe UI", 9), padx=10, pady=4).pack(side="left", padx=8)
        self._count_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self._count_var, bg=BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="right")
        cols = ("time", "who", "event", "command", "result", "ip")
        box, self._rows = tokens_window._boxed_tree(self, columns=cols, show="headings", selectmode="browse")
        box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for col, width, stretch in (("time", 130, False), ("who", 120, False), ("event", 100, False),
                                    ("command", 300, True), ("result", 160, False), ("ip", 110, False)):
            self._rows.heading(col, text="IP" if col == "ip" else col.title(), anchor="w")
            self._rows.column(col, width=width, stretch=stretch, anchor="w")
        self._rows.tag_configure("refused", foreground=RED)
        self._rows.tag_configure("failed", foreground=AMBER)
        self._choices = {}
        _finish_dark_window(self)
        self.show_token(token_id)

    def show_token(self, token_id):
        tokens = self._tw.tokens()
        self._choices = {"Everyone": "", "Owner token": "owner"}
        for tid, t in tokens.items():
            label = "%s (%s)" % (t.get("name") or tid, tid)
            self._choices[label] = tid
        self._who.config(values=list(self._choices))
        pick = next((label for label, tid in self._choices.items() if tid == (token_id or "")), "Everyone")
        self.v_who.set(pick)
        self._load()

    def _load(self):
        tid = self._choices.get(self.v_who.get(), "")
        self._count_var.set("Loading…")

        def done(res):
            if not self.winfo_exists():
                return
            data = res.get("result_data")
            entries = data.get("entries") if isinstance(data, dict) else None
            if entries is None:
                _, problem = _answer(res)
                self._count_var.set("Couldn't read the log: %s" % (problem or "no answer"))
                return
            self._rows.delete(*self._rows.get_children())
            for e in entries:
                result = e.get("result") or ""
                if e.get("reason"):
                    result = (result + ": " if result else "") + e["reason"]
                tag = "refused" if e.get("event") == "bad_login" or e.get("result") == "refused" else \
                      "failed" if e.get("result") == "failed" else ""
                self._rows.insert("", "end", values=(
                    _when(e.get("time"), ""), e.get("name") or e.get("token") or "",
                    EVENTS.get(e.get("event"), e.get("event") or ""), e.get("command") or "",
                    result, e.get("ip") or ""), tags=(tag,) if tag else ())
            kids = self._rows.get_children()
            if kids:
                self._rows.see(kids[-1])
            self._count_var.set("%d line(s), newest at the bottom" % len(entries))
        self._tw.ask('token log %s 200' % (tid or '""'), done)
