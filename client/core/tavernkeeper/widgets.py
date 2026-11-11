"""Small pieces the TavernKeeper tabs and frame share."""
import math
import re
import tkinter as tk
from tkinter import messagebox, ttk

from tavern_shared.screen_fit import SCROLL_STEP, ScrollArea, wheel_step
from tavern_shared.theme import (
    AMBER, AMBERDIM, BG, BORDER, MUTED, PARCH, RED, SURF, SURF2, _btn, _fix_combobox_popdown_colors,
)

TAB_GAP = 2
PLAYER_NOT_FOUND = re.compile(r"Player(List)? \w+ : value was null")


def confirm(window, title, message):
    """Ask before something that can't be undone. Enter on the dialog means No."""
    return messagebox.askyesno(title, message, icon="warning", default="no", parent=window)


def error_text(error):
    """A server error in plain words."""
    text = " ".join(re.sub(r"^\[CommandService\.Handle\]\s*", "", error).split())
    if PLAYER_NOT_FOUND.search(text):
        return "That player isn't online."
    if text == "Failed sending request":
        return "This server can't look up player accounts, so this doesn't work here."
    return text


def entity_name(text):
    """A game object's display name, without its id prefix and (Clone)."""
    return re.sub(r"^\d+ - |\(Clone\)$", "", str(text))


def parse_vector(text):
    """x,y,z with no spaces, the only shape the console takes, or None."""
    parts = re.sub(r"\s", "", text).split(",")
    try:
        return ",".join(parts) if len(parts) == 3 and all(float(p) is not None for p in parts) else None
    except ValueError:
        return None


def form_row(parent):
    row = tk.Frame(parent, bg=BG)
    row.pack(fill="x", padx=20, pady=(0, 4))
    return row


def form_text(row, text):
    tk.Label(row, text=text, bg=BG, fg=PARCH, font=("Segoe UI", 9)).pack(side="left", padx=(0, 6))


def form_entry(row, var, width):
    entry = tk.Entry(row, textvariable=var, bg=SURF, fg=PARCH, insertbackground=AMBER, relief="flat",
                     font=("Consolas", 10), bd=4, width=width)
    entry.pack(side="left", padx=(0, 8))
    return entry


def form_button(row, text, command, style="normal"):
    font = ("Segoe UI", 9, "bold") if style != "normal" else ("Segoe UI", 9)
    button = _btn(row, text, command, style, font=font, pady=5, padx=10)
    button.pack(side="left", padx=(0, 6))
    return button


def form_combo(row, var, values=(), width=18, editable=False, **options):
    combo = ttk.Combobox(row, textvariable=var, values=values, width=width, font=("Consolas", 10),
                         style="Tavk.Target.TCombobox", state="normal" if editable else "readonly", **options)
    combo.pack(side="left", padx=(0, 8))
    _fix_combobox_popdown_colors(combo, SURF, PARCH, AMBERDIM, "#ffd080")
    return combo


def status_line(parent):
    label = tk.Label(parent, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left",
                     wraplength=600)
    label.pack(fill="x", padx=22, pady=(0, 2))
    return label


def say(label, text, color=MUTED):
    label.config(text=text, fg=color)


def read_number(var, label, what, kind=float):
    try:
        return kind(var.get().strip())
    except ValueError:
        say(label, f"Enter a number for {what}.", RED)
        return None


class _TabStrip(ScrollArea):
    """One row that only scrolls sideways, on the plain wheel too."""

    def _need_height(self):
        return 0

    def _scroll(self, event):
        if self._show_h:
            self.canvas.xview_scroll(wheel_step(event), "units")


class TabBar:
    """A notebook's tabs in one row with every name in full, scrolling sideways
    when they don't fit. The notebook's own tabs are hidden; it still decides
    which page shows."""

    def __init__(self, parent, notebook):
        self.notebook = notebook
        self.strip = _TabStrip(parent, BG)
        self.frame = self.strip.shell
        self.buttons = {}
        notebook.bind("<<NotebookTabChanged>>", self.mark, add="+")

    def add(self, page, label):
        button = _btn(self.strip.body, label, lambda: self._open(page),
                      font=("Georgia", 9), pady=5, padx=8)
        self.buttons[str(page)] = button
        self.strip.canvas.configure(height=button.winfo_reqheight())

    def _open(self, page):
        self.notebook.select(page)
        self._reveal(self.buttons[str(page)])

    def refresh(self):
        for tab in self.notebook.tabs():
            self.buttons[tab].pack_forget()
            self.buttons[tab].pack(side="left", padx=(0, TAB_GAP))
        self.mark()

    def mark(self, event=None):
        current = self.notebook.select()
        for tab, button in self.buttons.items():
            selected = tab == current
            button.config(bg=AMBERDIM if selected else SURF2, fg="#ffd080" if selected else PARCH)
        if current:
            self.frame.after_idle(lambda: self._reveal(self.buttons[current]))

    def _reveal(self, button):
        """Slides the row so the open tab's whole name is in view."""
        canvas = self.strip.canvas
        total = self.strip.body.winfo_width()
        view = canvas.winfo_width()
        if total <= view:
            return
        left = button.winfo_x()
        right = left + button.winfo_width()
        origin = canvas.canvasx(0)
        if left < origin:
            canvas.xview_moveto(math.floor(left / SCROLL_STEP) * SCROLL_STEP / total)
        elif right > origin + view:
            canvas.xview_moveto(math.ceil((right - view) / SCROLL_STEP) * SCROLL_STEP / total)


def error_card(parent, label, details):
    """Fills a tab whose build failed. The details are selectable and copyable."""
    card = tk.Frame(parent, bg=SURF, highlightbackground=RED, highlightthickness=1)
    card.pack(fill="both", expand=True, padx=12, pady=12)
    tk.Label(card, text=f"The {label} tab couldn't be built", bg=SURF, fg=RED,
             font=("Georgia", 11, "bold")).pack(anchor="w", padx=12, pady=(12, 2))
    tk.Label(card, text="The other tabs still work. Send these details to whoever made this tab.",
             bg=SURF, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", padx=12, pady=(0, 8))

    def copy():
        card.clipboard_clear()
        card.clipboard_append(details)

    _btn(card, "Copy Details", copy, font=("Segoe UI", 8), pady=3, padx=8).pack(
        side="bottom", anchor="e", padx=12, pady=(6, 12))
    text = tk.Text(card, bg=SURF2, fg=PARCH, font=("Consolas", 9), height=8, width=60, wrap="word",
                   relief="flat", bd=6, highlightbackground=BORDER, highlightthickness=1)
    text.insert("1.0", details)
    text.config(state="disabled")
    text.pack(fill="both", expand=True, padx=12)
