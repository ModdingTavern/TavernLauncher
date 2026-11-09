"""The Move & Rotate tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import struct
import tkinter as tk
from tkinter import messagebox

from tavern_shared.theme import BG, SURF, SURF2, BORDER, AMBER, PARCH, MUTED, _btn, _section_label


class MoveTabMixin:
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
            self._send(f"spawn string {self._q_target(target)} {self._q(rescaled)}")
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
                        self._send(f"spawn string {self._q_target(target)} {self._q(rescaled)}")
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
        for var in self._nearby_vars.values():
            var.set(False)
        self.models.selection.checked.clear()
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
        return self.models.selection.active_ids()

    def _send_to_selection(self, cmd):
        """Send a command, repeating it for each entity in the active group
        (selecting each in turn), or just once for single selection."""
        ids = self._active_entity_ids()
        if ids:
            def send_next(i=0):
                if i >= len(ids):
                    return
                stopped = f"[Stopped at {i+1} of {len(ids)}]\n"
                if not self._send(f"select {ids[i]}"):
                    return self._append_log(stopped, "err")
                def then():
                    if not self._send(cmd):
                        return self._append_log(stopped, "err")
                    self.after(80, lambda: send_next(i+1))
                self.after(80, then)
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
                spawn_string = self._clean_spawn_string(rs) if rs else None
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
            spawn_string = self._clean_spawn_string(rs) if rs else None
            if spawn_string:
                self._send(f"spawn string-raw {self._q(spawn_string)}")
            self.after(150, lambda: self._clone_entity_list(ids, i + 1))

        self.after(80, lambda: self._send_and_capture("select tostring", on_result))
