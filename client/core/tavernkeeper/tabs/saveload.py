"""The Save & Load tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import json
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

from tavern_shared.theme import (
    BG, SURF, BORDER, AMBERDIM, PARCH, MUTED, _btn, _section_label, _mk_scrollbar,
)
from client.core.tavernkeeper.widgets import confirm


class SaveLoadTabMixin:
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
                spawn_string = self._clean_spawn_string(rs) if rs else None
                if not spawn_string:
                    messagebox.showinfo("Nothing to add",
                        "Select something in Find & Select first.", parent=self)
                    return
                label = f"Item {len(self.models.staged)+1}"
                self.models.staged.append((label, spawn_string))
                self._save_listbox.insert("end", label)
            self._send_and_capture("select tostring", on_result)

    def _add_group_to_save_list(self, ids, i):
        """Recursively select each group entity, capture its tostring, add to list."""
        if i >= len(ids):
            return
        eid = ids[i]
        self._send(f"select {eid}")
        def on_result(rs, rd):
            spawn_string = self._clean_spawn_string(rs) if rs else None
            if spawn_string:
                label = f"Item {len(self.models.staged)+1}"
                self.models.staged.append((label, spawn_string))
                self._save_listbox.insert("end", label)
            # Move to next entity after a short delay
            self.after(150, lambda: self._add_group_to_save_list(ids, i + 1))
        self.after(80, lambda: self._send_and_capture("select tostring", on_result))

    def _on_rename_save_item(self, event=None):
        sel = self._save_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        old_label, spawn_string = self.models.staged[idx]
        new_label = simpledialog.askstring(
            "Rename item", "Enter a new name:",
            initialvalue=old_label, parent=self)
        if new_label and new_label.strip():
            new_label = new_label.strip()
            self.models.staged[idx] = (new_label, spawn_string)
            self._save_listbox.delete(idx)
            self._save_listbox.insert(idx, new_label)
            self._save_listbox.selection_set(idx)

    def _on_remove_from_save_list(self):
        sel = self._save_listbox.curselection()
        if not sel:
            return
        idx = sel[0]
        if not confirm(self, "Remove item", f"Remove {self.models.staged[idx][0]} from the list?"):
            return
        del self.models.staged[idx]
        self._save_listbox.delete(idx)

    def _on_save_to_file(self):
        if not self.models.staged:
            messagebox.showinfo("Nothing staged",
                "Add at least one item to the list first.", parent=self)
            return
        path = filedialog.asksaveasfilename(
            title="Save prefab collection", defaultextension=".json",
            filetypes=[("JSON files","*.json"),("All files","*.*")], parent=self)
        if not path:
            return
        try:
            data = [{"label": label, "string": s} for label, s in self.models.staged]
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
            self.models.staged = [(d.get("label","Item"), d["string"]) for d in data if "string" in d]
            self._save_listbox.delete(0, "end")
            for label, _ in self.models.staged:
                self._save_listbox.insert("end", label)
        except Exception as e:
            messagebox.showerror("Couldn't load", str(e), parent=self)

    def _on_spawn_all_saved(self):
        if not self.models.staged:
            messagebox.showinfo("Nothing staged",
                "Add or load some items first.", parent=self)
            return
        def spawn_next(i=0):
            if i >= len(self.models.staged):
                return
            label, s = self.models.staged[i]
            if not self._send(f"spawn string-raw {self._q(s)}"):
                self._append_log(f"[Spawn All stopped at {i+1} of {len(self.models.staged)}: {label}]\n", "err")
                return
            self.after(200, lambda: spawn_next(i+1))
        spawn_next()
