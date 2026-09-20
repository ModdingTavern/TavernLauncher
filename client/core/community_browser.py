"""Browses the public community server list."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json, urllib.request

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from client.core.config import load_cfg, save_cfg, COMMUNITY_API
from client.core.auth import ping_server

class CommunityBrowser(tk.Toplevel):
    _COLUMNS = ("name","address","players","locked","type","region","version","ping")
    _HEADINGS = {"name":"Name","address":"Address","players":"Players",
                 "locked":"","type":"Type","region":"Region","version":"Version","ping":"Ping"}
    _SORT_KEYS = {
        "name":    lambda s: s.get("name","").lower(),
        "address": lambda s: s.get("address","").lower(),
        "players": lambda s: s.get("player_count",0),
        "locked":  lambda s: bool(s.get("has_password")),
        "type":    lambda s: s.get("kind","official"),
        "region":  lambda s: s.get("region","unknown").lower(),
        "version": lambda s: s.get("version","unknown").lower(),
        # Not-yet-checked (key absent) and confirmed-offline (-1) both sort
        # to the bottom either way -- neither is a "good" result worth
        # ranking above an actual measured ms value.
        "ping":    lambda s: s["_ping_ms"] if s.get("_ping_ms", -1) >= 0 else float("inf"),
    }

    # Checked in order, first match wins. Genuine text color via Treeview
    # row tags -- Treeview can only color a whole row's text, not a single
    # cell, so this does tint every column in that row, same tradeoff
    # already accepted for the offline-row dimming below. (Colored circle
    # emoji were tried first, but several systems render those as a plain
    # monochrome glyph rather than true color, which isn't a gradient at
    # all in practice -- row-tag foreground color is the one thing Tk
    # actually guarantees renders as color.)
    _PING_BUCKETS = (
        (60,  "ping_great", "#8fe89a"),   # light green
        (120, "ping_good",  "#6aaa72"),   # green
        (200, "ping_ok",    "#c9b856"),   # yellow
        (350, "ping_poor",  "#d89a4a"),   # orange
        (None,"ping_bad",   "#a83c3c"),   # dark red
    )

    # How many servers to ping at once -- unbounded parallel threads would
    # be wasteful if the list ever grows very large; this is generous
    # enough that even a few dozen servers all finish in roughly one
    # timeout's worth of wall time rather than serially.
    _MAX_CONCURRENT_PINGS = 20

    def __init__(self, parent, on_select):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Community Servers")
        self.configure(bg=BG)
        self.geometry("850x460")
        self.resizable(False, False)
        self._on_select = on_select
        self._servers   = []   # full list, straight from the API
        self._visible    = []  # filtered + sorted subset actually shown
        self._sort_col   = None
        self._sort_reverse = False
        self._ping_sema  = threading.Semaphore(self._MAX_CONCURRENT_PINGS)
        self._load()
        self._build()
        self._refresh()
        _finish_dark_window(self)

    def _load(self):
        cfg = load_cfg()
        self._sort_col = cfg.get("sort_col", None)
        self._sort_reverse = cfg.get("sort_reverse", False)
        save_cfg(cfg)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🌍  Community Servers", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        sf = tk.Frame(self, bg=BG)
        sf.pack(fill="x", padx=20, pady=(10,4))
        tk.Label(sf, text="🔍", bg=BG, fg=MUTED, font=("Segoe UI",10)).pack(side="left")
        self.v_search = tk.StringVar(value="")
        self.v_search.trace_add("write", lambda *_: self._populate())
        tk.Entry(sf, textvariable=self.v_search, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True, padx=(6,0))

        self._status = tk.StringVar(value="Fetching server list…")
        tk.Label(self, textvariable=self._status, bg=BG, fg=MUTED,
                 font=("Segoe UI",9)).pack(anchor="w", padx=20, pady=(4,4))

        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,8))
        self.tree = _mk_tree(lf, self._COLUMNS,
                             [190,130,65,30,85,60,95,80], height=8, hscroll=True)
        for col in self._COLUMNS:
            self.tree.heading(col, text=self._HEADINGS[col],
                              command=lambda c=col: self._sort_by(c))
        # Whole-row text coloring by ping quality (see _PING_BUCKETS'
        # comment for why this is row-level, not per-cell) -- offline
        # reuses the app's own muted gray rather than a bucket color,
        # since "unreachable" isn't a point on the good-to-bad gradient,
        # it's a different state entirely.
        for _threshold, tag, color in self._PING_BUCKETS:
            self.tree.tag_configure(tag, foreground=color)
        self.tree.tag_configure("offline_row", foreground=MUTED)

        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=20, pady=(0,12))
        _btn(br, "⟳ Refresh", self._refresh, font=("Segoe UI",9),
             pady=6, padx=12).pack(side="left")
        _btn(br, "★ Save as Favorite", self._save_favorite,
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)
        _btn(br, "Connect",   self._connect, "primary",
             font=("Georgia",10,"bold"), pady=6, padx=14).pack(side="right")

    def _refresh(self):
        self._status.set("Fetching…")
        for r in self.tree.get_children(): self.tree.delete(r)
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            req = urllib.request.Request(COMMUNITY_API,
                headers={"User-Agent":"TavernLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
            self._servers = data if isinstance(data, list) else []
            self.after(0, self._populate)
            self._start_pings()
        except Exception as e:
            self.after(0, lambda: self._status.set(
                f"Could not reach community list — {e}"))

    def _start_pings(self):
        """Kicks off one background ping per server, bounded to
        _MAX_CONCURRENT_PINGS at a time via the semaphore. Each result
        gets written directly onto that server's own dict (so re-sorting
        or filtering afterward never needs to re-check anything already
        measured), then the corresponding row's ping cell is refreshed
        in place -- no full re-populate, so an in-progress search/sort
        never gets disturbed by a ping landing mid-typing."""
        for srv in self._servers:
            address = srv.get("address","")
            host = address.split(":")[0]
            if not host:
                continue
            threading.Thread(target=self._ping_one, args=(srv, host), daemon=True).start()

    def _ping_one(self, srv, host):
        with self._ping_sema:
            try:
                _resp, ms = ping_server(host, timeout=5)
                srv["_ping_ms"] = ms
            except Exception:
                srv["_ping_ms"] = -1  # sentinel: confirmed unreachable, not just "not checked yet"
        self.after(0, lambda: self._update_ping_cell(srv))

    def _update_ping_cell(self, srv):
        address = srv.get("address","")
        if not self.tree.exists(address):
            return  # filtered out of view, or window closed mid-ping
        ms = srv.get("_ping_ms")
        self.tree.set(address, "ping", self._format_ping(ms))
        tag = "offline_row" if ms == -1 else self._ping_tag(ms)
        self.tree.item(address, tags=(tag,) if tag else ())

    def _format_ping(self, ms):
        if ms is None:
            return "…"
        if ms == -1:
            return "Offline"
        return f"{ms}ms"

    def _ping_tag(self, ms):
        """Returns the row tag name for this ping value, or None for the
        not-yet-checked/offline cases (handled separately by the caller)."""
        if ms is None or ms == -1:
            return None
        for threshold, tag, _color in self._PING_BUCKETS:
            if threshold is None or ms < threshold:
                return tag
        return self._PING_BUCKETS[-1][1]

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        cfg = load_cfg()
        cfg["sort_col"] = self._sort_col
        cfg["sort_reverse"] = self._sort_reverse
        save_cfg(cfg)
        self._populate()

    def _populate(self):
        query = self.v_search.get().strip().lower()
        if query:
            visible = [s for s in self._servers if
                       query in s.get("name","").lower() or
                       query in s.get("address","").lower()]
        else:
            visible = list(self._servers)

        if self._sort_col:
            key = self._SORT_KEYS[self._sort_col]
            visible.sort(key=key, reverse=self._sort_reverse)

        self._visible = visible

        for col in self._COLUMNS:
            label = self._HEADINGS[col]
            if col == self._sort_col:
                label += " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(col, text=label)

        for r in self.tree.get_children(): self.tree.delete(r)
        for s in self._visible:
            players = f"{s.get('player_count',0)}/{s.get('player_limit',50)}"
            locked  = "🔒" if s.get("has_password") else ""
            kind    = s.get("kind", "official")
            type_label = "🏛 Official" if kind == "official" else "🌐 Headless"
            version    = s.get("version", "unknown") or "unknown"
            region     = s.get("region", "unknown") or "unknown"
            ping_ms    = s.get("_ping_ms")
            ping_text  = self._format_ping(ping_ms)
            row_tag    = "offline_row" if ping_ms == -1 else self._ping_tag(ping_ms)
            row_tags   = (row_tag,) if row_tag else ()
            address    = s.get("address","?")
            # address as the row's own iid -- assumed unique (it's ip:port
            # for a live listing), and is what lets an async ping result
            # find its way back to the right row even after the list has
            # since been re-sorted or re-filtered by a search keystroke.
            try:
                self.tree.insert("","end", iid=address,
                    values=(s.get("name","?"), address, players, locked, type_label, region, version, ping_text),
                    tags=row_tags)
            except tk.TclError:
                # Two listed servers sharing the exact same address would
                # collide on iid -- fall back to an auto-generated one
                # rather than losing the row entirely; that server just
                # won't get live ping updates targeted at it specifically.
                self.tree.insert("","end",
                    values=(s.get("name","?"), address, players, locked, type_label, region, version, ping_text),
                    tags=row_tags)

        if not self._servers:
            self._status.set("No servers listed yet.")
        elif query and not visible:
            self._status.set(f"No servers match '{query}'.")
        else:
            self._status.set(f"{len(visible)} of {len(self._servers)} servers shown."
                             if query else f"{len(self._servers)} servers listed.")

    def _selected_server(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a server first.", parent=self)
            return None
        return self._visible[self.tree.index(sel[0])]

    def _connect(self):
        srv = self._selected_server()
        if not srv: return
        kind = srv.get("kind", "official")
        address = srv.get("address","")
        host = address.split(":")[0]
        port = address.split(":")[1] if ":" in address else "1757"
        # "address" is "ip:port" for display — only the host is meaningful to
        # the auth handshake / headless join today, but the port still gets
        # passed through so Join Server can hand it to the game itself.
        self._on_select(host, srv.get("name",""), kind, port)
        self.destroy()

    def _save_favorite(self):
        srv = self._selected_server()
        if not srv: return
        address = srv.get("address","")
        host = address.split(":")[0]
        port = address.split(":")[1] if ":" in address else "1757"
        name = srv.get("name") or host
        cfg = load_cfg()
        saved = cfg.get("saved_servers", [])
        if any(s.get("ip") == host for s in saved):
            messagebox.showinfo("Already saved", f"'{name}' is already in your favorites.", parent=self)
            return
        saved.append({"name": name, "ip": host, "port": port})
        cfg["saved_servers"] = saved
        save_cfg(cfg)
        messagebox.showinfo("Saved", f"'{name}' added to favorites.", parent=self)

