"""The Player Admin tab.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import tkinter as tk
from tkinter import messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, PARCH, MUTED, _btn, _field, _hint, _section_label,
)
from client.core.tavernkeeper.widgets import confirm


class AdminTabMixin:
    # ── Player Admin tab ─────────────────────────────────────────────────────

    def _build_admin_tab(self, parent):
        inner = parent

        tk.Label(inner, text="Acts on the target player selected above.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=680, justify="left"
        ).pack(anchor="w", padx=8, pady=(10,10))

        row = tk.Frame(inner, bg=BG)
        row.pack(fill="x", padx=8, pady=(0,10))
        _btn(row, "Kick", self._on_kick, "danger",
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
        if not target or not confirm(self, "Kick player", f"Kick {target} from the server?"):
            return
        self._send(f"player kick {self._q_target(target)}")

    def _on_kill(self):
        target = self._current_target()
        if not target or not confirm(self, "Kill player", f"Kill {target}?"):
            return
        self._send(f"player kill {self._q_target(target)}")

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
        self._send(f"player message {self._q_target(target)} {self._q(msg)} {duration}")

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
        self._send(f"player teleport {self._q_target(target)} {self._q(dest)}")

    def _on_quick_teleport(self, spawn_area_identifier):
        target = self._current_target()
        if not target:
            return
        self._send(f"player teleport {self._q_target(target)} {spawn_area_identifier}")

    def _on_set_home(self):
        target = self._current_target()
        if not target:
            return
        home = self.v_sethome_value.get().strip() or "reset"
        self._send(f"player set-home {self._q_target(target)} {self._q(home)}")

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

        self._send(f"player set-stat {self._q_target(target)} {stat_name} {value}")
        self._send_and_capture(f"player list-stats {self._q_target(target)}", on_refresh)

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
        self._send_and_capture(f"player list-stats {self._q_target(target)}", on_result)
