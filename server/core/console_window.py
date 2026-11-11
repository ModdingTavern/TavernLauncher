"""Local (owner-side) live console window."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from tavern_shared.ws_console_client import WsConsoleClient
from tavern_shared.console_commands import CONSOLE_COMMANDS
from server.core.data_store import CONSOLE_TOKEN_FILE

class ConsoleWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Console")
        self.configure(bg=BG)
        self.geometry("640x480")
        self.resizable(True, True)
        _set_window_icon(self)
        self._ws_client = None
        self._connected = False
        self._stop      = threading.Event()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _finish_dark_window(self)
        self._connect()

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🖥  Console", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        self._status_var = tk.StringVar(value="Connecting…")
        tk.Label(h, textvariable=self._status_var, bg=SURF, fg=MUTED,
                 font=("Segoe UI",9)).pack(side="right", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=12, pady=(10,6))
        lb = tk.Frame(lf, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True)
        self.out = tk.Text(lb, bg=SURF, fg="#b09a78", font=MONO,
                           relief="flat", bd=0, state="disabled", wrap="word")
        sb = _mk_scrollbar(lb, self.out.yview)
        sb.pack(side="right", fill="y")
        self.out.config(yscrollcommand=sb.set)
        self.out.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        for t,c in [("ok",GREEN),("warn",AMBER),("err",RED),("cyan",CYAN)]:
            self.out.tag_config(t, foreground=c)

        cf = tk.Frame(self, bg=BG)
        cf.pack(fill="x", padx=12, pady=(0,12))
        self.v_cmd = tk.StringVar()
        entry = tk.Entry(cf, textvariable=self.v_cmd, bg=SURF, fg=PARCH,
                         insertbackground=AMBER, relief="flat", font=("Consolas",10),
                         bd=6)
        entry.pack(side="left", fill="x", expand=True)
        entry.focus_set()
        _btn(cf, "Send", self._send, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=14).pack(side="left", padx=(6,0))

        # ── Command autocomplete ──────────────────────────────────────────────
        # A floating suggestion list under the entry, positioned via place(in_=)
        # so it overlays correctly regardless of the pack layout around it.
        # Wrapped in its own frame (rather than placing the Listbox directly)
        # so a real Scrollbar can sit alongside it — some command groups
        # (e.g. "player") have 30+ matches for one prefix, far more than
        # comfortably fit on screen at once, and without a scrollbar those
        # extra matches would be completely unreachable by mouse, not just
        # initially hidden.
        self._ac_frame = tk.Frame(self, bg=SURF2, highlightbackground=BORDER,
                                  highlightthickness=1)
        self._ac_listbox = tk.Listbox(self._ac_frame, bg=SURF2, fg=PARCH,
                                      selectbackground=AMBERDIM, selectforeground="#ffd080",
                                      relief="flat", bd=0, highlightthickness=0,
                                      font=("Consolas",10), activestyle="none")
        self._ac_scrollbar = _mk_scrollbar(self._ac_frame, self._ac_listbox.yview)
        self._ac_scrollbar.pack(side="right", fill="y")
        self._ac_listbox.config(yscrollcommand=self._ac_scrollbar.set)
        self._ac_listbox.pack(side="left", fill="both", expand=True)
        self._ac_visible = False
        self._ac_matches = []

        def _hide_autocomplete():
            if self._ac_visible:
                self._ac_frame.place_forget()
                self._ac_visible = False

        def _show_autocomplete(matches):
            self._ac_matches = matches
            self._ac_listbox.delete(0, "end")
            for m in matches:
                params = CONSOLE_COMMANDS.get(m, [])
                display = f"{m}  [{', '.join(params)}]" if params else m
                self._ac_listbox.insert("end", display)
            self._ac_listbox.selection_clear(0, "end")
            self._ac_listbox.selection_set(0)
            # Only the VISIBLE row count is capped — matches itself already
            # holds everything that matched, all of it reachable via the
            # scrollbar or by continuing to type/arrow-key through it.
            self._ac_listbox.config(height=min(8, len(matches)))
            # Anchored ABOVE the entry (its own bottom-left corner sits at
            # the entry's top-left), not below it — the entry sits right
            # above the Send button near the window's bottom edge, so a
            # dropdown growing downward from there had nowhere to go and
            # got clipped by the window itself. Growing upward into the
            # (much larger) output area actually has room to work with.
            self._ac_frame.place(in_=entry, x=0, rely=0.0, anchor="sw",
                                 width=entry.winfo_width())
            self._ac_frame.lift()
            self._ac_visible = True

        def _update_autocomplete(event=None):
            # Down/Up/Tab/Return/Escape also fire a generic KeyRelease —
            # without this guard, navigating the list with arrow keys would
            # immediately re-filter and snap the selection back to the top,
            # since the text itself hasn't changed but this handler would
            # still run and rebuild the list from scratch.
            if event is not None and event.keysym in ("Down","Up","Tab","Return","Escape"):
                return
            text = self.v_cmd.get().strip().lower()
            if not text:
                _hide_autocomplete()
                return
            # No practical cap here — with 294 total commands, even a broad
            # prefix stays comfortably scrollable; truncating this list (as
            # opposed to just the visible height above) is what silently
            # hid real completions like "player kick" before.
            matches = [c for c in CONSOLE_COMMANDS if c.startswith(text)]
            if matches and matches != [text]:
                _show_autocomplete(matches)
            else:
                _hide_autocomplete()

        def _accept_selected(event=None):
            if not self._ac_visible:
                return None
            sel = self._ac_listbox.curselection()
            idx = sel[0] if sel else 0
            if 0 <= idx < len(self._ac_matches):
                self.v_cmd.set(self._ac_matches[idx] + " ")
                entry.icursor("end")
            _hide_autocomplete()
            return "break"

        def _move_selection(delta):
            if not self._ac_visible:
                return
            sel = self._ac_listbox.curselection()
            idx = sel[0] if sel else 0
            idx = max(0, min(len(self._ac_matches)-1, idx+delta))
            self._ac_listbox.selection_clear(0, "end")
            self._ac_listbox.selection_set(idx)
            self._ac_listbox.activate(idx)
            self._ac_listbox.see(idx)

        def _on_return(event=None):
            if self._ac_visible:
                return _accept_selected()
            self._send()
            return None

        def _on_listbox_click(event=None):
            _accept_selected()
            entry.focus_set()

        entry.bind("<KeyRelease>", _update_autocomplete)
        entry.bind("<Return>", _on_return)
        entry.bind("<Tab>", _accept_selected)
        entry.bind("<Down>", lambda e: (_move_selection(1), "break")[1])
        entry.bind("<Up>", lambda e: (_move_selection(-1), "break")[1])
        entry.bind("<Escape>", lambda e: _hide_autocomplete())
        self._ac_listbox.bind("<ButtonRelease-1>", _on_listbox_click)
        self._hide_autocomplete = _hide_autocomplete

    def _append(self, text, tag=""):
        self.out.config(state="normal")
        self.out.insert("end", text, tag)
        self.out.see("end")
        self.out.config(state="disabled")

    def _connect(self):
        try:
            with open(CONSOLE_TOKEN_FILE) as f:
                token = f.read().strip()
        except Exception:
            self._status_var.set("No console token")
            self._append("console_token.txt not found — start the server first.\n", "err")
            return
        client = self._ws_client = WsConsoleClient()

        def worker():
            ok, msg = client.connect(
                "127.0.0.1", token,
                on_line=lambda t: self.after(0, lambda p=t: self._append(p)),
                on_disc=lambda r: self.after(0, lambda: self._on_disconnected(r)),
            )
            if self._stop.is_set():
                # Closed while connecting: drop the socket nobody will read.
                client.disconnect()
                return
            if ok:
                self._connected = True
                self.after(0, lambda: self._status_var.set("Connected"))
                self.after(0, lambda: self._append("[Connected]\n", "ok"))
            else:
                self.after(0, lambda m=msg: self._status_var.set(f"Error: {m}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_disconnected(self, msg):
        self._connected = False
        self._status_var.set("Disconnected")
        self._append(f"\n[{msg}]\n", "err")

    def _send(self):
        cmd = self.v_cmd.get().strip()
        if not cmd or not self._connected:
            return
        self.v_cmd.set("")
        self._append(f"> {cmd}\n", "cyan")
        if not self._ws_client.send(cmd):
            self._append("Not sent: not connected\n", "err")

    def _on_close(self):
        self._stop.set()
        if self._ws_client is not None:
            self._ws_client.disconnect()
        self.destroy()

