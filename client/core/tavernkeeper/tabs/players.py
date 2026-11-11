"""The Players tab: everything done to the target player picked in the sidebar.

Methods of TavernKeeperWindow, which inherits this mixin. Each section answers
on its own status line, in the server's words when something fails.
"""
import re
import tkinter as tk
from collections import Counter

from tavern_shared.theme import BG, SURF, SURF2, AMBER, PARCH, MUTED, RED, _section_label
from client.core.tavernkeeper.widgets import (
    confirm, entity_name, form_button, form_combo, form_entry, form_row, form_text, read_number, say, status_line,
)

# SpawnAreaIdentifier values that work on the stock map. The others throw or are dev-only.
PLACES = (
    "RespawnPoint", "Home", "OutsideCave", "OutsideForest", "OutsideTower", "TowerCP1", "TowerCP2",
    "TowerCP3", "TowerCP4", "TowerCP5", "TowerEnd", "OutsideLake", "MountainPass", "MountainPassEnd",
    "Glades", "BattleField", "HolidayZone", "WoodcuttingShrine", "ArcheryShrine", "MeleeShrine",
)
PATHS = ("Mining", "Forging", "Woodcutting", "Melee", "Ranged")
STAT_MODES = ("Base", "Min", "Max")


def _place_label(name):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def _number(value):
    return f"{round(value, 3):g}"


def _item_name(item):
    return entity_name(item.get("Name", "?"))


def _describe_inventory(row):
    def names(key):
        value = row.get(key)
        items = value if isinstance(value, list) else [value]
        return ", ".join(_item_name(i) if isinstance(i, dict) else "empty" for i in items)

    seen, counts = set(), Counter()
    for item in row.get("All") or []:
        if isinstance(item, dict) and item.get("Identifier") not in seen:
            seen.add(item.get("Identifier"))
            counts[_item_name(item)] += 1
    everything = ", ".join(f"{name} x{n}" if n > 1 else name for name, n in sorted(counts.items()))
    return (f"Left hand: {names('LeftHand')}\nRight hand: {names('RightHand')}\n"
            f"Belt: {names('Belt')}\nBack: {names('Back')}\n"
            f"Everything ({len(seen)}): {everything or 'empty'}")


class PlayersTabMixin:
    def _build_players_tab(self, parent):
        self._stat_rows = {}
        self._stat_base = None
        self._players_shown = None

        tk.Label(parent, text="Everything here acts on the player picked on the left.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(10, 2))

        _section_label(parent, "MODERATE")
        row = form_row(parent)
        form_text(row, "Reason:")
        self.v_kick_reason = tk.StringVar()
        form_entry(row, self.v_kick_reason, 20)
        form_button(row, "Kick", self._on_kick, "danger")
        form_button(row, "Kill", self._on_kill, "danger")
        form_button(row, "God Mode On", lambda: self._on_god_mode(True))
        form_button(row, "God Mode Off", lambda: self._on_god_mode(False))
        self._say_moderate = status_line(parent)

        _section_label(parent, "MESSAGE")
        row = form_row(parent)
        self.v_admin_message = tk.StringVar()
        form_entry(row, self.v_admin_message, 34)
        form_text(row, "Seconds:")
        self.v_admin_duration = tk.StringVar(value="5")
        form_entry(row, self.v_admin_duration, 5)
        form_button(row, "Send Message", self._on_message, "primary")
        form_button(row, "Send to All", lambda: self._on_message(everyone=True))
        self._say_message = status_line(parent)

        _section_label(parent, "TELEPORT")
        row = form_row(parent)
        form_text(row, "To a player:")
        self.v_teleport_target = tk.StringVar()
        self._teleport_combo = form_combo(row, self.v_teleport_target, editable=True,
                                      postcommand=self._fill_teleport_players)
        form_button(row, "Teleport to Player", self._on_teleport, "primary")
        row = form_row(parent)
        form_text(row, "To a place:")
        self.v_teleport_place = tk.StringVar(value=_place_label(PLACES[0]))
        form_combo(row, self.v_teleport_place, [_place_label(p) for p in PLACES])
        form_button(row, "Teleport to Place", self._on_teleport_place, "primary")
        self._say_teleport = status_line(parent)

        _section_label(parent, "HOME")
        row = form_row(parent)
        self._home_readout = tk.Label(row, text="", bg=BG, fg=PARCH, font=("Consolas", 10))
        self._home_readout.pack(side="left", padx=(0, 12))
        form_button(row, "Set Home Here", self._on_set_home_here, "primary")
        form_button(row, "Clear Home", self._on_clear_home)
        self._say_home = status_line(parent)

        _section_label(parent, "STATS")
        row = form_row(parent)
        self.v_stat = tk.StringVar()
        self._stat_combo = form_combo(row, self.v_stat, width=24)
        self._stat_combo.bind("<<ComboboxSelected>>", self._on_stat_picked)
        form_button(row, "Refresh Stats", self._on_refresh_stats)
        self._stat_readout = tk.Label(row, text="", bg=BG, fg=PARCH, font=("Consolas", 9))
        self._stat_readout.pack(side="left", padx=(6, 0))
        row = form_row(parent)
        form_text(row, "Set")
        self.v_stat_mode = tk.StringVar(value=STAT_MODES[0])
        mode = form_combo(row, self.v_stat_mode, STAT_MODES, width=6)
        mode.bind("<<ComboboxSelected>>", lambda e: self._show_stat(prefill=True))
        form_text(row, "to")
        self.v_stat_value = tk.StringVar()
        form_entry(row, self.v_stat_value, 8)
        form_button(row, "Set Stat", self._on_set_stat, "primary")
        row = form_row(parent)
        form_text(row, "Buff by")
        self.v_buff_value = tk.StringVar(value="1")
        form_entry(row, self.v_buff_value, 6)
        form_text(row, "for")
        self.v_buff_seconds = tk.StringVar(value="30")
        form_entry(row, self.v_buff_seconds, 6)
        form_text(row, "seconds")
        self.v_buff_multiply = tk.BooleanVar(value=False)
        tk.Checkbutton(row, text="Multiply", variable=self.v_buff_multiply, bg=BG, fg=PARCH,
                       selectcolor=SURF, activebackground=BG, activeforeground=PARCH,
                       font=("Segoe UI", 9), bd=0).pack(side="left", padx=(0, 8))
        form_button(row, "Apply Buff", self._on_buff, "primary")
        self._say_stats = status_line(parent)

        _section_label(parent, "PROGRESSION")
        row = form_row(parent)
        self.v_path = tk.StringVar(value=PATHS[0])
        form_combo(row, self.v_path, PATHS, width=14)
        form_text(row, "XP:")
        self.v_path_xp = tk.StringVar(value="100")
        form_entry(row, self.v_path_xp, 8)
        form_button(row, "Give XP", self._on_give_xp, "primary")
        form_button(row, "Level Up", self._on_level_up)
        self._say_progress = status_line(parent)

        _section_label(parent, "INVENTORY")
        row = form_row(parent)
        form_button(row, "Show Inventory", self._on_show_inventory)
        self._say_inventory = status_line(parent)
        frame = tk.Frame(parent, bg=SURF)
        frame.pack(fill="x", padx=20, pady=(0, 4))
        self._inventory_text = tk.Text(frame, bg=SURF2, fg=PARCH, font=("Consolas", 9), height=6, width=40,
                                       wrap="word", relief="flat", bd=6, state="disabled")
        self._inventory_text.pack(fill="x")

        _section_label(parent, "ATM")
        row = form_row(parent)
        self._atm_readout = tk.Label(row, text="", bg=BG, fg=PARCH, font=("Consolas", 10))
        self._atm_readout.pack(side="left", padx=(0, 12))
        form_button(row, "Get Balance", lambda: self._on_atm("get"))
        form_text(row, "Amount:")
        self.v_atm_amount = tk.StringVar(value="0")
        form_entry(row, self.v_atm_amount, 8)
        form_button(row, "Set Balance", lambda: self._on_atm("set"), "primary")
        form_button(row, "Add to Balance", lambda: self._on_atm("add"), "primary")
        self._say_atm = status_line(parent)

        self.api.on_target_changed(self._players_refresh)
        self.api.on_connected(self._players_refresh)
        self._nb.bind("<<NotebookTabChanged>>", self._players_refresh, add="+")

    def _target_name(self):
        return self.v_target.get().strip()

    # Reading the target

    def _players_refresh(self, *_):
        """Reads the target's stats and home whenever this tab is open. A typed
        name that isn't online has nothing to read."""
        if not self._connected or self._nb.select() != str(self._tab_frames["admin"]):
            return
        target = self.api.target
        changed = target != self._players_shown
        self._players_shown = target
        if changed:
            self._clear_player_readouts()
        if target is not None and target.id is not None:
            self._read_home(target.name)
            self._read_stats(target.name, prefill=changed)

    def _clear_player_readouts(self):
        self._stat_rows = {}
        self._stat_base = None
        self._stat_combo["values"] = ()
        self.v_stat.set("")
        self.v_stat_value.set("")
        self._stat_readout.config(text="")
        self._home_readout.config(text="")
        self._atm_readout.config(text="")
        self._write_inventory("")
        for label in (self._say_moderate, self._say_message, self._say_teleport, self._say_home,
                      self._say_stats, self._say_progress, self._say_inventory, self._say_atm):
            say(label, "")

    def _read_home(self, target):
        def got(result):
            if self._target_name() != target:
                return
            home = result.value if result.ok and isinstance(result.value, list) else None
            if home is None:
                self._home_readout.config(text="")
            elif not any(home):
                self._home_readout.config(text="No home set")
            else:
                self._home_readout.config(text=", ".join(_number(v) for v in home))
        self._run_command(f"player get-home {self._q_target(target)}", got, quiet=True)

    def _read_stats(self, target, prefill, label=None):
        def got(result):
            if self._target_name() != target:
                return
            if not result.ok or not isinstance(result.value, list):
                if label is not None:
                    self._answer_on(label, "")(result)
                return
            self._stat_rows = {r["Name"]: r for r in result.value if isinstance(r, dict) and r.get("Name")}
            self._stat_combo["values"] = list(self._stat_rows)
            if self.v_stat.get() not in self._stat_rows and self._stat_rows:
                self.v_stat.set(next(iter(self._stat_rows)))
            self._read_stat(target, prefill)
        self._run_command(f"player list-stats {self._q_target(target)}", got, quiet=label is None, output=False)

    def _read_stat(self, target, prefill):
        stat = self.v_stat.get()
        if not stat:
            return

        def got(result):
            if self._target_name() != target or self.v_stat.get() != stat:
                return
            value = result.value if result.ok and isinstance(result.value, dict) else {}
            self._stat_base = value.get("Base")
            if value.get("Value") is not None and stat in self._stat_rows:
                self._stat_rows[stat]["Value"] = value["Value"]
            self._show_stat(prefill)
        self._run_command(f"player check-stat {self._q_target(target)} {stat}", got, quiet=True)

    def _on_stat_picked(self, event=None):
        target = self._target_name()
        if target:
            self._read_stat(target, prefill=True)

    def _show_stat(self, prefill):
        row = self._stat_rows.get(self.v_stat.get())
        if row is None:
            self._stat_readout.config(text="")
            return
        base = self._stat_base
        parts = [f"Value {_number(row['Value'])}"]
        if base is not None:
            parts.append(f"Base {_number(base)}")
        parts += [f"Min {_number(row['Min'])}", f"Max {_number(row['Max'])}"]
        self._stat_readout.config(text="   ".join(parts))
        if prefill:
            current = {"Base": base, "Min": row["Min"], "Max": row["Max"]}[self.v_stat_mode.get()]
            self.v_stat_value.set("" if current is None else _number(current))

    def _write_inventory(self, text):
        self._inventory_text.config(state="normal")
        self._inventory_text.delete("1.0", "end")
        self._inventory_text.insert("1.0", text)
        self._inventory_text.config(state="disabled")

    # Moderate

    def _on_kick(self):
        target = self._current_target()
        if not target or not confirm(self, "Kick player", f"Kick {target} from the server?"):
            return
        reason = self.v_kick_reason.get().strip()
        cmd = f"player kick {self._q_target(target)}"
        if reason:
            cmd += f" {self._q_text(reason)}"
        self._send_and_say(cmd, self._say_moderate, f"Kicked {target}.",
                     then=lambda: self.after(800, lambda: self._refresh_players(quiet=True)), target=target)

    def _on_kill(self):
        target = self._current_target()
        if not target or not confirm(self, "Kill player", f"Kill {target}?"):
            return
        self._send_and_say(f"player kill {self._q_target(target)}", self._say_moderate, f"Killed {target}.", target=target)

    def _on_god_mode(self, on):
        target = self._current_target()
        if not target:
            return
        self._send_and_say(f"player god-mode {self._q_target(target)} {'true' if on else 'false'}", self._say_moderate,
                     f"God mode {'on' if on else 'off'} for {target}. The server can't report this back.",
                     target=target)

    # Message

    def _on_message(self, everyone=False):
        label = self._say_message
        text = self.v_admin_message.get().strip()
        if not text:
            say(label, "Type a message first.", RED)
            return
        duration = read_number(self.v_admin_duration, label, "the seconds")
        if duration is None:
            return
        if everyone:
            self._send_and_say(f"player message * {self._q_text(text)} {duration}", label, "Sent to everyone.")
            return
        target = self._current_target()
        if target:
            self._send_and_say(f"player message {self._q_target(target)} {self._q_text(text)} {duration}", label,
                         f"Sent to {target}.", target=target)

    # Teleport

    def _fill_teleport_players(self):
        self._teleport_combo["values"] = [p.name for p in self.models.roster.players]

    def _on_teleport(self):
        label = self._say_teleport
        target = self._current_target()
        if not target:
            return
        dest = self.v_teleport_target.get().strip()
        if not dest:
            say(label, "Pick a player to teleport to.", RED)
            return
        self._send_and_say(f"player teleport {self._q_target(target)} {self._q_target(dest)}", label,
                     f"Teleported {target} to {dest}.", target=target)

    def _on_teleport_place(self):
        target = self._current_target()
        if not target:
            return
        place = self.v_teleport_place.get()
        self._send_and_say(f"player teleport {self._q_target(target)} {place.replace(' ', '')}", self._say_teleport,
                     f"Teleported {target} to {place}.", target=target)

    # Home

    def _on_set_home_here(self):
        label = self._say_home
        target = self._current_target()
        if not target:
            return
        q = self._q_target(target)

        def got(result):
            position = result.value.get("Position") if result.ok and isinstance(result.value, dict) else None
            if position is None:
                self._answer_on(label, "Couldn't read where they are.", color=RED)(result)
                return
            spot = ",".join(f"{v:.3f}" for v in position)
            self._send_and_say(f"player set-home {q} {spot}", label, "Home set to where they are now.",
                         then=lambda: self._read_home(target))
        say(label, "Sending...")
        self._run_command(f"player detailed {q}", got, output=False)

    def _on_clear_home(self):
        target = self._current_target()
        if target:
            self._send_and_say(f"player set-home {self._q_target(target)}", self._say_home, "Home cleared.",
                         then=lambda: self._read_home(target), target=target)

    # Stats

    def _on_refresh_stats(self):
        target = self._current_target()
        if target:
            self._read_stats(target, prefill=True, label=self._say_stats)

    def _on_set_stat(self):
        label = self._say_stats
        target = self._current_target()
        if not target:
            return
        stat, mode = self.v_stat.get(), self.v_stat_mode.get()
        if not stat:
            say(label, "Pick a stat first.", RED)
            return
        value = read_number(self.v_stat_value, label, "the new value")
        if value is None:
            return
        self._send_and_say(f"player set-stat {self._q_target(target)} {stat} {value} {mode}", label,
                     f"{stat} {mode} set to {_number(value)}.",
                     then=lambda: self._read_stats(target, prefill=False), target=target)

    def _on_buff(self):
        label = self._say_stats
        target = self._current_target()
        if not target:
            return
        stat = self.v_stat.get()
        if not stat:
            say(label, "Pick a stat first.", RED)
            return
        value = read_number(self.v_buff_value, label, "the buff")
        seconds = None if value is None else read_number(self.v_buff_seconds, label, "the seconds")
        if seconds is None:
            return
        multiply = "true" if self.v_buff_multiply.get() else "false"
        self._send_and_say(f"player modify-stat {self._q_target(target)} {stat} {value} {seconds} {multiply}", label,
                     f"Buffed {stat} for {_number(seconds)} seconds.",
                     then=lambda: self._read_stats(target, prefill=False), target=target)

    # Progression. The server only prints XP totals in its own process, so there is no check here.

    def _on_give_xp(self):
        label = self._say_progress
        target = self._current_target()
        if not target:
            return
        xp = read_number(self.v_path_xp, label, "the XP", int)
        if xp is None:
            return
        path = self.v_path.get()
        self._send_and_say(f"player progression pathxp {self._q_target(target)} {path} {xp}", label,
                     f"Gave {target} {xp} {path} XP.", target=target)

    def _on_level_up(self):
        target = self._current_target()
        if target:
            path = self.v_path.get()
            self._send_and_say(f"player progression pathlevelup {self._q_target(target)} {path}", self._say_progress,
                         f"Levelled {target} up in {path}.", target=target)

    # Inventory

    def _on_show_inventory(self):
        label = self._say_inventory
        target = self._current_target()
        if not target:
            return

        def got(result):
            if result.ok and isinstance(result.value, list) and result.value:
                self._write_inventory(_describe_inventory(result.value[0]))
                say(label, "")
            else:
                self._write_inventory("")
                self._answer_on(label, "Nothing to show.", color=AMBER)(result)
        say(label, "Sending...")
        self._run_command(f"player inventory {self._q_target(target)}", got, output=False)

    # ATM

    def _on_atm(self, verb):
        label = self._say_atm
        target = self._current_target()
        if not target:
            return
        q = self._q_target(target)
        if verb == "get":
            def got(result):
                if result.ok:
                    balance = result.value if result.value not in (None, "") else result.text
                    self._atm_readout.config(text=f"Balance: {balance}")
                    say(label, "")
                else:
                    self._atm_readout.config(text="")
                    self._answer_on(label, "")(result)
            say(label, "Sending...")
            self._run_command(f"trade atm get {q}", got, output=False)
            return
        amount = read_number(self.v_atm_amount, label, "the amount", int)
        if amount is not None:
            self._send_and_say(f"trade atm {verb} {q} {amount}", label, "Done.", then=lambda: self._on_atm("get"))
