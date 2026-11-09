"""Small pieces the TavernKeeper tabs and frame share."""
import math
import tkinter as tk
from tkinter import messagebox

from tavern_shared.screen_fit import SCROLL_STEP, ScrollArea, wheel_step
from tavern_shared.theme import BG, SURF, SURF2, BORDER, AMBERDIM, PARCH, MUTED, RED, _btn

TAB_GAP = 2


def confirm(window, title, message):
    """Ask before something that can't be undone. Enter on the dialog means No."""
    return messagebox.askyesno(title, message, icon="warning", default="no", parent=window)


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
