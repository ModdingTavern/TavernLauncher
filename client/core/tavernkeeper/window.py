"""
TavernKeeper: native prefab spawn/select/move/settings/admin tool, run on
a remote-console connection. Core tabs (Spawn, Find & Select, Move &
Rotate, Server Settings, Save & Load, Player Admin) live in tabs/, as
mixins of the window below; anything else -- e.g. the Macros tab -- comes from an addon
registering itself through client.core.tavernkeeper.registry, and is
inserted at the position it asks for without this file needing to know
the addon exists.
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO, _btn,
    _section_label, _mk_scrollbar, _fix_combobox_popdown_colors,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from client.core.tavernkeeper.registry import register_tab, ordered_tabs, registry
from tavern_shared.reorder_dialog import ReorderDialog
from client.core.tavernkeeper.connection import ConnectionMixin
from client.core.tavernkeeper.tabs.spawn import SpawnTabMixin
from client.core.tavernkeeper.tabs.select import SelectTabMixin
from client.core.tavernkeeper.tabs.move import MoveTabMixin
from client.core.tavernkeeper.tabs.settings import SettingsTabMixin
from client.core.tavernkeeper.tabs.saveload import SaveLoadTabMixin
from client.core.tavernkeeper.tabs.admin import AdminTabMixin


class TavernKeeperWindow(
    ConnectionMixin,
    SpawnTabMixin,
    SelectTabMixin,
    MoveTabMixin,
    SettingsTabMixin,
    SaveLoadTabMixin,
    AdminTabMixin,
    tk.Toplevel,
):
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
        # Packed by _on_disconnected, hidden again once reconnected
        self._reconnect_btn = _btn(h, "Reconnect", self._reconnect,
             font=("Segoe UI",8), pady=3, padx=8)
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
