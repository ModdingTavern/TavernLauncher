"""The Server Settings tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import tkinter as tk
from tkinter import messagebox

from tavern_shared.theme import (
    BG, SURF, BORDER, AMBER, PARCH, _btn, _hint, _section_label, _mk_scrollbar,
)


class SettingsTabMixin:
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
