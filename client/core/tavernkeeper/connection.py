"""Connecting, reconnecting and sending commands.

Methods of TavernKeeperWindow, which inherits this mixin.
"""
import threading
import tkinter as tk

from tavern_shared.theme import (
    BG, SURF, BORDER, AMBER, PARCH, MUTED, RED, _btn, _field, _section_label,
)
from tavern_shared.ws_console_client import WsConsoleClient
from client.core.tavernkeeper.api import Result


class ConnectionMixin:
    # ── Connection ───────────────────────────────────────────────────────────

    def _build_connect_form(self):
        self.geometry("420x300")
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🧩  TavernKeeper", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tk.Label(self,
            text="Connects to a server's console, the same way Remote Console does. "
                 "You'll need the server's IP and a console token from the owner.",
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
                on_line=lambda t: self.after(0, lambda p=t: self._on_line(p)),
                on_disc=lambda r: self.after(0, lambda: self._on_disconnected(r)),
            )
            if ok:
                self._connected = True
                self.after(0, self._connect_succeeded)
            else:
                self.after(0, lambda m=msg: self._connect_failed(m))
        threading.Thread(target=worker, daemon=True).start()

    def _connect_failed(self, msg):
        self._connect_btn.config(state="normal", text="Connect")
        self._connect_status.set(msg)

    def _connect_succeeded(self):
        for child in list(self.winfo_children()):
            child.destroy()
        self.minsize(1, 1)
        self._build_main_ui()
        self._refresh_players()
        self.api._fire("connected")

    def _on_disconnected(self, msg):
        self._connected = False
        if hasattr(self, "_log_status"):
            self._log_status.set("Disconnected")
        if hasattr(self, "out"):
            self._append_log(f"\n[{msg}]\n", "err")
        if hasattr(self, "_reconnect_btn"):
            self._reconnect_btn.pack(side="right")
        self.api._fire("disconnected", msg)

    def _reconnect(self):
        """Reconnect in place with the same host and token, so the tabs keep
        their state."""
        host = self.v_host.get().strip() or "127.0.0.1"
        token = self.v_token.get().strip()
        self._reconnect_btn.config(state="disabled", text="Reconnecting...")
        self._ws_client = WsConsoleClient()

        def worker():
            ok, msg = self._ws_client.connect(
                host, token,
                on_line=lambda t: self.after(0, lambda p=t: self._on_line(p)),
                on_disc=lambda r: self.after(0, lambda: self._on_disconnected(r)),
            )
            self.after(0, lambda: self._reconnect_done(ok, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _reconnect_done(self, ok, msg):
        self._reconnect_btn.config(state="normal", text="Reconnect")
        if not ok:
            self._append_log(f"[Reconnect failed: {msg}]\n", "err")
            return
        self._connected = True
        self._log_status.set("Connected")
        self._reconnect_btn.pack_forget()
        self._append_log("[Reconnected]\n", "ok")
        self._refresh_players()
        self.api._fire("connected")

    def _on_line(self, text):
        """Called by WsConsoleClient for streaming output — display only."""
        self._append_log(text)

    # ── Sending ──────────────────────────────────────────────────────────────

    def _send(self, cmd):
        """Fire-and-forget — output arrives via _on_line callback."""
        self._append_log(f"> {cmd}\n", "cyan")
        if not (self._connected and self._ws_client.send(cmd)):
            self._append_log("Not sent: not connected\n", "err")
            return False
        return True

    def _send_and_capture(self, cmd, on_result, quiet=0.4, max_wait=20.0):
        """Send a command and deliver (result_string, result_data) to on_result.
        Uses WsConsoleClient.send_capture — blocks in a worker thread,
        then calls on_result(result_string, result_data) on the Tk thread.
        quiet and max_wait are kept for API compatibility but max_wait
        is used as the capture timeout."""
        self._run_command(cmd, lambda r: on_result(r.raw, r.value), timeout=max_wait)

    def _run_command(self, cmd, on_result, timeout=20.0, quiet=False):
        """Send a command and hand a Result to on_result on the Tk thread.
        quiet leaves the command and any failure out of the log."""
        if not quiet:
            self._append_log(f"> {cmd}\n", "cyan")
        if not self._connected:
            if not quiet:
                self._append_log("Not sent: not connected\n", "err")
            self.after(0, lambda: on_result(Result.failed("Not connected")))
            return

        def worker():
            result = Result.from_reply(self._ws_client.request(cmd, timeout=timeout))
            if result.error and not quiet:
                self.after(0, lambda: self._append_log(f"[{cmd} failed: {result.error}]\n", "err"))
            self.after(0, lambda: on_result(result))
        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _q(value):
        """Quotes a value for a console command argument, matching the
        convention already used elsewhere in this project."""
        return f'"{value}"'
