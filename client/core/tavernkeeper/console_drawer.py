"""The console drawer: TavernKeeper's log and a raw command line.

Runs on the window's own connection, so it needs no second login. Remote
Console stays as its own window for anyone who prefers it.
"""
import tkinter as tk

from tavern_shared.console_commands import CONSOLE_COMMANDS
from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO, _btn, _mk_scrollbar,
)

HISTORY_LIMIT = 200
MODIFIER_KEYS = ("Control_L", "Control_R", "Shift_L", "Shift_R", "Alt_L", "Alt_R")
NAVIGATION_KEYS = ("Down", "Up", "Tab", "Return", "Escape")


class ConsoleDrawerMixin:
    def _build_console_drawer(self, parent):
        drawer = tk.Frame(parent, bg=BG)
        small = {"font": ("Segoe UI", 8), "pady": 3, "padx": 8}

        bar = tk.Frame(drawer, bg=BG)
        bar.pack(side="top", fill="x", padx=12, pady=(6, 3))
        tk.Label(bar, text="CONSOLE", bg=BG, fg=MUTED, font=("Georgia", 8, "bold")).pack(side="left")
        self.v_log_filter = tk.StringVar(value="all")
        for text, value in (("All", "all"), ("Errors", "errors")):
            tk.Radiobutton(bar, text=text, value=value, variable=self.v_log_filter, indicatoron=False,
                           command=self._apply_log_filter, bg=SURF2, fg=PARCH, selectcolor=AMBERDIM,
                           activebackground=AMBERDIM, activeforeground="#ffd080", relief="flat", bd=0,
                           cursor="hand2", **small).pack(side="left", padx=(8, 0))
        self._console_expand_btn = _btn(bar, "Expand", self._toggle_console_expanded, **small)
        self._console_expand_btn.pack(side="right")
        _btn(bar, "Copy", self._copy_console, **small).pack(side="right", padx=(0, 6))
        _btn(bar, "Clear", self._clear_console, **small).pack(side="right", padx=(0, 6))

        row = tk.Frame(drawer, bg=BG)
        row.pack(side="bottom", fill="x", padx=12, pady=(3, 8))
        self.v_console = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.v_console, bg=SURF, fg=PARCH, insertbackground=AMBER,
                         relief="flat", font=("Consolas", 10), bd=6)
        entry.pack(side="left", fill="x", expand=True)
        self._console_entry = entry
        _btn(row, "Insert Player", self._insert_target_in_console, **small).pack(side="left", padx=(6, 0))
        _btn(row, "Send", self._send_console_line, "primary",
             font=("Segoe UI", 9, "bold"), pady=6, padx=14).pack(side="left", padx=(6, 0))

        frame = tk.Frame(drawer, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(side="top", fill="both", expand=True, padx=12)
        self.out = tk.Text(frame, bg=SURF, fg="#b09a78", font=MONO, height=6,
                           relief="flat", bd=0, state="disabled", wrap="word")
        sb = _mk_scrollbar(frame, self.out.yview)
        sb.pack(side="right", fill="y")
        self.out.config(yscrollcommand=sb.set)
        self.out.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        for t, c in [("ok", GREEN), ("warn", AMBER), ("err", RED), ("cyan", CYAN)]:
            self.out.tag_config(t, foreground=c)
        self.out.tag_config("nonerr", elide=False)

        self._console_history = []
        self._console_pos = None
        self._console_draft = ""
        self._console_expanded = False
        self._console_sash = None
        self._build_console_autocomplete(entry)
        return drawer

    # Log tools

    def _apply_log_filter(self):
        self.out.tag_config("nonerr", elide=self.v_log_filter.get() == "errors")
        self.out.see("end")

    def _visible_log(self):
        return self.out.tk.call(self.out, "get", "-displaychars", "1.0", "end-1c")

    def _clear_console(self):
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.config(state="disabled")

    def _copy_console(self):
        self.clipboard_clear()
        self.clipboard_append(self._visible_log())

    def _toggle_console_expanded(self):
        paned, tabs, drawer = self._paned, self._tabs_pane, self._console_drawer
        if self._console_expanded:
            paned.paneconfigure(tabs, hide=False)
            paned.paneconfigure(drawer, stretch="never")
            self.update_idletasks()
            if self._console_sash:
                paned.sash_place(0, *self._console_sash)
            self._console_expand_btn.config(text="Expand")
        else:
            self._console_sash = paned.sash_coord(0)
            paned.paneconfigure(tabs, hide=True)
            paned.paneconfigure(drawer, stretch="always")
            self._console_expand_btn.config(text="Collapse")
        self._console_expanded = not self._console_expanded

    # Command line

    def _send_console_line(self):
        cmd = self.v_console.get().strip()
        self._hide_console_suggestions()
        if not cmd:
            return
        history = self._console_history
        if not history or history[-1] != cmd:
            history.append(cmd)
            del history[:-HISTORY_LIMIT]
        self._console_pos = None
        self._console_draft = ""
        if self._send(cmd):
            self.v_console.set("")

    def _insert_target_in_console(self):
        target = self._current_target()
        if target:
            self._console_entry.insert("insert", self._q(target))
            self._console_entry.focus_set()

    def _step_console_history(self, delta):
        history = self._console_history
        self._hide_console_suggestions()
        if not history or (self._console_pos is None and delta > 0):
            return "break"
        if self._console_pos is None:
            self._console_draft = self.v_console.get()
            self._console_pos = len(history)
        pos = max(0, self._console_pos + delta)
        if pos >= len(history):
            self._console_pos = None
            self.v_console.set(self._console_draft)
        else:
            self._console_pos = pos
            self.v_console.set(history[pos])
        self._console_entry.icursor("end")
        return "break"

    # Autocomplete, the same list Remote Console shows

    def _build_console_autocomplete(self, entry):
        self._ac_frame = tk.Frame(self, bg=SURF2, highlightbackground=BORDER, highlightthickness=1)
        self._ac_listbox = tk.Listbox(self._ac_frame, bg=SURF2, fg=PARCH, selectbackground=AMBERDIM,
                                      selectforeground="#ffd080", relief="flat", bd=0,
                                      highlightthickness=0, font=("Consolas", 10), activestyle="none")
        scrollbar = _mk_scrollbar(self._ac_frame, self._ac_listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self._ac_listbox.config(yscrollcommand=scrollbar.set)
        self._ac_listbox.pack(side="left", fill="both", expand=True)
        self._ac_visible = False
        self._ac_matches = []
        self._ac_moved = False

        entry.bind("<KeyRelease>", self._update_console_suggestions)
        entry.bind("<Return>", self._on_console_return)
        entry.bind("<Tab>", self._accept_console_suggestion)
        entry.bind("<Down>", lambda e: self._move_console_suggestion(1))
        entry.bind("<Up>", lambda e: self._move_console_suggestion(-1))
        entry.bind("<Control-Up>", lambda e: self._step_console_history(-1))
        entry.bind("<Control-Down>", lambda e: self._step_console_history(1))
        entry.bind("<Escape>", lambda e: self._hide_console_suggestions())
        self._ac_listbox.bind("<ButtonRelease-1>", self._on_console_suggestion_click)

    def _hide_console_suggestions(self):
        if self._ac_visible:
            self._ac_frame.place_forget()
            self._ac_visible = False

    def _show_console_suggestions(self, matches):
        self._ac_matches = matches
        self._ac_moved = False
        self._ac_listbox.delete(0, "end")
        for m in matches:
            params = CONSOLE_COMMANDS.get(m, [])
            self._ac_listbox.insert("end", f"{m}  [{', '.join(params)}]" if params else m)
        self._ac_listbox.selection_clear(0, "end")
        self._ac_listbox.selection_set(0)
        self._ac_listbox.config(height=min(8, len(matches)))
        entry = self._console_entry
        self._ac_frame.place(in_=entry, x=0, rely=0.0, anchor="sw", width=entry.winfo_width())
        self._ac_frame.lift()
        self._ac_visible = True

    def _update_console_suggestions(self, event=None):
        if event is not None and event.keysym in NAVIGATION_KEYS + MODIFIER_KEYS:
            return
        text = self.v_console.get().strip().lower()
        if not text:
            self._hide_console_suggestions()
            return
        matches = [c for c in CONSOLE_COMMANDS if c.startswith(text)]
        if matches and matches != [text]:
            self._show_console_suggestions(matches)
        else:
            self._hide_console_suggestions()

    def _accept_console_suggestion(self, event=None):
        if not self._ac_visible:
            return None
        sel = self._ac_listbox.curselection()
        idx = sel[0] if sel else 0
        if 0 <= idx < len(self._ac_matches):
            self.v_console.set(self._ac_matches[idx] + " ")
            self._console_entry.icursor("end")
        self._hide_console_suggestions()
        return "break"

    def _move_console_suggestion(self, delta):
        if self._ac_visible:
            sel = self._ac_listbox.curselection()
            idx = max(0, min(len(self._ac_matches) - 1, (sel[0] if sel else 0) + delta))
            self._ac_listbox.selection_clear(0, "end")
            self._ac_listbox.selection_set(idx)
            self._ac_listbox.activate(idx)
            self._ac_listbox.see(idx)
            self._ac_moved = True
        return "break"

    def _on_console_return(self, event=None):
        text = self.v_console.get().strip().lower()
        if self._ac_visible and (self._ac_moved or text not in CONSOLE_COMMANDS):
            return self._accept_console_suggestion()
        self._send_console_line()
        return "break"

    def _on_console_suggestion_click(self, event=None):
        self._accept_console_suggestion()
        self._console_entry.focus_set()
