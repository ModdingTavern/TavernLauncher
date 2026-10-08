"""
The Mods install/update window -- identical between both apps today
(confirmed via diff), so it lives here once. Depends on tavern_shared's
theme + mod_install modules.
"""
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN,
    _btn, _section_label,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window
from tavern_shared.mod_install import (
    _detect_exe_arch, _melonloader_installed, _install_melonloader,
    _melonloader_status, _tavernlib_status, _install_tavernlib,
    _circuitsvoicechat_status, _install_circuitsvoicechat,
    _tavernessentials_status, _install_tavernessentials,
)

class ModsWindow(tk.Toplevel):
    def __init__(self, parent, exe_path, on_status_change=None):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Mods")
        self.configure(bg=BG)
        self.geometry("520x420")
        self.resizable(False, False)
        self._exe = exe_path
        self._game_dir = os.path.dirname(exe_path)
        self._busy = False
        self._on_status_change = on_status_change
        self._build()
        self.update_idletasks()
        self.geometry(f"520x{self.winfo_reqheight()}")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _finish_dark_window(self)

    def _on_close(self):
        if self._on_status_change: self._on_status_change()
        self.destroy()

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🧪  Mods", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tk.Label(self,
            text="These set up modding for A Township Tale on this machine. "
                 "Install MelonLoader first, then the others. If GitHub can't be "
                 "reached (some networks/antivirus block it), the version bundled "
                 "with this launcher is used automatically instead.",
            bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=470, justify="left"
        ).pack(anchor="w", padx=20, pady=(10,4))

        _section_label(self, "REQUIRED MODS")
        self._ml_btn = self._mod_row(
            "MelonLoader", "The mod loader itself — required before anything else.",
            self._on_melonloader_click)
        self._tl_btn = self._mod_row(
            "TavernLib", "Our plugin — adds this server's mod support to the game.",
            self._on_tavernlib_click)

        _section_label(self, "OPTIONAL MODS")
        self._cvc_btn = self._mod_row(
            "CircuitsVoiceChat", "Proximity voice chat for players on this server.",
            self._on_circuitsvoicechat_click)
        self._te_btn = self._mod_row(
            "TavernEssentials",
            "A framework to restore the original main menu functionality as well as plenty of social features and more - created by Shadow!",
            self._on_tavernessentials_click)

        tk.Label(self, text="More mods will be manageable from here later.",
                 bg=BG, fg=MUTED, font=("Segoe UI",8,"italic")
        ).pack(anchor="w", padx=22, pady=(2,8))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20)
        self._status = tk.StringVar(value="")
        tk.Label(self, textvariable=self._status, bg=BG, fg=CYAN,
                 font=("Segoe UI",9), wraplength=470, justify="left"
        ).pack(anchor="w", padx=20, pady=10)

        self._refresh_states()

    def _mod_row(self, title, subtitle, on_click):
        row = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        row.pack(fill="x", padx=20, pady=4)
        dotvar = tk.StringVar(value="○")
        dot = tk.Label(row, textvariable=dotvar, bg=SURF, fg=MUTED, font=("Segoe UI",13))
        dot.pack(side="left", padx=(14,10), pady=10)
        tf = tk.Frame(row, bg=SURF)
        tf.pack(side="left", fill="both", expand=True, pady=8)
        tk.Label(tf, text=title, bg=SURF, fg=PARCH, font=("Georgia",10,"bold")).pack(anchor="w")
        subvar = tk.StringVar(value=subtitle)
        tk.Label(tf, textvariable=subvar, bg=SURF, fg=MUTED, font=("Segoe UI",8),
                 wraplength=280, justify="left").pack(anchor="w")
        btn = _btn(row, "…", on_click, font=("Segoe UI",9), pady=6, padx=12)
        btn.pack(side="right", padx=12)
        btn._dotvar = dotvar
        btn._dotlabel = dot
        btn._subvar = subvar
        btn._subtitle = subtitle
        return btn

    # ── Status ───────────────────────────────────────────────────────────────

    _STATE_STYLE = {
        "missing":  ("○", MUTED, "⬇ Install"),
        "outdated": ("⚠", AMBER, "⟳ Update"),
        "unknown":  ("●", MUTED, "⟳ Reinstall"),
        "current":  ("●", GREEN, "⟳ Reinstall"),
    }
    _STATE_NOTE = {
        "missing": None,
        "outdated": "Update available.",
        "unknown": None,
        "current": "Up to date.",
    }

    def _refresh_states(self, keep_status=None):
        self._status.set(keep_status or "Checking status…")
        def worker():
            ml = _melonloader_status(self._game_dir)
            tl = _tavernlib_status(self._game_dir)
            cvc = _circuitsvoicechat_status(self._game_dir)
            te = _tavernessentials_status(self._game_dir)
            self.after(0, lambda: self._apply_states(ml, tl, cvc, te, keep_status))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_states(self, ml_state, tl_state, cvc_state, te_state, keep_status=None):
        self._apply_row_state(self._ml_btn, ml_state)
        self._apply_row_state(self._tl_btn, tl_state)
        self._apply_row_state(self._cvc_btn, cvc_state)
        self._apply_row_state(self._te_btn, te_state)
        self._status.set(keep_status or "")
        self._fit_height()  # a long install error needs room to be readable
        if self._on_status_change: self._on_status_change()

    def _fit_height(self):
        self.update_idletasks()
        self.geometry(f"520x{self.winfo_reqheight()}")

    def _apply_row_state(self, btn, state):
        dot, color, text = self._STATE_STYLE[state]
        btn._dotvar.set(dot)
        btn._dotlabel.config(fg=color)
        btn.config(text=text)
        note = self._STATE_NOTE[state]
        btn._subvar.set(f"{btn._subtitle}  ·  {note}" if note else btn._subtitle)

    def _set_busy(self, busy, msg=""):
        self._busy = busy
        state = "disabled" if busy else "normal"
        self._ml_btn.config(state=state)
        self._tl_btn.config(state=state)
        self._cvc_btn.config(state=state)
        self._te_btn.config(state=state)
        self._status.set(msg)

    def _on_melonloader_click(self):
        if self._busy: return
        arch = _detect_exe_arch(self._exe)
        if not arch:
            messagebox.showerror("Can't tell architecture",
                "Couldn't determine whether the game is 32- or 64-bit from "
                "the selected .exe. Try re-browsing to it on the main screen.", parent=self)
            return
        self._set_busy(True, f"Detected {arch} game — starting install…")

        def worker():
            try:
                _install_melonloader(self._game_dir, arch,
                    lambda m: self.after(0, lambda: self._status.set(m)))
                self.after(0, lambda: self._finish_install(True, "MelonLoader installed."))
            except Exception as e:
                msg = f"Install failed: {e}"  # e is gone by the time the callback runs
                self.after(0, lambda: self._finish_install(False, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_tavernlib_click(self):
        if self._busy: return
        if not _melonloader_installed(self._game_dir):
            messagebox.showwarning("Install MelonLoader first",
                "TavernLib is a MelonLoader plugin — install MelonLoader above first.", parent=self)
            return
        self._set_busy(True, "Starting TavernLib install…")

        def worker():
            try:
                _install_tavernlib(self._game_dir,
                    lambda m: self.after(0, lambda: self._status.set(m)))
                self.after(0, lambda: self._finish_install(True, "TavernLib installed."))
            except Exception as e:
                msg = f"Install failed: {e}"  # e is gone by the time the callback runs
                self.after(0, lambda: self._finish_install(False, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_circuitsvoicechat_click(self):
        if self._busy: return
        if not _melonloader_installed(self._game_dir):
            messagebox.showwarning("Install MelonLoader first",
                "CircuitsVoiceChat is a MelonLoader mod — install MelonLoader above first.", parent=self)
            return
        self._set_busy(True, "Installing CircuitsVoiceChat…")

        def worker():
            try:
                _install_circuitsvoicechat(self._game_dir,
                    lambda m: self.after(0, lambda: self._status.set(m)))
                self.after(0, lambda: self._finish_install(True, "CircuitsVoiceChat installed."))
            except Exception as e:
                msg = f"Install failed: {e}"  # e is gone by the time the callback runs
                self.after(0, lambda: self._finish_install(False, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _on_tavernessentials_click(self):
        if self._busy: return
        if not _melonloader_installed(self._game_dir):
            messagebox.showwarning("Install MelonLoader first",
                "TavernEssentials is a MelonLoader mod — install MelonLoader above first.", parent=self)
            return
        self._set_busy(True, "Installing TavernEssentials…")

        def worker():
            try:
                result = _install_tavernessentials(self._game_dir,
                    lambda m: self.after(0, lambda: self._status.set(m)))
                done = ("TavernEssentials is already up to date." if result == "current"
                        else "TavernEssentials installed.")
                self.after(0, lambda: self._finish_install(True, done))
            except Exception as e:
                msg = f"Install failed: {e}"  # e is gone by the time the callback runs
                self.after(0, lambda: self._finish_install(False, msg))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_install(self, ok, msg):
        self._set_busy(False, msg)
        self._refresh_states(keep_status=msg)

