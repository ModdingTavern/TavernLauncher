"""The Spawn tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import os
import re
import json
import tkinter as tk
from tkinter import messagebox

from tavern_shared.theme import (
    BG, SURF, BORDER, AMBER, AMBERDIM, PARCH, MUTED, _btn, _field, _section_label,
    _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.paths import _tavern_data_dir


class SpawnTabMixin:
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
        cmd = f"spawn {self._q_target(target)} {self._q(prefab)}"
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
        if self.models.prefabs is not None:
            self._show_prefab_picker(target_var)
            return
        cached = self._load_prefabs_cache()
        if cached:
            self.models.prefabs = cached
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
            self.models.prefabs = prefabs
            self._save_prefabs_cache(self.models.prefabs)
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

        state = {"filtered": list(self.models.prefabs)}

        def refresh_list(*_):
            query = v_search.get().strip().lower()
            if query:
                state["filtered"] = [(h,n) for h,n in self.models.prefabs
                                      if query in n.lower() or query == str(h)]
            else:
                state["filtered"] = list(self.models.prefabs)
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
