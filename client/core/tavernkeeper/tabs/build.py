"""The Build tab: spawn, find, and work on what's selected, side by side.

Methods of TavernKeeperWindow, which inherits this mixin. Each section's code
is in spawn.py, select.py and move.py.
"""
import tkinter as tk

from tavern_shared.theme import BG


class BuildTabMixin:
    def _build_build_tab(self, parent):
        self._build_spawn_section(parent)
        columns = tk.Frame(parent, bg=BG)
        columns.pack(fill="both", expand=True)
        columns.columnconfigure(0, weight=3)
        columns.columnconfigure(1, weight=2)
        columns.rowconfigure(0, weight=1)
        left = tk.Frame(columns, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right = tk.Frame(columns, bg=BG)
        right.grid(row=0, column=1, sticky="nsew")
        self._build_find_section(left)
        self._build_move_section(right)
