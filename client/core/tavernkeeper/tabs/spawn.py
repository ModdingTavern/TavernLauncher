"""The Spawn section of the Build tab, and the prefab picker.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import os
import re
import json
import tkinter as tk
from tkinter import messagebox

from tavern_shared.theme import (
    BG, SURF, BORDER, AMBER, AMBERDIM, PARCH, MUTED, RED, _btn, _section_label, _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.paths import _tavern_data_dir
from client.core.tavernkeeper.widgets import (
    form_button, form_entry, form_row, form_text, parse_vector, read_number, say, status_line,
)

MAX_SPAWN_COUNT = 50


class SpawnTabMixin:
    # ── Spawn section ────────────────────────────────────────────────────────

    def _build_spawn_section(self, parent):
        _section_label(parent, "SPAWN")
        row = form_row(parent)
        form_text(row, "Prefab:")
        self.v_spawn_prefab = tk.StringVar()
        entry = form_entry(row, self.v_spawn_prefab, 24)
        entry.pack_configure(fill="x", expand=True)
        self._bind_prefab_autocomplete(entry, self.v_spawn_prefab)
        form_button(row, "Browse Prefabs…", lambda: self._open_prefab_picker(self.v_spawn_prefab), "primary")

        row = form_row(parent)
        form_text(row, "Arguments:")
        self.v_spawn_args = tk.StringVar()
        form_entry(row, self.v_spawn_args, 16).pack_configure(fill="x", expand=True)
        form_text(row, "Count:")
        self.v_spawn_count = tk.StringVar(value="1")
        form_entry(row, self.v_spawn_count, 4)
        form_button(row, "Spawn at Target Player", self._on_spawn, "primary")

        row = form_row(parent)
        form_text(row, "Exact:")
        self.v_spawn_position = tk.StringVar()
        form_entry(row, self.v_spawn_position, 22)
        form_button(row, "Target's Position", self._on_use_target_position)
        form_text(row, "Rotation:")
        self.v_spawn_rotation = tk.StringVar(value="0,0,0")
        form_entry(row, self.v_spawn_rotation, 9)
        form_button(row, "Spawn Exact", self._on_spawn_exact, "primary")
        self._say_spawn = status_line(parent)

    def _spawn_prefab(self):
        prefab = self.v_spawn_prefab.get().strip()
        if not prefab:
            say(self._say_spawn, "Pick or type a prefab first.", RED)
        return prefab

    def _on_spawn(self):
        label = self._say_spawn
        target = self._current_target()
        prefab = self._spawn_prefab() if target else None
        if not prefab:
            return
        count = read_number(self.v_spawn_count, label, "the count", int)
        if count is None:
            return
        if not 1 <= count <= MAX_SPAWN_COUNT:
            say(label, f"The count has to be from 1 to {MAX_SPAWN_COUNT}.", RED)
            return
        args = self.v_spawn_args.get().strip()
        cmd = f"spawn {self._q_target(target)} {self._q(prefab)}" + (f" {args}" if args else "")
        self._send_series([cmd] * count, label, f"Spawned {count} at {target}.", target=target)

    def _on_use_target_position(self):
        label = self._say_spawn
        target = self._current_target()
        if not target:
            return

        def got(result):
            position = result.value.get("Position") if result.ok and isinstance(result.value, dict) else None
            if position is None:
                self._answer_on(label, "Couldn't read where they are.", color=RED)(result)
            else:
                self.v_spawn_position.set(",".join(f"{v:.3f}" for v in position))
                say(label, "")
        self._run_command(f"player detailed {self._q_target(target)}", got, quiet=True)

    def _on_spawn_exact(self):
        label = self._say_spawn
        prefab = self._spawn_prefab()
        if not prefab:
            return
        position = parse_vector(self.v_spawn_position.get())
        rotation = parse_vector(self.v_spawn_rotation.get())
        if position is None or rotation is None:
            say(label, "Position and rotation need three numbers, like 10,20,30.", RED)
            return
        args = self.v_spawn_args.get().strip()
        cmd = f"spawn exact {position} {rotation} {self._q(prefab)}" + (f" {args}" if args else "")
        self._send_and_say(cmd, label, f"Spawned at {position}.")

    def _prefabs_cache_path(self):
        host = re.sub(r"[^\w.-]", "_", self.v_host.get().strip() or "127.0.0.1")
        return os.path.join(_tavern_data_dir(), f"prefabs-{host}.json")

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
