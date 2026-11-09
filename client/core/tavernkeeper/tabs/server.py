"""The Server tab: status, shutting down, wipes and every server setting.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import re
import tkinter as tk

from tavern_shared.theme import AMBER, BG, MUTED, PARCH, RED, _section_label
from client.core.tavernkeeper.widgets import (
    confirm, form_button, form_combo, form_entry, form_row, form_text, read_number, say, status_line,
)

WIPE_WORD = "WIPE"
QUIT_WARNINGS = (60, 30, 10, 5)
RISKY_SETTINGS = {
    "WipesWhenEmpty": ("true", "The world will be wiped whenever the server empties."),
    "IsSaving": ("false", "The server will stop saving the world."),
    "IsAutoSaving": ("false", "The server will stop saving by itself."),
}


def _setting_label(name):
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name)


def _setting_text(value):
    return ("true" if value else "false") if isinstance(value, bool) else str(value)


class ServerTabMixin:
    def _build_server_tab(self, parent):
        self._setting_rows = {}
        self._quit_after = None
        self._quit_left = 0

        _section_label(parent, "STATUS")
        row = form_row(parent)
        self._status_readout = tk.Label(row, text="", bg=BG, fg=PARCH, font=("Consolas", 10))
        self._status_readout.pack(side="left", padx=(0, 12))
        form_button(row, "Refresh Status", self._read_server_status)

        _section_label(parent, "SHUT DOWN")
        row = form_row(parent)
        form_text(row, "Warn players for")
        self.v_quit_seconds = tk.StringVar(value="30")
        form_entry(row, self.v_quit_seconds, 5)
        form_text(row, "seconds")
        self._quit_btn = form_button(row, "Quit Server", self._on_quit, "danger")
        self._cancel_quit_btn = form_button(row, "Cancel Shutdown", self._on_cancel_quit)
        self._cancel_quit_btn.config(state="disabled")
        self._say_quit = status_line(parent)

        _section_label(parent, "DANGER ZONE")
        row = form_row(parent)
        form_text(row, f"Type {WIPE_WORD} to unlock these:")
        self.v_wipe_word = tk.StringVar()
        self.v_wipe_word.trace_add("write", self._on_wipe_word)
        form_entry(row, self.v_wipe_word, 8)
        row = form_row(parent)
        self._wipe_caves_btn = form_button(row, "Wipe Caves", self._on_wipe_caves, "danger")
        form_text(row, "Clears every cave and moves anyone inside to the surface.")
        row = form_row(parent)
        form_text(row, "Chunk:")
        self.v_wipe_chunk = tk.StringVar()
        form_entry(row, self.v_wipe_chunk, 10)
        form_button(row, "Use Target's Chunk", self._on_target_chunk)
        self._wipe_chunk_btn = form_button(row, "Wipe Chunk", self._on_wipe_chunk, "danger")
        self._on_wipe_word()
        self._say_danger = status_line(parent)

        _section_label(parent, "SETTINGS")
        row = form_row(parent)
        form_text(row, "Find:")
        self.v_setting_filter = tk.StringVar()
        self.v_setting_filter.trace_add("write", self._apply_setting_filter)
        form_entry(row, self.v_setting_filter, 20)
        form_button(row, "Refresh Settings", lambda: self._read_settings(force=True))
        tk.Label(parent, text="Changes apply at once and survive a restart.", bg=BG, fg=MUTED,
                 font=("Segoe UI", 8)).pack(anchor="w", padx=22, pady=(0, 2))
        self._say_settings = status_line(parent)
        self._settings_frame = tk.Frame(parent, bg=BG)
        self._settings_frame.pack(fill="x")

        self.api.on_connected(self._server_refresh)
        self._nb.bind("<<NotebookTabChanged>>", self._server_refresh, add="+")

    def _server_refresh(self, *_):
        """Reads the status and settings whenever this tab opens."""
        if self._connected and self._nb.select() == str(self._tab_frames["settings"]):
            self._read_server_status()
            self._read_settings()

    # Status

    def _read_server_status(self):
        def got(result):
            value = result.value if result.ok and isinstance(result.value, dict) else None
            if value is None:
                self._status_readout.config(text="")
                return
            self._status_readout.config(text=f"FPS {round(value.get('fps', 0))}   Players {value.get('players', '?')}   "
                                             f"Chunks loaded: world {value.get('overworldLoaded', '?')}, caves {value.get('cavesLoaded', '?')}")
        self._run_command("debug server-stats", got, quiet=True)

    # Settings

    def _read_settings(self, force=False):
        """Shows the server's values. Only force overwrites a value typed but not set yet."""
        def got(result):
            if result.ok and isinstance(result.value, dict):
                self._show_settings(result.value, force)
            elif result.error or result.timed_out:
                self._answer_on(self._say_settings, "")(result)
        self._run_command("settings list server", got, quiet=True)

    def _show_settings(self, values, force=False):
        self.models.settings = values
        if list(values) != list(self._setting_rows):
            self._build_setting_rows(values)
        for name, value in values.items():
            text = _setting_text(value)
            row = self._setting_rows[name]
            if force or row["shown"] != text:
                row["shown"] = text
                row["var"].set(text)

    def _build_setting_rows(self, values):
        for child in self._settings_frame.winfo_children():
            child.destroy()
        self._setting_rows = {}
        for name, value in values.items():
            row = tk.Frame(self._settings_frame, bg=BG)
            tk.Label(row, text=_setting_label(name), bg=BG, fg=PARCH, font=("Segoe UI", 9), width=34, anchor="w").pack(side="left")
            var = tk.StringVar()
            if isinstance(value, bool):
                form_combo(row, var, ("true", "false"), width=8)
            else:
                form_entry(row, var, 16)
            button = form_button(row, "Set", lambda n=name: self._on_set_setting(n))
            self._setting_rows[name] = {"frame": row, "var": var, "shown": None, "button": button}
        self._apply_setting_filter()

    def _apply_setting_filter(self, *_):
        text = self.v_setting_filter.get().strip().lower().replace(" ", "")
        for name, row in self._setting_rows.items():
            row["frame"].pack_forget()
            if text in name.lower():
                row["frame"].pack(fill="x", padx=20, pady=2)

    def _on_set_setting(self, name):
        label = self._say_settings
        value = self._setting_rows[name]["var"].get().strip()
        if not value:
            say(label, f"Type a value for {_setting_label(name)}.", RED)
            return
        risky = RISKY_SETTINGS.get(name)
        if risky and value.lower() == risky[0] and not confirm(self, "Change setting", f"{risky[1]} Change it?"):
            return
        argument = self._q_text(value) if " " in value else value
        self._send_and_say(f"settings changesetting server {name} {argument}", label,
                           f"{_setting_label(name)} set to {value}.", then=self._read_settings)

    # Shut down

    def _on_quit(self):
        label = self._say_quit
        seconds = read_number(self.v_quit_seconds, label, "the seconds", int)
        if seconds is None:
            return
        seconds = max(0, seconds)
        if not confirm(self, "Quit server", f"Shut the server down in {seconds} seconds? Everyone will be disconnected."):
            return
        self._quit_left = seconds
        self._quit_btn.config(state="disabled")
        self._cancel_quit_btn.config(state="normal")
        if seconds:
            self._warn_players(f"Server shutting down in {seconds} seconds")
        self._quit_tick()

    def _warn_players(self, text):
        self._send(f"player message * {self._q_text(text)} 5")

    def _quit_tick(self):
        self._quit_after = None
        if not self._connected:
            self._reset_quit()
            say(self._say_quit, "Stopped: the connection dropped.", RED)
            return
        if self._quit_left <= 0:
            self._reset_quit()
            self._send_and_say("save now", self._say_quit, "Saved. Quitting...", then=lambda: self._send("quit"))
            return
        say(self._say_quit, f"Shutting down in {self._quit_left} seconds...", AMBER)
        if self._quit_left in QUIT_WARNINGS:
            self._warn_players(f"Server shutting down in {self._quit_left} seconds")
        self._quit_left -= 1
        self._quit_after = self.after(1000, self._quit_tick)

    def _reset_quit(self):
        if self._quit_after is not None:
            self.after_cancel(self._quit_after)
            self._quit_after = None
        self._quit_btn.config(state="normal")
        self._cancel_quit_btn.config(state="disabled")

    def _on_cancel_quit(self):
        self._reset_quit()
        self._warn_players("Server shutdown cancelled")
        say(self._say_quit, "Shutdown cancelled.")

    # Danger zone

    def _on_wipe_word(self, *_):
        state = "normal" if self.v_wipe_word.get() == WIPE_WORD else "disabled"
        self._wipe_caves_btn.config(state=state)
        self._wipe_chunk_btn.config(state=state)

    def _on_wipe_caves(self):
        self.v_wipe_word.set("")
        self._send_and_say("save wipecaves", self._say_danger, "Caves wiped.")

    def _on_target_chunk(self):
        chunk = self.models.roster.chunks.get(self.v_target.get().strip())
        found = re.search(r"\d+-\d+", chunk or "")
        if found:
            self.v_wipe_chunk.set(found.group())
        else:
            say(self._say_danger, "The target player's chunk isn't known.", RED)

    def _on_wipe_chunk(self):
        chunk = self.v_wipe_chunk.get().strip()
        if not re.fullmatch(r"\d+-\d+", chunk):
            say(self._say_danger, "Enter a chunk like 21-35.", RED)
            return
        self.v_wipe_word.set("")
        self._send_and_say(f"chunks wipe {chunk}", self._say_danger, None)
