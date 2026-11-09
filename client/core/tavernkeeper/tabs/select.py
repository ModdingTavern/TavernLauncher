"""The Find & Select tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, _btn, _field, _section_label,
    _mk_scrollbar, _fix_combobox_popdown_colors,
)


class SelectTabMixin:
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
