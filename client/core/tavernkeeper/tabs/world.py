"""The World tab: time, festivities, caves and saving.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import re
import tkinter as tk

from tavern_shared.theme import BG, MUTED, RED, _section_label
from client.core.tavernkeeper.widgets import (
    form_button, form_combo, form_entry, form_row, form_text, say, status_line,
)

CLOCK = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")
# Layer 0 moves nobody and layers past 3 can hang the command with no answer.
CAVE_LAYERS = ("1", "2", "3")


class WorldTabMixin:
    def _build_world_tab(self, parent):
        self._festivities = {}
        self._world_loaded = False

        tk.Label(parent, text="The server can't report the time or which festivity is running, so these only set.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=20, pady=(10, 2))

        _section_label(parent, "TIME")
        row = form_row(parent)
        self.v_time_keyword = tk.StringVar()
        self._time_combo = form_combo(row, self.v_time_keyword, width=12)
        form_button(row, "Set Time", self._on_time_keyword, "primary")
        form_button(row, "Toggle Day/Night", self._on_time_toggle)
        row = form_row(parent)
        form_text(row, "Or a clock time (24 hour):")
        self.v_time_value = tk.StringVar(value="12:00")
        form_entry(row, self.v_time_value, 8)
        form_button(row, "Set Clock", self._on_time_clock, "primary")
        self._say_time = status_line(parent)

        _section_label(parent, "FESTIVITIES")
        row = form_row(parent)
        self.v_festivity = tk.StringVar()
        self._festivity_combo = form_combo(row, self.v_festivity, width=24)
        form_button(row, "Start Festivity", lambda: self._on_festivity("start"), "primary")
        form_button(row, "Stop Festivity", lambda: self._on_festivity("stop"))
        self._say_festivity = status_line(parent)

        _section_label(parent, "CAVES")
        row = form_row(parent)
        form_text(row, "Send the target player to layer:")
        self.v_cave_layer = tk.StringVar(value=CAVE_LAYERS[0])
        form_combo(row, self.v_cave_layer, CAVE_LAYERS, width=4)
        form_button(row, "Teleport to Layer", self._on_cave_teleport, "primary")
        self._say_caves = status_line(parent)

        _section_label(parent, "SAVE")
        row = form_row(parent)
        form_button(row, "Save Now", self._on_save_now, "primary")
        form_button(row, "Save Backup", self._on_save_backup)
        self._say_save = status_line(parent)

        self.api.on_connected(self._world_reload)
        self._nb.bind("<<NotebookTabChanged>>", self._world_refresh, add="+")

    def _world_reload(self):
        self._world_loaded = False
        self._world_refresh()

    def _world_refresh(self, *_):
        """Fetches the server's own lists the first time this tab opens."""
        if self._world_loaded or not self._connected or self._nb.select() != str(self._tab_frames["world"]):
            return
        self._world_loaded = True

        def got_keywords(result):
            names = [k["Name"] for k in result.value if isinstance(k, dict)] if isinstance(result.value, list) else []
            self._time_combo["values"] = names
            if names and self.v_time_keyword.get() not in names:
                self.v_time_keyword.set(names[0])

        def got_festivities(result):
            rows = result.value if isinstance(result.value, list) else []
            self._festivities = {r["Name"]: r["Hash"] for r in rows if isinstance(r, dict)}
            self._festivity_combo["values"] = list(self._festivities)
            if self._festivities and self.v_festivity.get() not in self._festivities:
                self.v_festivity.set(next(iter(self._festivities)))

        self._run_command("time keywords", got_keywords, quiet=True)
        self._run_command("festivities list", got_festivities, quiet=True)

    # Time

    def _on_time_keyword(self):
        keyword = self.v_time_keyword.get()
        if not keyword:
            say(self._say_time, "Pick a time first.", RED)
            return
        self._send_and_say(f"time set {keyword}", self._say_time, f"Time set to {keyword}.")

    def _on_time_clock(self):
        match = CLOCK.match(self.v_time_value.get().strip())
        if not match:
            say(self._say_time, "Enter a time like 14:30.", RED)
            return
        hours, minutes = match.groups()
        self._send_and_say(f"time set {int(hours)}.{minutes}", self._say_time, f"Time set to {int(hours)}:{minutes}.")

    def _on_time_toggle(self):
        self._send_and_say("time toggle", self._say_time, "Switched between day and night.")

    # Festivities

    def _on_festivity(self, verb):
        name = self.v_festivity.get()
        if name not in self._festivities:
            say(self._say_festivity, "Pick a festivity first.", RED)
            return
        self._send_and_say(f"festivities {verb} {self._festivities[name]}", self._say_festivity, None)

    # Caves

    def _on_cave_teleport(self):
        target = self._current_target()
        if target:
            layer = self.v_cave_layer.get()
            self._send_and_say(f"world caves teleport {self._q_target(target)} {layer}", self._say_caves,
                               f"Sent {target} to layer {layer}. The server can't confirm a move, "
                               "and a layer that isn't generated yet moves nobody.", target=target)

    # Save

    def _on_save_now(self):
        self._send_and_say("save now", self._say_save, "Saved.")

    def _on_save_backup(self):
        self._send_and_say("save backup", self._say_save, "Backup made.")
