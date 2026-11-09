"""Remote-console connection window (uses a console_token from the server owner)."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json, urllib.request

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from tavern_shared.ws_console_client import WsConsoleClient
from tavern_shared.console_commands import CONSOLE_COMMANDS

class RemoteConsoleWindow(tk.Toplevel):
    """Lets a player connect to a server owner's console *remotely*,
    authenticating with a console_token the owner shares with them
    directly — never anything read from a local file, unlike server.exe's
    own ConsoleWindow, since (unlike a server admin talking to their own
    locally-running game) there's no local console_token.txt for this
    launcher to trust in the first place. The console UI itself, once
    connected, is identical to server.exe's version — same protocol, same
    autocomplete, same everything — just reached via a connect step
    first instead of an automatic local connection."""
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Remote Console")
        self.configure(bg=BG)
        self.resizable(True, True)
        _set_window_icon(self)
        self._ws_client = None
        self._connected = False
        self._stop      = threading.Event()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._build_connect_form()
        _finish_dark_window(self)

    def _build_connect_form(self):
        self.geometry("420x320")
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🖥  Remote Console", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tk.Label(self,
            text="Connects to another server owner's console remotely. You'll "
                 "need the server's IP and the console token they give you directly "
                 "— this is never read from any file on your own machine.",
            bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=370, justify="left"
        ).pack(anchor="w", padx=20, pady=(10,4))

        _section_label(self, "SERVER IP")
        hf = _field(self)
        self.v_host = tk.StringVar()
        host_entry = tk.Entry(hf, textvariable=self.v_host, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6)
        host_entry.pack(fill="x")

        _section_label(self, "CONSOLE TOKEN")
        tf = _field(self)
        self.v_token = tk.StringVar()
        token_entry = tk.Entry(tf, textvariable=self.v_token, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, show="●")
        token_entry.pack(fill="x")
        tk.Label(self,
            text="Given to you by the server owner — the same token their "
                 "own server.exe uses for its own local console access.",
            bg=BG, fg=MUTED, font=("Segoe UI",8), justify="left", anchor="w",
            wraplength=370).pack(fill="x", padx=22, pady=(2,4))

        self._connect_status = tk.StringVar(value="")
        tk.Label(self, textvariable=self._connect_status, bg=BG, fg=RED,
                 font=("Segoe UI",9), wraplength=370, justify="left"
        ).pack(anchor="w", padx=22, pady=(2,0))

        self._connect_btn = _btn(self, "Connect", self._attempt_connect, "primary",
             font=("Georgia",10,"bold"), pady=10)
        self._connect_btn.pack(fill="x", padx=20, pady=(10,16))

        host_entry.bind("<Return>", lambda e: token_entry.focus_set())
        token_entry.bind("<Return>", lambda e: self._attempt_connect())
        host_entry.focus_set()

        self.update_idletasks()
        self.geometry(f"420x{self.winfo_reqheight()}")

    def _attempt_connect(self):
        host = self.v_host.get().strip() or "127.0.0.1"
        token = self.v_token.get().strip()
        if not token:
            self._connect_status.set("Enter the console token.")
            return
        self._connect_btn.config(state="disabled", text="Connecting…")
        self._connect_status.set("")
        self._ws_client = WsConsoleClient()

        def worker():
            ok, msg = self._ws_client.connect(
                host, token,
                on_line=lambda t: self.after(0, lambda p=t: self._append(p)),
                on_disc=lambda r: self.after(0, lambda: self._on_disconnected(r)),
            )
            if ok:
                self._connected = True
                self.after(0, lambda: self._connect_succeeded(host))
            else:
                self.after(0, lambda m=msg: self._connect_failed(m))
        threading.Thread(target=worker, daemon=True).start()

    def _connect_failed(self, msg):
        self._connect_btn.config(state="normal", text="Connect")
        self._connect_status.set(msg)

    def _connect_succeeded(self, host):
        self._host = host
        for child in list(self.winfo_children()):
            child.destroy()
        self.minsize(1, 1)
        self._build_console_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._append("[Connected]\n", "ok")

    def _build_console_ui(self):
        self.geometry("700x560")
        self.minsize(620, 480)
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"🖥  Remote Console — {self._host}", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        self._status_var = tk.StringVar(value="Connected")
        tk.Label(h, textvariable=self._status_var, bg=SURF, fg=MUTED,
                 font=("Segoe UI",9)).pack(side="right", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=12, pady=(10,6))
        lb = tk.Frame(lf, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True)
        self.out = tk.Text(lb, bg=SURF, fg="#b09a78", font=MONO, height=20,
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
            self._ac_listbox.config(height=min(8, len(matches)))
            self._ac_frame.place(in_=entry, x=0, rely=0.0, anchor="sw",
                                 width=entry.winfo_width())
            self._ac_frame.lift()
            self._ac_visible = True

        def _update_autocomplete(event=None):
            if event is not None and event.keysym in ("Down","Up","Tab","Return","Escape"):
                return
            text = self.v_cmd.get().strip().lower()
            if not text:
                _hide_autocomplete()
                return
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
        if hasattr(self, "_ws_client") and self._ws_client:
            self._ws_client.disconnect()
        self.destroy()

