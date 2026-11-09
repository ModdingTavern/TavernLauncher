"""The Find section of the Build tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import tkinter as tk
from tkinter import ttk, messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, RED, _btn, _section_label,
    _mk_scrollbar, _fix_combobox_popdown_colors,
)
from tavern_shared.screen_fit import bind_wheel, wheel_step
from client.core.tavernkeeper.widgets import confirm, entity_name, say


class SelectTabMixin:
    # ── Find section ─────────────────────────────────────────────────────────

    def _build_find_section(self, parent):
        _section_label(parent, "FIND")
        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x", padx=8, pady=(0,6))
        tk.Label(top, text="Diameter:", bg=BG, fg=PARCH,
                 font=("Segoe UI",9)).pack(side="left")
        self.v_radius = tk.StringVar(value="10")
        tk.Entry(top, textvariable=self.v_radius, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=6).pack(side="left", padx=(6,10))
        _btn(top, "🔍 Find Nearby", self._on_find_nearby, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=12).pack(side="left")

        gf = tk.Frame(parent, bg=BG)
        gf.pack(fill="x", padx=8, pady=(0,4))
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
                                          font=("Consolas",9), width=14, state="readonly",
                                          style="Tavk.Group.TCombobox")
        self._group_combo["values"] = ["(none)"]
        self._group_combo.pack(side="left", padx=(4,6))
        self._group_combo.bind("<<ComboboxSelected>>", self._on_group_select)
        _fix_combobox_popdown_colors(self._group_combo, SURF, PARCH, AMBERDIM, "#ffd080")
        _btn(gf, "✕ Delete Group", self._on_group_delete,
             font=("Segoe UI",8), pady=3, padx=6).pack(side="left")
        gs = tk.Frame(parent, bg=BG)
        gs.pack(fill="x", padx=8, pady=(0,6))
        self.v_group_name = tk.StringVar()
        tk.Entry(gs, textvariable=self.v_group_name, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",9),
                 bd=4, width=14).pack(side="left", padx=(0,4))
        _btn(gs, "Save Checked as Group", self._on_group_save, "primary",
             font=("Segoe UI",8,"bold"), pady=3, padx=6).pack(side="left")

        tk.Label(parent, text="NEARBY  (✓ = group)", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).pack(anchor="w", padx=8, pady=(0,2))
        lb = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True, padx=8, pady=(0,6))
        self._nearby_canvas = tk.Canvas(lb, bg=SURF, highlightthickness=0, height=200, width=200)
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
            self._nearby_canvas.yview_scroll(wheel_step(event), "units")
        bind_wheel(self._nearby_canvas, _nearby_mousewheel)
        bind_wheel(self._nearby_inner, _nearby_mousewheel)
        self._nearby_mousewheel = _nearby_mousewheel

        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", padx=8, pady=(0,2))
        tk.Label(head, text="SELECTION HISTORY", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).pack(side="left")
        _btn(head, "Clear", self._on_history_clear,
             font=("Segoe UI",7), pady=1, padx=6).pack(side="right")
        hf = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        hf.pack(fill="x", padx=8, pady=(0,6))
        self._history_listbox = tk.Listbox(hf, bg=SURF, fg=PARCH,
                                            selectbackground=AMBERDIM,
                                            selectforeground="#ffd080",
                                            relief="flat", bd=0, height=4,
                                            highlightthickness=0,
                                            font=("Consolas",8),
                                            activestyle="none")
        hsb = _mk_scrollbar(hf, self._history_listbox.yview)
        hsb.pack(side="right", fill="y")
        self._history_listbox.config(yscrollcommand=hsb.set)
        self._history_listbox.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        # Click history entry to re-select that entity
        self._history_listbox.bind("<<ListboxSelect>>", self._on_history_select)

        self._nearby_vars = {}
        self._nearby_listbox = None

        tk.Label(parent, text="NEAREST BY PREFAB", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).pack(anchor="w", padx=8, pady=(0,2))
        spf = tk.Frame(parent, bg=BG)
        spf.pack(fill="x", padx=8, pady=(0,8))
        self.v_select_prefab = tk.StringVar()
        select_prefab_entry = tk.Entry(spf, textvariable=self.v_select_prefab, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=12)
        select_prefab_entry.pack(side="left", fill="x", expand=True, padx=(0,4))
        self._bind_prefab_autocomplete(select_prefab_entry, self.v_select_prefab)
        _btn(spf, "Browse Prefabs…", lambda: self._open_prefab_picker(self.v_select_prefab),
             font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(0,4))
        _btn(spf, "Select Nearest", self._on_select_prefab, "primary",
             font=("Segoe UI",8,"bold"), pady=4, padx=6).pack(side="left")

    def _populate_nearby(self, items):
        """Rebuild the checkbox list from items = [(id, name), ...]."""
        for widget in self._nearby_inner.winfo_children():
            widget.destroy()
        selection = self.models.selection
        selection.nearby = list(items)
        selection.checked.clear()
        self._nearby_vars = {}
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

            def _refresh_row_bg(row=row, var=var, eid=eid):
                """Colour the whole row amber when checked, normal when not."""
                checked = var.get()
                if checked:
                    selection.checked.add(eid)
                else:
                    selection.checked.discard(eid)
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
                self._read_selected()
            lbl.bind("<Button-1>", on_click)
            # Mousewheel on each row and its children
            mwh = getattr(self, "_nearby_mousewheel", None)
            if mwh:
                bind_wheel(row, mwh)
                bind_wheel(cb, mwh)
                bind_wheel(lbl, mwh)
            self._nearby_vars[eid] = var
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
        self._send_and_capture(f"select find {self._q_target(target)} {diameter}", on_result, quiet=0.6)

    def _on_group_save(self):
        name = self.v_group_name.get().strip()
        if not name:
            messagebox.showinfo("Enter a name", "Type a group name first.", parent=self)
            return
        selection = self.models.selection
        checked = [(eid, n) for eid, n in selection.nearby if eid in selection.checked]
        if not checked:
            messagebox.showinfo("Nothing checked",
                "Check at least one item in the Nearby list first.", parent=self)
            return
        selection.groups[name] = checked
        selection.group = name
        self._group_combo["values"] = ["(none)"] + list(selection.groups)
        self._group_combo_var.set(name)
        self.v_group_name.set("")
        self._append_log(f"[Group '{name}' saved: {len(checked)} item(s)]\n", "ok")

    def _on_group_select(self, event=None):
        selection = self.models.selection
        name = self._group_combo_var.get()
        selection.group = name if name in selection.groups else None
        if selection.group is None:
            return
        items = selection.groups[name]
        self._populate_nearby(items)
        self._append_log(f"[Group '{name}' loaded: {len(items)} item(s)]\n", "ok")

    def _on_group_delete(self):
        selection = self.models.selection
        name = self._group_combo_var.get()
        if name not in selection.groups:
            return
        del selection.groups[name]
        selection.group = None
        self._group_combo["values"] = ["(none)"] + list(selection.groups)
        self._group_combo_var.set("(none)")
        self._append_log(f"[Group '{name}' deleted]\n", "warn")

    def _on_destroy_selection(self):
        label = self._say_selected
        selection = self.models.selection
        ids = selection.active_ids() or ([selection.current[0]] if selection.current else [])
        if not ids:
            say(label, "Select something first.", RED)
            return
        if len(ids) > 1:
            what = f"these {len(ids)} objects"
        elif selection.current and selection.current[0] == ids[0]:
            what = f"{entity_name(selection.current[1])} ({ids[0]})"
        else:
            what = f"object {ids[0]}"
        if not confirm(self, "Destroy", f"Destroy {what}? This can't be undone."):
            return

        def done():
            selection.forget(ids)
            self._populate_nearby(selection.nearby)
            self._history_listbox.delete(0, "end")
            for eid, name in selection.history:
                self._history_listbox.insert("end", f"{str(eid):<10} {name}")
            self._read_selected()
        self._send_series([f"wacky destroy {eid}" for eid in ids], label, "Destroyed.", then=done)

    def _add_to_history(self, eid, name):
        entry = f"{str(eid):<10} {name}"
        history = self.models.selection.history
        for i, (e, n) in enumerate(history):
            if e == eid:
                history.pop(i)
                self._history_listbox.delete(i)
                break
        history.insert(0, (eid, name))
        self._history_listbox.insert(0, entry)
        if len(history) > 50:
            history.pop()
            self._history_listbox.delete("end")

    def _on_history_select(self, event=None):
        sel = self._history_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        history = self.models.selection.history
        if idx < len(history):
            eid, name = history[idx]
            self._uncheck_all_nearby()
            self._send(f"select {eid}")
            self._read_selected()

    def _on_history_clear(self):
        self.models.selection.history.clear()
        self._history_listbox.delete(0, "end")

    def _on_select_prefab(self):
        target = self._current_target()
        if not target:
            return
        prefab = self.v_select_prefab.get().strip()
        if not prefab:
            messagebox.showinfo("Pick a prefab", "Browse for a prefab first.", parent=self)
            return
        self._send(f"select prefab {prefab} {self._q_target(target)}")
        self._read_selected()

    def _on_get_string(self):
        def on_result(rs, rd):
            if rs:
                self._append_log(f"[Selection string]\n{rs}\n", "ok")
        self._send_and_capture("select tostring", on_result)

    def _on_look_at(self):
        target = self._current_target()
        if not target:
            return
        self._send(f"select look-at {self._q_target(target)}")
        self._read_selected()
