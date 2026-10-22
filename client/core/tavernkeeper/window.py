"""
TavernKeeper: native prefab spawn/select/move/settings/admin tool, run on
a remote-console connection. Core tabs (Spawn, Find & Select, Move &
Rotate, Server Settings, Save & Load, Player Admin) are built directly
here; anything else -- e.g. the Macros tab -- comes from an addon
registering itself through client.core.tavernkeeper.registry, and is
inserted at the position it asks for without this file needing to know
the addon exists.
"""
import os
import re
import json
import time
import struct
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar, _fix_combobox_popdown_colors,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.ws_console_client import WsConsoleClient
from tavern_shared.paths import _tavern_data_dir
from client.core.tavernkeeper.registry import register_tab, ordered_tabs, registry
from tavern_shared.reorder_dialog import ReorderDialog

class TavernKeeperWindow(tk.Toplevel):
    """A native prefab spawn/select/move/settings/admin tool, on the same
    remote console connection as RemoteConsoleWindow — built to replicate
    the community's Prefabulator tool without depending on it directly (it
    authenticates through Alta's own official servers, which doesn't work
    for a private server that never registers there).

    The console connection here has no idea which in-game player is "the
    one using this" — there's no such concept, it's a plain admin pipe
    into the server. Every position-based command (select find, select
    prefab, select look-at, ...) takes an explicit player name to anchor
    around. That's why there's a Target Player selector rather than any
    assumption baked in about whose position "nearby" means."""

    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("TavernKeeper")
        self.configure(bg=BG)
        self.resizable(True, True)
        _set_window_icon(self)
        self._ws_client = None
        self._connected = False
        self._stop = threading.Event()
        self._prefab_list = None
        self._save_items = []  # list of (label, spawn_string) staged for Save/Load
        self._build_connect_form()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _finish_dark_window(self)

    # ── Connection ───────────────────────────────────────────────────────────

    def _build_connect_form(self):
        self.geometry("420x300")
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🧩  TavernKeeper", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tk.Label(self,
            text="Connects to a server's console, the same way Remote Console does. "
                 "You'll need the server's IP and a console token from the owner.",
            bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=370, justify="left"
        ).pack(anchor="w", padx=20, pady=(10,4))

        _section_label(self, "SERVER IP")
        hf = _field(self)
        self.v_host = tk.StringVar()
        host_entry = tk.Entry(hf, textvariable=self.v_host, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6)
        host_entry.pack(fill="x")

        _section_label(self, "CONSOLE TOKEN")
        tf = _field(self)
        self.v_token = tk.StringVar()
        token_entry = tk.Entry(tf, textvariable=self.v_token, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, show="●")
        token_entry.pack(fill="x")

        self._connect_status = tk.StringVar(value="")
        tk.Label(self, textvariable=self._connect_status, bg=BG, fg=RED,
                 font=("Segoe UI",9), wraplength=370, justify="left"
        ).pack(anchor="w", padx=22, pady=(2,0))

        self._connect_btn = _btn(self, "Connect", self._attempt_connect, "primary",
             font=("Georgia",10,"bold"), pady=10)
        self._connect_btn.pack(fill="x", padx=20, pady=(10,16))

        host_entry.bind("<Return>", lambda e: token_entry.focus_set())
        token_entry.bind("<Return>", lambda e: self._attempt_connect())
        host_entry.focus_set()

        self.update_idletasks()
        self.geometry(f"420x{self.winfo_reqheight()}")

    def _attempt_connect(self):
        host = self.v_host.get().strip() or "127.0.0.1"
        token = self.v_token.get().strip()
        if not token:
            self._connect_status.set("Enter the console token.")
            return
        self._connect_btn.config(state="disabled", text="Connecting…")
        self._connect_status.set("")
        self._ws_client = WsConsoleClient()

        def worker():
            ok, msg = self._ws_client.connect(
                host, token,
                on_line=lambda t: self.after(0, lambda p=t: self._on_line(p)),
                on_disc=lambda r: self.after(0, lambda: self._on_disconnected(r)),
            )
            if ok:
                self._connected = True
                self.after(0, self._connect_succeeded)
            else:
                self.after(0, lambda m=msg: self._connect_failed(m))
        threading.Thread(target=worker, daemon=True).start()

    def _connect_failed(self, msg):
        self._connect_btn.config(state="normal", text="Connect")
        self._connect_status.set(msg)

    def _connect_succeeded(self):
        for child in list(self.winfo_children()):
            child.destroy()
        self.minsize(1, 1)
        self._build_main_ui()
        self._refresh_players()

    def _on_disconnected(self, msg):
        self._connected = False
        if hasattr(self, "_log_status"):
            self._log_status.set("Disconnected")
        if hasattr(self, "out"):
            self._append_log(f"\n[{msg}]\n", "err")

    def _on_line(self, text):
        """Called by WsConsoleClient for streaming output — display only."""
        self._append_log(text)

    # ── Sending ──────────────────────────────────────────────────────────────

    def _send(self, cmd):
        """Fire-and-forget — output arrives via _on_line callback."""
        if not self._connected:
            return
        self._append_log(f"> {cmd}\n", "cyan")
        self._ws_client.send(cmd)

    def _send_and_capture(self, cmd, on_result, quiet=0.4, max_wait=20.0):
        """Send a command and deliver (result_string, result_data) to on_result.
        Uses WsConsoleClient.send_capture — blocks in a worker thread,
        then calls on_result(result_string, result_data) on the Tk thread.
        quiet and max_wait are kept for API compatibility but max_wait
        is used as the capture timeout."""
        if not self._connected:
            self.after(0, lambda: on_result(None, None))
            return
        self._append_log(f"> {cmd}\n", "cyan")

        def worker():
            rs, rd, err = self._ws_client.send_capture(cmd, timeout=max_wait)
            self.after(0, lambda: on_result(rs, rd))
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _q(value):
        """Quotes a value for a console command argument, matching the
        convention already used elsewhere in this project."""
        return f'"{value}"'

    # ── Main UI ──────────────────────────────────────────────────────────────

    def _build_main_ui(self):
        self.minsize(820, 820)
        self.geometry("860x900")
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🧩  TavernKeeper", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        _btn(h, "↕ Reorder Tabs", self._open_reorder_tabs,
             font=("Segoe UI",8), pady=3, padx=8).pack(side="left", padx=(0,8))
        _btn(h, "☰ Jump to Tab", self._open_jump_to_tab,
             font=("Segoe UI",8), pady=3, padx=8).pack(side="left", padx=(0,8))
        self._log_status = tk.StringVar(value="Connected")
        tk.Label(h, textvariable=self._log_status, bg=SURF, fg=MUTED,
                 font=("Segoe UI",9)).pack(side="right", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tf = tk.Frame(self, bg=BG)
        tf.pack(fill="x", padx=14, pady=(10,4))
        tk.Label(tf, text="Target player:", bg=BG, fg=PARCH,
                 font=("Segoe UI",9,"bold")).pack(side="left")
        self.v_target = tk.StringVar()
        style = ttk.Style()
        style.configure("Tavk.Target.TCombobox", fieldbackground=SURF, background=SURF2,
                        foreground=PARCH, selectbackground=SURF, selectforeground=PARCH,
                        arrowcolor=AMBERDIM, borderwidth=0)
        style.map("Tavk.Target.TCombobox",
                  fieldbackground=[("readonly",SURF), ("!disabled",SURF)],
                  foreground=[("readonly",PARCH), ("!disabled",PARCH)],
                  selectbackground=[("readonly",SURF), ("!disabled",SURF)],
                  selectforeground=[("readonly",PARCH), ("!disabled",PARCH)])
        self._target_combo = ttk.Combobox(tf, textvariable=self.v_target,
                                          font=("Consolas",10), width=22, style="Tavk.Target.TCombobox")
        self._target_combo.pack(side="left", padx=(8,6))
        _fix_combobox_popdown_colors(self._target_combo, SURF, PARCH, AMBERDIM, "#ffd080")
        _btn(tf, "⟳ Refresh", self._refresh_players,
             font=("Segoe UI",8), pady=3, padx=8).pack(side="left")
        tk.Label(tf, text="Actions below happen at this player's location.",
                 bg=BG, fg=MUTED, font=("Segoe UI",8)
        ).pack(side="left", padx=(10,0))

        style = ttk.Style()
        style.configure("Tavk.TNotebook", background=BG, borderwidth=0)
        style.configure("Tavk.TNotebook.Tab", background=SURF2, foreground=PARCH,
                        padding=(12,6), font=("Georgia",9))
        style.map("Tavk.TNotebook.Tab",
                  background=[("selected",AMBERDIM)],
                  foreground=[("selected","#ffd080")])

        self._tabs_container = tk.Frame(self, bg=BG)
        self._tabs_container.pack(fill="both", expand=True, padx=12, pady=(6,6))
        self._build_tabs_notebook()

        _section_label(self, "CONSOLE OUTPUT")
        lf = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lf.pack(fill="x", padx=12, pady=(0,12))
        self.out = tk.Text(lf, bg=SURF, fg="#b09a78", font=MONO, height=6,
                           relief="flat", bd=0, state="disabled", wrap="word")
        sb = _mk_scrollbar(lf, self.out.yview)
        sb.pack(side="right", fill="y")
        self.out.config(yscrollcommand=sb.set)
        self.out.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        for t,c in [("ok",GREEN),("warn",AMBER),("err",RED),("cyan",CYAN)]:
            self.out.tag_config(t, foreground=c)

    def _append_log(self, text, tag=""):
        self.out.config(state="normal")
        self.out.insert("end", text, tag)
        self.out.see("end")
        self.out.config(state="disabled")

    def _refresh_players(self):
        def on_result(rs, rd):
            names = []
            if rd and isinstance(rd, list):
                for item in rd:
                    if isinstance(item, dict):
                        name = item.get("Username") or item.get("username")
                        if name and name not in names:
                            names.append(str(name))
            elif rs and not rs.startswith("System."):
                for line in rs.splitlines():
                    line = line.strip()
                    if not line or "UserID" in line or line.startswith("-"):
                        continue
                    if line.startswith("[CommandService") or line == "Success":
                        continue
                    if line.startswith("System."):
                        continue
                    if " (" in line:
                        name = line.split(" (")[0].strip()
                    else:
                        name = line.split()[0].strip()
                    if name and name not in names:
                        names.append(name)
            # Always update — empty list clears the combo cleanly
            self._target_combo["values"] = names
            if names:
                if not self.v_target.get() or self.v_target.get() not in names:
                    self.v_target.set(names[0])
            else:
                self.v_target.set("")
        self._send_and_capture("player list", on_result)

    def _current_target(self):
        target = self.v_target.get().strip()
        if not target:
            messagebox.showinfo("Pick a target player",
                "Choose or type a target player first.", parent=self)
            return None
        return target

    def _bind_prefab_autocomplete(self, entry, target_var):
        """As-you-type suggestions for a prefab field, matching name or
        hash against the cached prefab list — reads from the same disk
        cache Browse Prefabs uses, without triggering a fetch of its own,
        so typing never causes a surprise network call."""
        ac_frame = tk.Frame(self, bg=SURF2, highlightbackground=BORDER, highlightthickness=1)
        ac_listbox = tk.Listbox(ac_frame, bg=SURF2, fg=PARCH,
                                selectbackground=AMBERDIM, selectforeground="#ffd080",
                                relief="flat", bd=0, highlightthickness=0,
                                font=("Consolas",10), activestyle="none")
        ac_scrollbar = _mk_scrollbar(ac_frame, ac_listbox.yview)
        ac_scrollbar.pack(side="right", fill="y")
        ac_listbox.config(yscrollcommand=ac_scrollbar.set)
        ac_listbox.pack(side="left", fill="both", expand=True)
        state = {"visible": False, "matches": []}

        def hide():
            if state["visible"]:
                ac_frame.place_forget()
                state["visible"] = False

        def show(matches):
            state["matches"] = matches
            ac_listbox.delete(0, "end")
            for h, n in matches:
                ac_listbox.insert("end", f"{n}   [{h}]")
            ac_listbox.selection_clear(0, "end")
            ac_listbox.selection_set(0)
            ac_listbox.config(height=min(6, len(matches)))
            ac_frame.place(in_=entry, x=0, rely=1.0, anchor="nw", width=entry.winfo_width())
            ac_frame.lift()
            state["visible"] = True

        def update_suggestions(event=None):
            if event is not None and event.keysym in ("Down","Up","Tab","Return","Escape"):
                return
            text = target_var.get().strip().lower()
            if not text:
                hide()
                return
            if self._prefab_list is None:
                cached = self._load_prefabs_cache()
                if not cached:
                    return  # nothing to suggest from yet, and typing shouldn't trigger a fetch
                self._prefab_list = cached
            matches = [(h,n) for h,n in self._prefab_list
                       if text in n.lower() or text == str(h)][:50]
            if matches and not (len(matches) == 1 and str(matches[0][0]) == text):
                show(matches)
            else:
                hide()

        def accept_selected(event=None):
            if not state["visible"]:
                return None
            sel = ac_listbox.curselection()
            idx = sel[0] if sel else 0
            if 0 <= idx < len(state["matches"]):
                target_var.set(str(state["matches"][idx][0]))
            hide()
            return "break"

        def move_selection(delta):
            if not state["visible"]:
                return
            sel = ac_listbox.curselection()
            idx = sel[0] if sel else 0
            idx = max(0, min(len(state["matches"])-1, idx+delta))
            ac_listbox.selection_clear(0, "end")
            ac_listbox.selection_set(idx)
            ac_listbox.see(idx)

        entry.bind("<KeyRelease>", update_suggestions)
        entry.bind("<Tab>", accept_selected)
        entry.bind("<Return>", accept_selected)
        entry.bind("<Down>", lambda e: (move_selection(1), "break")[1])
        entry.bind("<Up>", lambda e: (move_selection(-1), "break")[1])
        entry.bind("<Escape>", lambda e: hide())
        ac_listbox.bind("<ButtonRelease-1>", lambda e: (accept_selected(), entry.focus_set()))

    # ── Spawn tab ────────────────────────────────────────────────────────────

    def _build_spawn_tab(self, parent):
        tk.Label(parent, text="Spawns a prefab at the target player's location.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=680, justify="left"
        ).pack(anchor="w", padx=8, pady=(10,6))

        _section_label(parent, "PREFAB")
        pf = _field(parent)
        self.v_spawn_prefab = tk.StringVar()
        row = tk.Frame(pf, bg=SURF)
        row.pack(fill="x")
        spawn_prefab_entry = tk.Entry(row, textvariable=self.v_spawn_prefab, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6)
        spawn_prefab_entry.pack(side="left", fill="x", expand=True)
        self._bind_prefab_autocomplete(spawn_prefab_entry, self.v_spawn_prefab)
        _btn(parent, "Browse Prefabs…", lambda: self._open_prefab_picker(self.v_spawn_prefab), "primary",
             font=("Segoe UI",9,"bold"), pady=6).pack(fill="x", padx=8, pady=(4,10))

        _section_label(parent, "ARGUMENTS  (optional)")
        af = _field(parent)
        self.v_spawn_args = tk.StringVar()
        tk.Entry(af, textvariable=self.v_spawn_args, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")

        _btn(parent, "Spawn at Target Player", self._on_spawn, "primary",
             font=("Georgia",10,"bold"), pady=10).pack(fill="x", padx=8, pady=(8,8))

    def _on_spawn(self):
        target = self._current_target()
        if not target:
            return
        prefab = self.v_spawn_prefab.get().strip()
        if not prefab:
            messagebox.showinfo("Enter a prefab", "Pick or type a prefab first.", parent=self)
            return
        args = self.v_spawn_args.get().strip()
        cmd = f"spawn {self._q(target)} {self._q(prefab)}"
        if args:
            cmd += f" {args}"
        self._send(cmd)

    def _prefabs_cache_path(self):
        return os.path.join(_tavern_data_dir(), "prefabs.json")

    def _load_prefabs_cache(self):
        try:
            with open(self._prefabs_cache_path(), "r", encoding="utf-8") as f:
                data = json.load(f)
            return [(int(h), n) for h, n in data]
        except Exception:
            return None

    def _save_prefabs_cache(self, prefab_list):
        try:
            with open(self._prefabs_cache_path(), "w", encoding="utf-8") as f:
                json.dump(prefab_list, f)
        except Exception:
            pass  # a failed cache write isn't worth interrupting anything over

    def _open_prefab_picker(self, target_var):
        if self._prefab_list is not None:
            self._show_prefab_picker(target_var)
            return
        cached = self._load_prefabs_cache()
        if cached:
            self._prefab_list = cached
            self._show_prefab_picker(target_var)
            return
        self._fetch_prefab_list(target_var)

    def _fetch_prefab_list(self, target_var):
        self._append_log("Fetching prefab list…\n")
        def on_result(rs, rd):
            prefabs = []
            # rd is a list of {Hash: int, Name: str} objects from spawn list
            if rd and isinstance(rd, list):
                for item in rd:
                    if isinstance(item, dict):
                        h = item.get("Hash") or item.get("hash")
                        n = item.get("Name") or item.get("name") or ""
                        if h is not None:
                            prefabs.append((int(h), str(n)))
            elif rs:
                # Fall back to regex on ResultString
                matches = re.findall(r'\{"Hash":\s*(-?\d+),\s*"Name":\s*"([^"]*)"\}', rs)
                prefabs = [(int(h), n) for h, n in matches]
            if not prefabs:
                messagebox.showinfo("No prefabs found",
                    "The server didn't return a prefab list.", parent=self)
                return
            self._prefab_list = prefabs
            self._save_prefabs_cache(self._prefab_list)
            self._show_prefab_picker(target_var)
        self._send_and_capture("spawn list", on_result, quiet=1.5, max_wait=60.0)
    def _show_prefab_picker(self, target_var):
        win = tk.Toplevel(self)
        _start_hidden(win)
        win.title("Browse Prefabs")
        win.configure(bg=BG)
        _set_window_icon(win)
        win.geometry("480x600")
        win.minsize(420, 500)

        h = tk.Frame(win, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="Browse Prefabs", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(win, bg=BORDER, height=1).pack(fill="x")

        sf = tk.Frame(win, bg=BG)
        sf.pack(fill="x", padx=12, pady=(10,4))
        tk.Label(sf, text="Search:", bg=BG, fg=PARCH, font=("Segoe UI",9)).pack(side="left")
        v_search = tk.StringVar()
        search_entry = tk.Entry(sf, textvariable=v_search, bg=SURF, fg=PARCH,
                                insertbackground=AMBER, relief="flat",
                                font=("Consolas",10), bd=6)
        search_entry.pack(side="left", fill="x", expand=True, padx=(6,0))
        search_entry.focus_set()
        _btn(sf, "⟳", lambda: (win.destroy(), self._fetch_prefab_list(target_var)),
             font=("Segoe UI",9), pady=4, padx=8).pack(side="left", padx=(6,0))

        count_var = tk.StringVar()
        tk.Label(win, textvariable=count_var, bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).pack(anchor="w", padx=14, pady=(2,4))

        lf = tk.Frame(win, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lf.pack(fill="both", expand=True, padx=12, pady=(0,10))
        listbox = tk.Listbox(lf, bg=SURF, fg=PARCH, selectbackground=AMBERDIM,
                             selectforeground="#ffd080", relief="flat", bd=0,
                             font=("Consolas",10), activestyle="none")
        sb = _mk_scrollbar(lf, listbox.yview)
        sb.pack(side="right", fill="y")
        listbox.config(yscrollcommand=sb.set)
        listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)

        state = {"filtered": list(self._prefab_list)}

        def refresh_list(*_):
            query = v_search.get().strip().lower()
            if query:
                state["filtered"] = [(h,n) for h,n in self._prefab_list
                                      if query in n.lower() or query == str(h)]
            else:
                state["filtered"] = list(self._prefab_list)
            listbox.delete(0, "end")
            shown = state["filtered"][:500]
            for h, n in shown:
                listbox.insert("end", f"{n}   [{h}]")
            extra = f" (showing first 500)" if len(state["filtered"]) > 500 else ""
            count_var.set(f"{len(state['filtered'])} result(s){extra}")

        v_search.trace_add("write", refresh_list)
        refresh_list()
        _finish_dark_window(win)

        def use_selected(event=None):
            sel = listbox.curselection()
            if not sel:
                return
            h, n = state["filtered"][sel[0]]
            target_var.set(str(h))
            win.destroy()

        listbox.bind("<Double-Button-1>", use_selected)
        _btn(win, "Use Selected", use_selected, "primary",
             font=("Georgia",10,"bold"), pady=8).pack(fill="x", padx=12, pady=(0,12))

    # ── Find & Select tab ───────────────────────────────────────────────────

    def _build_select_tab(self, parent):
        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x", padx=8, pady=(10,6))
        tk.Label(top, text="Diameter:", bg=BG, fg=PARCH,
                 font=("Segoe UI",9)).pack(side="left")
        self.v_radius = tk.StringVar(value="10")
        tk.Entry(top, textvariable=self.v_radius, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=6).pack(side="left", padx=(6,10))
        _btn(top, "🔍 Find Nearby", self._on_find_nearby, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=12).pack(side="left")
        tk.Label(top, text="around the target player",
                 bg=BG, fg=MUTED, font=("Segoe UI",8)).pack(side="left", padx=(8,0))

        # Groups row
        gf = tk.Frame(parent, bg=BG)
        gf.pack(fill="x", padx=8, pady=(0,6))
        tk.Label(gf, text="Group:", bg=BG, fg=PARCH,
                 font=("Segoe UI",9)).pack(side="left")
        self._group_combo_var = tk.StringVar(value="(none)")
        style = ttk.Style()
        style.configure("Tavk.Group.TCombobox", fieldbackground=SURF, background=SURF2,
                        foreground=PARCH, selectbackground=SURF, selectforeground=PARCH,
                        arrowcolor=AMBERDIM, borderwidth=0)
        style.map("Tavk.Group.TCombobox",
                  fieldbackground=[("readonly",SURF)],
                  foreground=[("readonly",PARCH)],
                  selectbackground=[("readonly",SURF)],
                  selectforeground=[("readonly",PARCH)])
        self._group_combo = ttk.Combobox(gf, textvariable=self._group_combo_var,
                                          font=("Consolas",9), width=18, state="readonly",
                                          style="Tavk.Group.TCombobox")
        self._group_combo["values"] = ["(none)"]
        self._group_combo.pack(side="left", padx=(4,6))
        self._group_combo.bind("<<ComboboxSelected>>", self._on_group_select)
        _fix_combobox_popdown_colors(self._group_combo, SURF, PARCH, AMBERDIM, "#ffd080")
        _btn(gf, "✕ Delete Group", self._on_group_delete,
             font=("Segoe UI",8), pady=3, padx=6).pack(side="left", padx=(0,12))
        self.v_group_name = tk.StringVar()
        tk.Entry(gf, textvariable=self.v_group_name, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",9),
                 bd=4, width=14).pack(side="left", padx=(0,4))
        _btn(gf, "Save Checked as Group", self._on_group_save, "primary",
             font=("Segoe UI",8,"bold"), pady=3, padx=6).pack(side="left")

        # Two-column container: nearby list (left) + selection history (right)
        cols = tk.Frame(parent, bg=BG)
        cols.pack(fill="both", expand=True, padx=8, pady=(0,6))
        cols.columnconfigure(0, weight=3)
        cols.columnconfigure(1, weight=2)

        # ── Left: Nearby list ─────────────────────────────────────────────
        left = tk.Frame(cols, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0,4))
        tk.Label(left, text="NEARBY  (✓ = group)", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).pack(anchor="w", pady=(0,2))
        lb = tk.Frame(left, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True)
        self._nearby_canvas = tk.Canvas(lb, bg=SURF, highlightthickness=0)
        sb2 = _mk_scrollbar(lb, self._nearby_canvas.yview)
        sb2.pack(side="right", fill="y")
        self._nearby_canvas.config(yscrollcommand=sb2.set)
        self._nearby_canvas.pack(side="left", fill="both", expand=True)
        self._nearby_inner = tk.Frame(self._nearby_canvas, bg=SURF)
        self._nearby_canvas_window = self._nearby_canvas.create_window(
            (0, 0), window=self._nearby_inner, anchor="nw")
        self._nearby_inner.bind("<Configure>", lambda e: (
            self._nearby_canvas.configure(scrollregion=self._nearby_canvas.bbox("all")),
            self._nearby_canvas.itemconfig(self._nearby_canvas_window,
                                            width=self._nearby_canvas.winfo_width())
        ))
        self._nearby_canvas.bind("<Configure>", lambda e:
            self._nearby_canvas.itemconfig(self._nearby_canvas_window, width=e.width))

        def _nearby_mousewheel(event):
            self._nearby_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._nearby_canvas.bind("<MouseWheel>", _nearby_mousewheel)
        self._nearby_inner.bind("<MouseWheel>", _nearby_mousewheel)
        self._nearby_mousewheel = _nearby_mousewheel

        # ── Right: Selection history ──────────────────────────────────────
        right = tk.Frame(cols, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(4,0))
        tk.Label(right, text="SELECTION HISTORY", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).pack(anchor="w", pady=(0,2))
        hf = tk.Frame(right, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        hf.pack(fill="both", expand=True)
        self._history_listbox = tk.Listbox(hf, bg=SURF, fg=PARCH,
                                            selectbackground=AMBERDIM,
                                            selectforeground="#ffd080",
                                            relief="flat", bd=0,
                                            font=("Consolas",8),
                                            activestyle="none")
        hsb = _mk_scrollbar(hf, self._history_listbox.yview)
        hsb.pack(side="right", fill="y")
        self._history_listbox.config(yscrollcommand=hsb.set)
        self._history_listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        self._history_listbox.bind("<MouseWheel>",
            lambda e: self._history_listbox.yview_scroll(int(-1*(e.delta/120)), "units"))
        # Click history entry to re-select that entity
        self._history_listbox.bind("<<ListboxSelect>>", self._on_history_select)
        _btn(right, "Clear", self._on_history_clear,
             font=("Segoe UI",7), pady=2, padx=6).pack(anchor="e", pady=(2,0))

        # Storage
        self._nearby_items = []
        self._prefab_groups = {}
        self._selection_history = []  # list of (eid, name)
        self._nearby_listbox = None

        _section_label(parent, "SELECT BY PREFAB  (nearest to target player)")
        spf = _field(parent)
        self.v_select_prefab = tk.StringVar()
        row_sp = tk.Frame(spf, bg=SURF)
        row_sp.pack(fill="x")
        select_prefab_entry = tk.Entry(row_sp, textvariable=self.v_select_prefab, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6)
        select_prefab_entry.pack(side="left", fill="x", expand=True)
        self._bind_prefab_autocomplete(select_prefab_entry, self.v_select_prefab)
        _btn(parent, "Browse Prefabs…", lambda: self._open_prefab_picker(self.v_select_prefab), "primary",
             font=("Segoe UI",9,"bold"), pady=6).pack(fill="x", padx=8, pady=(4,4))
        _btn(parent, "Select Nearest", self._on_select_prefab, "primary",
             font=("Segoe UI",9,"bold"), pady=6).pack(fill="x", padx=8, pady=(0,10))

        _section_label(parent, "CURRENT SELECTION")
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=8, pady=(0,12))
        _btn(row, "Get String", self._on_get_string,
             font=("Segoe UI",9), pady=7, padx=12).pack(side="left")
        _btn(row, "Snap to Ground", lambda: self._send("select snap-ground"),
             font=("Segoe UI",9), pady=7, padx=12).pack(side="left", padx=6)
        _btn(row, "Look At Target", self._on_look_at,
             font=("Segoe UI",9), pady=7, padx=12).pack(side="left", padx=(0,6))
        _btn(row, "Unselect", lambda: self._send("select unselect"),
             font=("Segoe UI",9), pady=7, padx=12).pack(side="left")
        _btn(row, "✕ Destroy", self._on_destroy_selection, "danger",
             font=("Segoe UI",9,"bold"), pady=7, padx=12).pack(side="right")

    def _populate_nearby(self, items):
        """Rebuild the checkbox list from items = [(id, name), ...]."""
        for widget in self._nearby_inner.winfo_children():
            widget.destroy()
        self._nearby_items = []
        if not items:
            tk.Label(self._nearby_inner, text="(nothing found)", bg=SURF, fg=MUTED,
                     font=("Consolas",9)).pack(anchor="w", padx=6, pady=4)
            return
        for eid, name in items:
            var = tk.BooleanVar(value=False)
            row = tk.Frame(self._nearby_inner, bg=SURF)
            row.pack(fill="x")
            # Checkbutton: light indicator colour so it's visible on dark bg
            cb = tk.Checkbutton(row, variable=var, bg=SURF,
                                 activebackground=SURF,
                                 selectcolor=SURF,
                                 fg=PARCH,
                                 relief="flat", bd=0)
            cb.pack(side="left")
            label_text = f"{str(eid):<12} {name}"
            lbl = tk.Label(row, text=label_text, bg=SURF, fg=PARCH,
                           font=("Consolas",9), cursor="hand2", anchor="w")
            lbl.pack(side="left", fill="x", expand=True)

            def _refresh_row_bg(row=row, var=var):
                """Colour the whole row amber when checked, normal when not."""
                checked = var.get()
                bg = AMBERDIM if checked else SURF
                row.config(bg=bg)
                for c in row.winfo_children():
                    try: c.config(bg=bg)
                    except Exception: pass

            # Checkbox toggle → update row background
            cb.config(command=_refresh_row_bg)

            # Click label → select entity on server AND highlight row
            def on_click(e, eid=eid, name=name, row=row):
                # A single click here means "just this one" -- clear any
                # ticked checkboxes first so _active_entity_ids() doesn't
                # keep silently preferring a leftover checked group over
                # the explicit single selection being made right now.
                self._uncheck_all_nearby()
                # Always highlight this specific row orange (selected)
                row.config(bg=AMBERDIM)
                for c in row.winfo_children():
                    try: c.config(bg=AMBERDIM)
                    except Exception: pass
                self._send(f"select {eid}")
                self._add_to_history(eid, name)
            lbl.bind("<Button-1>", on_click)
            # Mousewheel on each row and its children
            mwh = getattr(self, "_nearby_mousewheel", None)
            if mwh:
                row.bind("<MouseWheel>", mwh)
                cb.bind("<MouseWheel>", mwh)
                lbl.bind("<MouseWheel>", mwh)
            self._nearby_items.append((eid, name, var))
        self._nearby_canvas.update_idletasks()
        self._nearby_canvas.configure(scrollregion=self._nearby_canvas.bbox("all"))

    def _on_find_nearby(self):
        target = self._current_target()
        if not target:
            return
        try:
            diameter = float(self.v_radius.get().strip())
        except ValueError:
            messagebox.showinfo("Invalid value", "Enter a number for the search diameter.", parent=self)
            return
        for widget in self._nearby_inner.winfo_children():
            widget.destroy()
        tk.Label(self._nearby_inner, text="Searching…", bg=SURF, fg=MUTED,
                 font=("Consolas",9)).pack(anchor="w", padx=6, pady=4)
        def on_result(rs, rd):
            items = []
            if rd and isinstance(rd, list):
                for item in rd:
                    if isinstance(item, dict):
                        eid  = item.get("Identifier") or item.get("identifier", "")
                        name = item.get("Name") or item.get("name") or item.get("OriginalName") or ""
                        if eid != "":
                            items.append((eid, name))
            elif rs:
                for line in rs.splitlines():
                    line = line.strip()
                    if not line or "Name" in line or line.startswith("-"):
                        continue
                    if line.startswith("[CommandService") or line == "Success":
                        continue
                    parts = line.split(None, 1)
                    if len(parts) == 2:
                        try:
                            items.append((int(parts[0]), parts[1]))
                        except ValueError:
                            pass
            self._populate_nearby(items)
        self._send_and_capture(f"select find {self._q(target)} {diameter}", on_result, quiet=0.6)

    def _on_group_save(self):
        name = self.v_group_name.get().strip()
        if not name:
            messagebox.showinfo("Enter a name", "Type a group name first.", parent=self)
            return
        checked = [(eid, n) for eid, n, var in self._nearby_items if var.get()]
        if not checked:
            messagebox.showinfo("Nothing checked",
                "Check at least one item in the Nearby list first.", parent=self)
            return
        self._prefab_groups[name] = checked
        vals = ["(none)"] + list(self._prefab_groups.keys())
        self._group_combo["values"] = vals
        self._group_combo_var.set(name)
        self.v_group_name.set("")
        self._append_log(f"[Group '{name}' saved: {len(checked)} item(s)]\n", "ok")

    def _on_group_select(self, event=None):
        name = self._group_combo_var.get()
        if name == "(none)" or name not in self._prefab_groups:
            return
        items = self._prefab_groups[name]
        self._populate_nearby(items)
        self._append_log(f"[Group '{name}' loaded: {len(items)} item(s)]\n", "ok")

    def _on_group_delete(self):
        name = self._group_combo_var.get()
        if name == "(none)" or name not in self._prefab_groups:
            return
        del self._prefab_groups[name]
        vals = ["(none)"] + list(self._prefab_groups.keys())
        self._group_combo["values"] = vals
        self._group_combo_var.set("(none)")
        self._append_log(f"[Group '{name}' deleted]\n", "warn")

    def _on_destroy_selection(self):
        self._send("select destroy")
        # Refresh nearby list so the destroyed object disappears
        self.after(400, self._on_find_nearby)

    def _add_to_history(self, eid, name):
        entry = f"{str(eid):<10} {name}"
        for i, (e, n) in enumerate(self._selection_history):
            if e == eid:
                self._selection_history.pop(i)
                self._history_listbox.delete(i)
                break
        self._selection_history.insert(0, (eid, name))
        self._history_listbox.insert(0, entry)
        if len(self._selection_history) > 50:
            self._selection_history.pop()
            self._history_listbox.delete("end")

    def _on_history_select(self, event=None):
        sel = self._history_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if idx < len(self._selection_history):
            eid, name = self._selection_history[idx]
            self._uncheck_all_nearby()
            self._send(f"select {eid}")

    def _on_history_clear(self):
        self._selection_history.clear()
        self._history_listbox.delete(0, "end")

    def _on_select_prefab(self):
        target = self._current_target()
        if not target:
            return
        prefab = self.v_select_prefab.get().strip()
        if not prefab:
            messagebox.showinfo("Pick a prefab", "Browse for a prefab first.", parent=self)
            return
        self._send(f"select prefab {prefab} {self._q(target)}")

    def _on_get_string(self):
        def on_result(rs, rd):
            if rs:
                self._append_log(f"[Selection string]\n{rs}\n", "ok")
        self._send_and_capture("select tostring", on_result)

    def _on_look_at(self):
        target = self._current_target()
        if not target:
            return
        self._send(f"select look-at {self._q(target)}")

    # ── Move & Rotate tab ───────────────────────────────────────────────────

    def _build_move_tab(self, parent):
        tk.Label(parent, text="Acts on whatever is currently selected in Find & Select.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=680, justify="left"
        ).pack(anchor="w", padx=8, pady=(10,12))

        outer = tk.Frame(parent, bg=BG)
        outer.pack()

        move_box = tk.Frame(outer, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        move_box.pack(side="left", padx=(0,20), pady=4, ipadx=12, ipady=12)
        mrow = tk.Frame(move_box, bg=SURF)
        mrow.pack()
        tk.Label(mrow, text="Move amount", bg=SURF, fg=PARCH,
                 font=("Segoe UI",9,"bold")).grid(row=0, column=0, columnspan=3, pady=(0,6))
        self.v_move_amount = tk.StringVar(value="0.5")
        tk.Entry(mrow, textvariable=self.v_move_amount, bg=SURF2, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, width=6, justify="center").grid(row=0, column=3, pady=(0,6))

        moves = [("↑","forward",1,1),("←","left",2,0),("→","right",2,2),
                 ("↓","back",3,1),("Up","up",1,3),("Down","down",3,3)]
        for label, direction, r, c in moves:
            _btn(mrow, label, lambda d=direction: self._on_move(d), "primary",
                 font=("Segoe UI",11,"bold"), width=5, pady=10).grid(row=r, column=c, padx=5, pady=5)
        _btn(mrow, "Clone", self._on_clone_selection, "primary",
             font=("Segoe UI",11,"bold"), width=5, pady=10).grid(row=2, column=1, padx=5, pady=5)

        rotate_box = tk.Frame(outer, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        rotate_box.pack(side="left", pady=4, ipadx=12, ipady=12)
        rrow = tk.Frame(rotate_box, bg=SURF)
        rrow.pack()
        tk.Label(rrow, text="Rotate degrees", bg=SURF, fg=PARCH,
                 font=("Segoe UI",9,"bold")).grid(row=0, column=0, columnspan=2, pady=(0,6))
        self.v_rotate_degrees = tk.StringVar(value="15")
        tk.Entry(rrow, textvariable=self.v_rotate_degrees, bg=SURF2, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, width=6, justify="center").grid(row=0, column=2, pady=(0,6))

        rotations = [("Pitch −","pitch",-1),("Pitch +","pitch",1),
                     ("Roll −","roll",-1),("Roll +","roll",1),
                     ("Yaw −","yaw",-1),("Yaw +","yaw",1)]
        for i, (label, axis, sign) in enumerate(rotations):
            _btn(rrow, label, lambda a=axis, s=sign: self._on_rotate(a, s), "primary",
                 font=("Segoe UI",9,"bold"), pady=9, padx=8).grid(row=1+i//2, column=i%2, padx=5, pady=5)

        # ── Scale ──────────────────────────────────────────────────────────
        _section_label(parent, "SCALE")
        scale_hint = tk.Label(parent, text="Sets the uniform scale of the selected object (1.0 = normal).",
                 bg=BG, fg=MUTED, font=("Segoe UI",8), wraplength=680, justify="left")
        scale_hint.pack(anchor="w", padx=10, pady=(0,6))
        sf = tk.Frame(parent, bg=BG)
        sf.pack(padx=8, pady=(0,10))
        _btn(sf, "−", lambda: self._scale_step(-0.25), "primary",
             font=("Segoe UI",12,"bold"), width=3, pady=6).pack(side="left")
        self.v_scale = tk.StringVar(value="1.0")
        scale_entry = tk.Entry(sf, textvariable=self.v_scale, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, width=7, justify="center")
        scale_entry.pack(side="left", padx=6)
        scale_entry.bind("<Return>", lambda e: self._on_set_scale())
        _btn(sf, "+", lambda: self._scale_step(0.25), "primary",
             font=("Segoe UI",12,"bold"), width=3, pady=6).pack(side="left")
        _btn(sf, "Set Scale", self._on_set_scale, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=10).pack(side="left", padx=(12,0))

    def _scale_step(self, delta):
        try:
            v = round(float(self.v_scale.get().strip()) + delta, 4)
        except ValueError:
            v = 1.0
        v = max(0.01, min(10.23, v))
        self.v_scale.set(f"{v:.2f}")

    def _on_set_scale(self):
        try:
            scale = float(self.v_scale.get().strip())
        except ValueError:
            messagebox.showinfo("Invalid scale", "Enter a number for the scale.", parent=self)
            return
        scale = max(0.01, min(10.23, scale))
        self.v_scale.set(f"{scale:.4f}".rstrip("0").rstrip("."))
        ids = self._active_entity_ids()
        if ids:
            self._rescale_entity_list(ids, 0, scale)
        else:
            self._rescale_single(scale)

    def _rescale_single(self, scale):
        """Rescale whatever is currently selected on the server."""
        def on_got_string(rs, rd):
            if not rs or rs.startswith("System."):
                messagebox.showinfo("No selection", "Select an object first.", parent=self)
                return
            rescaled = self._rescale_spawn_string(rs, scale)
            if rescaled is None:
                messagebox.showinfo("Scale failed",
                    "Couldn't parse the spawn string for rescaling.", parent=self)
                return
            target = self._current_target()
            if not target:
                return
            self._send("select destroy")
            self._send(f"spawn string {self._q(target)} {self._q(rescaled)}")
        self._send_and_capture("select tostring", on_got_string)

    def _rescale_entity_list(self, ids, i, scale):
        """Recursively rescale each entity in the list."""
        if i >= len(ids):
            return
        self._send(f"select {ids[i]}")
        def on_got_string(rs, rd):
            if rs and not rs.startswith("System."):
                rescaled = self._rescale_spawn_string(rs, scale)
                if rescaled:
                    target = self._current_target()
                    if target:
                        self._send("select destroy")
                        self._send(f"spawn string {self._q(target)} {self._q(rescaled)}")
            self.after(200, lambda: self._rescale_entity_list(ids, i + 1, scale))
        self.after(80, lambda: self._send_and_capture("select tostring", on_got_string))

    @staticmethod
    def _rescale_spawn_string(spawn_string, scale):
        """
        Rewrite the scale in an ATT spawn string.
        Format: "w0,w1,...,w10,...[|part2|...]"
        Word index 10 in the first pipe-section is the scale stored as the
        raw uint32 bit-representation of a float32 (big-endian).
        Matches Prefabulator's rescaleString() exactly.
        """
        import struct
        try:
            scale = max(0.01, min(10.23, scale))
            parts = spawn_string.split("|")
            words = parts[0].split(",")
            bits = struct.unpack(">I", struct.pack(">f", scale))[0]
            words[10] = str(bits)
            parts[0] = ",".join(words)
            return "|".join(parts)
        except Exception:
            return None

    def _uncheck_all_nearby(self):
        """Clears every ticked checkbox in the Nearby list. Called whenever
        something makes a single, explicit selection elsewhere (clicking a
        Nearby row's own label, or picking one from Recently Selected) --
        without this, a leftover checked group would silently keep taking
        priority in _active_entity_ids() over the selection the user just
        made, so Move/Clone/etc. would act on stale entities instead of
        the one just picked."""
        for eid, name, var in self._nearby_items:
            if var.get():
                var.set(False)
        # Row backgrounds reflect checked state -- refresh them all back
        # to normal now that nothing is checked.
        rows = self._nearby_inner.winfo_children()
        for row in rows:
            row.config(bg=SURF)
            for c in row.winfo_children():
                try: c.config(bg=SURF)
                except Exception: pass

    def _active_entity_ids(self):
        """Return list of entity IDs to act on.
        Priority:
        1. A saved group is selected in the dropdown → use that group's IDs
        2. Any checkboxes are ticked in the nearby list → use those IDs
        3. Neither → return None (act on current single server selection)
        """
        name = self._group_combo_var.get()
        if name != "(none)" and name in self._prefab_groups:
            return [eid for eid, _ in self._prefab_groups[name]]
        checked = [eid for eid, n, var in self._nearby_items if var.get()]
        if checked:
            return checked
        return None

    def _send_to_selection(self, cmd):
        """Send a command, repeating it for each entity in the active group
        (selecting each in turn), or just once for single selection."""
        ids = self._active_entity_ids()
        if ids:
            def send_next(i=0):
                if i >= len(ids):
                    return
                self._send(f"select {ids[i]}")
                self.after(80, lambda: (self._send(cmd), self.after(80, lambda: send_next(i+1))))
            send_next()
        else:
            self._send(cmd)

    def _on_move(self, direction):
        try:
            amount = float(self.v_move_amount.get().strip())
        except ValueError:
            messagebox.showinfo("Invalid amount", "Enter a number for the move amount.", parent=self)
            return
        self._send_to_selection(f"select move {direction} {amount}")

    def _on_rotate(self, axis, sign):
        try:
            degrees = float(self.v_rotate_degrees.get().strip()) * sign
        except ValueError:
            messagebox.showinfo("Invalid amount", "Enter a number for the rotate degrees.", parent=self)
            return
        self._send_to_selection(f"select rotate {axis} {degrees}")

    def _on_clone_selection(self):
        """Duplicate the current single selection or every entity in the active group."""
        ids = self._active_entity_ids()
        if ids:
            self._clone_entity_list(ids, 0)
        else:
            def on_result(rs, rd):
                spawn_string = TavernKeeperWindow._clean_spawn_string(rs) if rs else None
                if not spawn_string:
                    messagebox.showinfo("No selection", "Select an object first.", parent=self)
                    return
                self._send(f"spawn string-raw {self._q(spawn_string)}")
            self._send_and_capture("select tostring", on_result)

    def _clone_entity_list(self, ids, i):
        """Recursively clone every entity in a selected group."""
        if i >= len(ids):
            return
        eid = ids[i]
        self._send(f"select {eid}")

        def on_result(rs, rd):
            spawn_string = TavernKeeperWindow._clean_spawn_string(rs) if rs else None
            if spawn_string:
                self._send(f"spawn string-raw {self._q(spawn_string)}")
            self.after(150, lambda: self._clone_entity_list(ids, i + 1))

        self.after(80, lambda: self._send_and_capture("select tostring", on_result))

    # ── Server Settings tab ─────────────────────────────────────────────────

    # The exact settings Prefabulator's own Server Settings tab exposed —
    # (label, setting name, default shown to the user, is this a toggle).
    _SERVER_SETTINGS_FIELDS = [
        ("Drop all on death",                    "DropAllOnDeath",            True),
        ("Seconds before respawn",                "RespawnTimeSeconds",        False),
        ("Time speed multiplier",                 "TimeSpeedMultiplier",       False),
        ("Experience multiplier",                 "XPX",                       False),
        ("Global damage multiplier",              "DamageX",                   False),
        ("PVP damage enabled",                    "IsPVPEnabled",              True),
        ("PVP damage multiplier",                 "PVPMultiplier",             False),
        ("PVP cripple multiplier",                "PVPCrippleMultiplier",      False),
        ("Hunger deals damage",                   "HungerDealsDamage",         True),
        ("Hunger tick rate",                      "HungerTick",                False),
        ("Community storage multiplier",          "CommunityStorageMultiplier",False),
    ]

    def _build_settings_tab(self, parent):
        canvas_frame = tk.Frame(parent, bg=BG)
        canvas_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_frame, bg=BG, highlightthickness=0)
        vsb = _mk_scrollbar(canvas_frame, canvas.yview)
        vsb.pack(side="right", fill="y")
        canvas.config(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        def _settings_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _settings_mousewheel)
        inner.bind("<MouseWheel>", _settings_mousewheel)

        _section_label(inner, "SERVER CLOCK")
        row = tk.Frame(inner, bg=BG)
        row.pack(fill="x", padx=8, pady=(0,4))
        self.v_time_value = tk.StringVar(value="12:00")
        tk.Entry(row, textvariable=self.v_time_value, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=8).pack(side="left")
        _btn(row, "Set Time", self._on_time_set, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=10).pack(side="left", padx=(6,6))
        _btn(row, "Toggle Day/Night", lambda: self._send("time toggle"),
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left")
        _hint(inner, "24-hour time, e.g. 14:30 for 2:30pm.")

        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", padx=8, pady=12)
        _section_label(inner, "SERVER SETTINGS")
        _hint(inner, "Values apply immediately but are not read back from the server.")

        self._settings_vars = {}
        for label, name, is_toggle in self._SERVER_SETTINGS_FIELDS:
            row = tk.Frame(inner, bg=BG)
            row.pack(fill="x", padx=8, pady=4)
            tk.Label(row, text=label, bg=BG, fg=PARCH, font=("Segoe UI",9),
                     width=34, anchor="w").pack(side="left")
            if is_toggle:
                _btn(row, "On", lambda n=name: self._on_settings_apply(n, "true"),
                     font=("Segoe UI",9,"bold"), pady=4, padx=10).pack(side="left")
                _btn(row, "Off", lambda n=name: self._on_settings_apply(n, "false"),
                     font=("Segoe UI",9), pady=4, padx=10).pack(side="left", padx=(6,0))
            else:
                v = tk.StringVar(value="")
                self._settings_vars[name] = v
                tk.Entry(row, textvariable=v, bg=SURF, fg=PARCH,
                         insertbackground=AMBER, relief="flat", font=("Consolas",10),
                         bd=4, width=10).pack(side="left")
                _btn(row, "Set", lambda n=name, var=v: self._on_settings_apply(n, var.get().strip()),
                     "primary", font=("Segoe UI",9,"bold"), pady=4, padx=10).pack(side="left", padx=(6,0))

    def _on_time_set(self):
        raw = self.v_time_value.get().strip()
        # Matches the same HH:MM -> HH.MM conversion Prefabulator itself
        # used for its server clock field.
        value = raw.replace(":", ".", 1)
        self._send(f"time set {value}")

    def _on_settings_apply(self, name, value):
        if not value:
            messagebox.showinfo("Enter a value", f"Type a value for {name} first.", parent=self)
            return
        self._send(f"settings changesetting server {name} {value}")

    # ── Save & Load tab ──────────────────────────────────────────────────────

    def _build_saveload_tab(self, parent):
        tk.Label(parent, text="Build a list of prefabs to save, then export it to a file you "
                              "can load again later — even on a different server.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=680, justify="left"
        ).pack(anchor="w", padx=8, pady=(10,8))

        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", padx=8, pady=(0,6))
        _btn(row, "+ Add Current Selection", self._on_add_to_save_list, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=10).pack(side="left")
        _btn(row, "− Remove Selected", self._on_remove_from_save_list, "danger",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)

        _section_label(parent, "STAGED ITEMS")
        lb = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True, padx=8, pady=(0,8))
        self._save_listbox = tk.Listbox(lb, bg=SURF, fg=PARCH,
                                        selectbackground=AMBERDIM, selectforeground="#ffd080",
                                        relief="flat", bd=0, font=("Consolas",10),
                                        activestyle="none")
        sb3 = _mk_scrollbar(lb, self._save_listbox.yview)
        sb3.pack(side="right", fill="y")
        self._save_listbox.config(yscrollcommand=sb3.set)
        self._save_listbox.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self._save_listbox.bind("<Double-Button-1>", self._on_rename_save_item)

        row2 = tk.Frame(parent, bg=BG)
        row2.pack(fill="x", padx=8, pady=(0,12))
        _btn(row2, "💾 Save to File…", self._on_save_to_file, "primary",
             font=("Segoe UI",9,"bold"), pady=7, padx=12).pack(side="left")
        _btn(row2, "📂 Load from File…", self._on_load_from_file,
             font=("Segoe UI",9), pady=7, padx=12).pack(side="left", padx=6)
        _btn(row2, "🪄 Spawn All", self._on_spawn_all_saved, "primary",
             font=("Segoe UI",9,"bold"), pady=7, padx=12).pack(side="right")

    @staticmethod
    def _clean_spawn_string(rs):
        """Extract the raw spawn string from a select tostring ResultString.
        The WS console returns the spawn string directly as ResultString.
        Strip whitespace and skip useless type-name noise."""
        if not rs:
            return None
        s = rs.strip()
        if not s or s.startswith("System."):
            return None
        return s

    def _on_add_to_save_list(self):
        ids = self._active_entity_ids()
        if ids:
            # Group is active — capture tostring for each entity in sequence
            self._add_group_to_save_list(ids, 0)
        else:
            # Single selection
            def on_result(rs, rd):
                spawn_string = TavernKeeperWindow._clean_spawn_string(rs) if rs else None
                if not spawn_string:
                    messagebox.showinfo("Nothing to add",
                        "Select something in Find & Select first.", parent=self)
                    return
                label = f"Item {len(self._save_items)+1}"
                self._save_items.append((label, spawn_string))
                self._save_listbox.insert("end", label)
            self._send_and_capture("select tostring", on_result)

    def _add_group_to_save_list(self, ids, i):
        """Recursively select each group entity, capture its tostring, add to list."""
        if i >= len(ids):
            return
        eid = ids[i]
        self._send(f"select {eid}")
        def on_result(rs, rd):
            spawn_string = TavernKeeperWindow._clean_spawn_string(rs) if rs else None
            if spawn_string:
                label = f"Item {len(self._save_items)+1}"
                self._save_items.append((label, spawn_string))
                self._save_listbox.insert("end", label)
            # Move to next entity after a short delay
            self.after(150, lambda: self._add_group_to_save_list(ids, i + 1))
        self.after(80, lambda: self._send_and_capture("select tostring", on_result))

    def _on_rename_save_item(self, event=None):
        sel = self._save_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        old_label, spawn_string = self._save_items[idx]
        new_label = simpledialog.askstring(
            "Rename item", "Enter a new name:",
            initialvalue=old_label, parent=self)
        if new_label and new_label.strip():
            new_label = new_label.strip()
            self._save_items[idx] = (new_label, spawn_string)
            self._save_listbox.delete(idx)
            self._save_listbox.insert(idx, new_label)
            self._save_listbox.selection_set(idx)

    def _on_remove_from_save_list(self):
        sel = self._save_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        del self._save_items[idx]
        self._save_listbox.delete(idx)

    def _on_save_to_file(self):
        if not self._save_items:
            messagebox.showinfo("Nothing staged",
                "Add at least one item to the list first.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="Save prefab collection", defaultextension=".json",
            filetypes=[("JSON files","*.json"),("All files","*.*")], parent=self)
        if not path:
            return
        try:
            data = [{"label": label, "string": s} for label, s in self._save_items]
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            messagebox.showinfo("Saved", f"Saved {len(data)} item(s).", parent=self)
        except Exception as e:
            messagebox.showerror("Couldn't save", str(e), parent=self)

    def _on_load_from_file(self):
        path = filedialog.askopenfilename(
            title="Load prefab collection",
            filetypes=[("JSON files","*.json"),("All files","*.*")], parent=self)
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._save_items = [(d.get("label","Item"), d["string"]) for d in data if "string" in d]
            self._save_listbox.delete(0, "end")
            for label, _ in self._save_items:
                self._save_listbox.insert("end", label)
        except Exception as e:
            messagebox.showerror("Couldn't load", str(e), parent=self)

    def _on_spawn_all_saved(self):
        if not self._save_items:
            messagebox.showinfo("Nothing staged",
                "Add or load some items first.", parent=self)
            return
        def spawn_next(i=0):
            if i >= len(self._save_items):
                return
            _, s = self._save_items[i]
            self._send(f"spawn string-raw {self._q(s)}")
            self.after(200, lambda: spawn_next(i+1))
        spawn_next()

    # ── Player Admin tab ─────────────────────────────────────────────────────

    def _build_admin_tab(self, parent):
        # Outer scrollable canvas so stats list doesn't overflow
        cf = tk.Frame(parent, bg=BG)
        cf.pack(fill="both", expand=True)
        canvas = tk.Canvas(cf, bg=BG, highlightthickness=0)
        vsb = _mk_scrollbar(cf, canvas.yview)
        vsb.pack(side="right", fill="y")
        canvas.config(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas, bg=BG)
        canvas.create_window((0,0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(
            scrollregion=canvas.bbox("all")))

        def _admin_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind("<MouseWheel>", _admin_mousewheel)
        inner.bind("<MouseWheel>", _admin_mousewheel)

        tk.Label(inner, text="Acts on the target player selected above.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=680, justify="left"
        ).pack(anchor="w", padx=8, pady=(10,10))

        row = tk.Frame(inner, bg=BG)
        row.pack(fill="x", padx=8, pady=(0,10))
        _btn(row, "Kick", self._on_kick, "primary",
             font=("Segoe UI",9,"bold"), pady=7, padx=16).pack(side="left")
        _btn(row, "Kill", self._on_kill, "danger",
             font=("Segoe UI",9,"bold"), pady=7, padx=16).pack(side="left", padx=6)

        _section_label(inner, "MESSAGE")
        mf = _field(inner)
        self.v_admin_message = tk.StringVar()
        tk.Entry(mf, textvariable=self.v_admin_message, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        durf = tk.Frame(inner, bg=BG)
        durf.pack(fill="x", padx=8, pady=(0,4))
        tk.Label(durf, text="Duration (seconds):", bg=BG, fg=PARCH,
                 font=("Segoe UI",9)).pack(side="left")
        self.v_admin_duration = tk.StringVar(value="5")
        tk.Entry(durf, textvariable=self.v_admin_duration, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=6).pack(side="left", padx=(6,10))
        _btn(durf, "Send Message", self._on_message, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=10).pack(side="left")
        _btn(durf, "Send to All", self._on_message_all,
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=(6,0))

        _section_label(inner, "TELEPORT TO")
        ttf = _field(inner)
        self.v_teleport_target = tk.StringVar()
        tk.Entry(ttf, textvariable=self.v_teleport_target, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        _hint(inner, "Another player's name to teleport to them.")
        _btn(inner, "Teleport to Player", self._on_teleport, "primary",
             font=("Segoe UI",9,"bold"), pady=6).pack(fill="x", padx=8, pady=(4,6))

        _hint(inner, "Quick teleport to a spawn area:")
        # Row 1
        qr1 = tk.Frame(inner, bg=BG)
        qr1.pack(fill="x", padx=8, pady=(0,3))
        for label, dest in [("Spawn", "RespawnPoint"), ("Outside Cave", "OutsideCave"),
                             ("Outside Forest", "OutsideForest")]:
            _btn(qr1, label, lambda d=dest: self._on_quick_teleport(d),
                 font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(0,4))
        # Row 2
        qr2 = tk.Frame(inner, bg=BG)
        qr2.pack(fill="x", padx=8, pady=(0,3))
        for label, dest in [("Outside Tower", "OutsideTower"), ("Outside Lake", "OutsideLake"),
                             ("Mountain Pass", "MountainPass")]:
            _btn(qr2, label, lambda d=dest: self._on_quick_teleport(d),
                 font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(0,4))
        # Row 3
        qr3 = tk.Frame(inner, bg=BG)
        qr3.pack(fill="x", padx=8, pady=(0,3))
        for label, dest in [("Glades", "Glades"), ("Rock Arena", "OutsideRockArena"),
                             ("Battlefield", "BattleField")]:
            _btn(qr3, label, lambda d=dest: self._on_quick_teleport(d),
                 font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(0,4))
        # Row 4
        qr4 = tk.Frame(inner, bg=BG)
        qr4.pack(fill="x", padx=8, pady=(0,3))
        for label, dest in [("Tower CP1", "TowerCP1"), ("Tower CP2", "TowerCP2"),
                             ("Tower End", "TowerEnd")]:
            _btn(qr4, label, lambda d=dest: self._on_quick_teleport(d),
                 font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(0,4))
        # Row 5
        qr5 = tk.Frame(inner, bg=BG)
        qr5.pack(fill="x", padx=8, pady=(0,6))
        for label, dest in [("Woodcutting Shrine", "WoodcuttingShrine"),
                             ("Archery Shrine", "ArcheryShrine"),
                             ("Melee Shrine", "MeleeShrine")]:
            _btn(qr5, label, lambda d=dest: self._on_quick_teleport(d),
                 font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(0,4))

        _section_label(inner, "SET HOME")
        shf = _field(inner)
        self.v_sethome_value = tk.StringVar(value="reset")
        tk.Entry(shf, textvariable=self.v_sethome_value, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        _hint(inner, "'reset' clears it back to the respawn point.")
        _btn(inner, "Set Home", self._on_set_home, "primary",
             font=("Segoe UI",9,"bold"), pady=6).pack(fill="x", padx=8, pady=(4,10))

        # ── Player Stats ─────────────────────────────────────────────────
        tk.Frame(inner, bg=BORDER, height=1).pack(fill="x", padx=8, pady=(4,0))
        sh = tk.Frame(inner, bg=BG)
        sh.pack(fill="x", padx=8, pady=(6,2))
        _section_label(inner, "PLAYER STATS")
        _btn(inner, "Refresh Stats", self._on_refresh_stats, "primary",
             font=("Segoe UI",8,"bold"), pady=4, padx=8).pack(anchor="w", padx=8, pady=(0,8))

        # stat sliders grid — two columns
        stats_frame = tk.Frame(inner, bg=BG)
        stats_frame.pack(fill="x", padx=8, pady=(0,12))
        self._stat_vars = {}  # name -> DoubleVar
        stats = [('health', 'Health', 0, 2), ('maxhealth', 'Max Health', 0, 31), ('speed', 'Speed', 0, 15), ('damage', 'Damage', 0, 15), ('poison', 'Poison', 0, 31), ('hunger', 'Hunger', 0, 2), ('damageprotection', 'Damage Protection', 0.1, 10), ('crippledamageprotection', 'Cripple Dmg Protection', 0.1, 10), ('luminosity', 'Luminosity', 0, 15), ('cripplehealth', 'Cripple Health', 0, 1), ('xpboost', 'XP Boost', 0.1, 10), ('nightmare', 'Nightmare', 0, 1), ('fullness', 'Fullness', 0, 6), ('left-hand-stamina', 'L. Stamina', 0, 0.2), ('right-hand-stamina', 'R. Stamina', 0, 0.2), ('maxHandStamina', 'Max Hand Stamina', 0.2, 0.4), ('aggro', 'Aggro', 1, 10), ('Frost', 'Frost', 0, 1), ('playerweight', 'Player Weight', 0, 99999), ('recentdamage', 'Recent Damage', 0, 1)]
        for i, (stat_name, label, smin, smax) in enumerate(stats):
            col = i % 2
            row_idx = i // 2
            cell = tk.Frame(stats_frame, bg=SURF, highlightbackground=BORDER,
                             highlightthickness=1)
            cell.grid(row=row_idx, column=col, sticky="ew", padx=(0 if col else 0, 6 if col==0 else 0),
                      pady=3, ipadx=6, ipady=4)
            stats_frame.columnconfigure(col, weight=1)
            tk.Label(cell, text=label, bg=SURF, fg=PARCH,
                     font=("Segoe UI",8,"bold"), anchor="w").pack(fill="x", padx=6, pady=(4,0))
            var = tk.DoubleVar(value=0.0)
            self._stat_vars[stat_name] = var
            entry_row = tk.Frame(cell, bg=SURF)
            entry_row.pack(fill="x", padx=4, pady=(2,4))
            entry = tk.Entry(entry_row, textvariable=var, bg=SURF2, fg=PARCH,
                             insertbackground=AMBER, relief="flat",
                             font=("Consolas",10), bd=4, width=8, justify="center")
            entry.pack(side="left", padx=(0,4))
            tk.Label(entry_row, text=f"{smin}–{smax}", bg=SURF, fg=MUTED,
                     font=("Segoe UI",7)).pack(side="left", padx=(0,6))
            _btn(entry_row, "Set", lambda sn=stat_name, v=var: self._on_set_stat(sn, v),
                 font=("Segoe UI",8,"bold"), pady=3, padx=8).pack(side="left")

    def _on_kick(self):
        target = self._current_target()
        if not target:
            return
        self._send(f"player kick {self._q(target)}")

    def _on_kill(self):
        target = self._current_target()
        if not target:
            return
        self._send(f"player kill {self._q(target)}")

    def _on_message(self):
        target = self._current_target()
        if not target:
            return
        msg = self.v_admin_message.get().strip()
        if not msg:
            return
        try:
            duration = float(self.v_admin_duration.get().strip())
        except ValueError:
            duration = 5
        self._send(f"player message {self._q(target)} {self._q(msg)} {duration}")

    def _on_message_all(self):
        msg = self.v_admin_message.get().strip()
        if not msg:
            return
        try:
            duration = float(self.v_admin_duration.get().strip())
        except ValueError:
            duration = 5
        self._send(f"player message * {self._q(msg)} {duration}")

    def _on_teleport(self):
        target = self._current_target()
        if not target:
            return
        dest = self.v_teleport_target.get().strip()
        if not dest:
            messagebox.showinfo("Enter a destination", "Type a player name to teleport to.", parent=self)
            return
        self._send(f"player teleport {self._q(target)} {self._q(dest)}")

    def _on_quick_teleport(self, spawn_area_identifier):
        target = self._current_target()
        if not target:
            return
        self._send(f"player teleport {self._q(target)} {spawn_area_identifier}")

    def _on_set_home(self):
        target = self._current_target()
        if not target:
            return
        home = self.v_sethome_value.get().strip() or "reset"
        self._send(f"player set-home {self._q(target)} {self._q(home)}")

    def _on_set_stat(self, stat_name, var):
        target = self._current_target()
        if not target:
            return
        try:
            value = float(var.get())
        except (ValueError, tk.TclError):
            messagebox.showinfo("Invalid value", f"Enter a number for {stat_name}.", parent=self)
            return
        def on_refresh(rs, rd):
            if rd and isinstance(rd, list):
                for item in rd:
                    if isinstance(item, dict):
                        n = item.get("Name","")
                        v = item.get("Value")
                        if n in self._stat_vars and v is not None:
                            try:
                                self._stat_vars[n].set(round(float(v), 4))
                            except Exception:
                                pass

        self._send(f"player set-stat {self._q(target)} {stat_name} {value}")
        self._send_and_capture(f"player list-stats {self._q(target)}", on_refresh)

    def _on_refresh_stats(self):
        target = self._current_target()
        if not target:
            return
        def on_result(rs, rd):
            if rd and isinstance(rd, list):
                for item in rd:
                    if isinstance(item, dict):
                        n = item.get("Name","")
                        v = item.get("Value")
                        if n in self._stat_vars and v is not None:
                            try:
                                self._stat_vars[n].set(round(float(v), 4))
                            except Exception:
                                pass
            elif rs:
                self._append_log(f"[Stats]\n{rs}\n", "ok")
        self._send_and_capture(f"player list-stats {self._q(target)}", on_result)


    def _build_tabs_notebook(self):
        nb = ttk.Notebook(self._tabs_container, style="Tavk.TNotebook")
        nb.pack(fill="both", expand=True)
        self._nb = nb
        self._tab_frames = {}
        for tab in ordered_tabs():
            frame = tk.Frame(nb, bg=BG)
            nb.add(frame, text=f"  {tab['label']}  ")
            self._tab_frames[tab["key"]] = frame
            tab["build_fn"](frame, self)

    def _rebuild_tabs(self):
        for child in self._tabs_container.winfo_children():
            child.destroy()
        self._build_tabs_notebook()

    def _open_jump_to_tab(self):
        menu = tk.Menu(self, tearoff=0, bg=SURF, fg=PARCH,
                        activebackground=AMBERDIM, activeforeground="#ffd080")
        for tab in ordered_tabs():
            frame = self._tab_frames.get(tab["key"])
            if frame is not None:
                menu.add_command(label=tab["label"], command=lambda f=frame: self._nb.select(f))
        try:
            x = self.winfo_pointerx()
            y = self.winfo_pointery()
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _open_reorder_tabs(self):
        ReorderDialog(self, registry(), title="Reorder Tabs", on_saved=self._rebuild_tabs)

    def _on_close(self):
        self._stop.set()
        if hasattr(self, "_ws_client") and self._ws_client:
            self._ws_client.disconnect()
        self.destroy()


register_tab("spawn", "Spawn", lambda parent, window: window._build_spawn_tab(parent), built_in=True)
register_tab("select", "Find & Select", lambda parent, window: window._build_select_tab(parent), built_in=True)
register_tab("move", "Move & Rotate", lambda parent, window: window._build_move_tab(parent), built_in=True)
register_tab("settings", "Server Settings", lambda parent, window: window._build_settings_tab(parent), built_in=True)
register_tab("saveload", "Save & Load", lambda parent, window: window._build_saveload_tab(parent), built_in=True)
register_tab("admin", "Player Admin", lambda parent, window: window._build_admin_tab(parent), built_in=True)
