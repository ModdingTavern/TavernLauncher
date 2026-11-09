"""The player sidebar: who is online, and which of them commands aim at.

The list comes from player list-detailed, every ROSTER_REFRESH_MS and on demand.
The selected row is the target, and commands name it by id, so a quote or
space in a player's name cannot break them.
"""
import tkinter as tk

from tavern_shared.theme import BG, SURF, BORDER, AMBERDIM, PARCH, MUTED, _btn, _mk_scrollbar

ROSTER_REFRESH_MS = 10000


class RosterMixin:
    def _build_player_sidebar(self, parent):
        self._roster_busy = False
        side = tk.Frame(parent, bg=BG, width=190)
        side.pack_propagate(False)

        head = tk.Frame(side, bg=BG)
        head.pack(fill="x", pady=(2, 4))
        self._roster_title = tk.StringVar(value="PLAYERS")
        tk.Label(head, textvariable=self._roster_title, bg=BG, fg=MUTED,
                 font=("Georgia", 8, "bold")).pack(side="left")
        self._roster_btn = _btn(head, "⟳", self._refresh_players, font=("Segoe UI", 8), pady=1, padx=6)
        self._roster_btn.pack(side="right")

        self._roster_detail = tk.StringVar()
        tk.Label(side, textvariable=self._roster_detail, bg=BG, fg=MUTED, font=("Consolas", 8),
                 justify="left", anchor="w", wraplength=180).pack(side="bottom", fill="x", pady=(4, 0))

        frame = tk.Frame(side, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill="both", expand=True)
        self._roster_list = tk.Listbox(frame, bg=SURF, fg=PARCH, selectbackground=AMBERDIM,
                                       selectforeground="#ffd080", relief="flat", bd=0,
                                       highlightthickness=0, font=("Consolas", 10),
                                       activestyle="none", exportselection=False)
        sb = _mk_scrollbar(frame, self._roster_list.yview)
        sb.pack(side="right", fill="y")
        self._roster_list.config(yscrollcommand=sb.set)
        self._roster_list.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        self._roster_list.bind("<<ListboxSelect>>", self._on_roster_select)

        self._roster_after = self.after(ROSTER_REFRESH_MS, self._roster_tick)
        return side

    def _roster_tick(self):
        if self._connected and not self._roster_busy:
            self._refresh_players(quiet=True)
        self._roster_after = self.after(ROSTER_REFRESH_MS, self._roster_tick)

    def _refresh_players(self, quiet=False):
        self._roster_busy = True
        self._run_command("player list-detailed", lambda r: self._on_roster(r, quiet),
                          quiet=quiet, output=False)

    def _on_roster(self, result, quiet):
        self._roster_busy = False
        if not result.ok or not isinstance(result.value, list):
            return
        roster = self.models.roster
        roster.update(result.value)
        self._roster_title.set(f"PLAYERS ({len(roster.players)})")
        names = [p.name for p in roster.players]
        self._target_combo["values"] = names
        if names != list(self._roster_list.get(0, "end")):
            self._roster_list.delete(0, "end")
            self._roster_list.insert("end", *names)
        if names and not self.v_target.get().strip():
            self.v_target.set(names[0])
        self._sync_roster_selection()
        if not quiet:
            self._append_log(f"[{len(names)} online]\n", "ok")

    def _on_roster_select(self, event=None):
        sel = self._roster_list.curselection()
        if sel:
            self.v_target.set(self._roster_list.get(sel[0]))

    def _sync_roster_selection(self):
        name = self.v_target.get().strip()
        names = list(self._roster_list.get(0, "end"))
        self._roster_list.selection_clear(0, "end")
        if name in names:
            self._roster_list.selection_set(names.index(name))
            self._roster_list.see(names.index(name))
        self._roster_detail.set(self._describe_target(name))

    def _describe_target(self, name):
        if not name:
            return ""
        player = self.models.roster.find(name)
        if player is None:
            return "Not online"
        pos = self.models.roster.positions.get(name)
        where = ", ".join(str(round(v)) for v in pos) if isinstance(pos, list) else ""
        return f"#{player.id}\n{where}"

    def _q_target(self, target):
        """A target as a console argument: the player's id when known, else
        the quoted name."""
        player = self.models.roster.find(target)
        if player is not None and player.id is not None:
            return str(player.id)
        return self._q(target)
