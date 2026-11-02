"""Advanced server settings - small key/value editor."""
import math
import tkinter as tk
from tkinter import messagebox

from tavern_shared.theme import BG, SURF, BORDER, AMBER, PARCH, _btn
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from server.core.data_store import load_server_settings, save_server_settings

# (label, settings key, default, type, whether 0 is a valid value)
ADVANCED_FIELDS = [
    ("GarbageCollectionTime",  "garbage_collection_timer",  30, float, False),
    ("ServerBackupTime",       "server_backup_time",         0, float, True),
    ("ServerBackupMaxBackups", "server_backup_max_backups",  0, int,   True),
]


class AdvancedSettingsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Advanced Settings")
        self.configure(bg=BG)
        self.geometry("380x200")
        self.resizable(False, False)
        _set_window_icon(self)
        self._vars = {}
        self._build()
        self.update_idletasks()
        self.geometry(f"380x{self.winfo_reqheight()}")
        _finish_dark_window(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=40)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚙  Advanced Settings", bg=SURF, fg=AMBER,
                 font=("Georgia",11,"bold")).pack(side="left", padx=14, pady=6)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        ss = load_server_settings()

        rows = tk.Frame(self, bg=BG)
        rows.pack(fill="x", padx=16, pady=(10,8))
        rows.columnconfigure(1, weight=1)

        for i, (label, key, default, value_type, zero_ok) in enumerate(ADVANCED_FIELDS):
            tk.Label(rows, text=label, bg=BG, fg=PARCH,
                     font=("Segoe UI",9)).grid(row=i, column=0, sticky="w", pady=4, padx=(0,10))
            shown = ss.get(key, default)
            var = tk.StringVar(value=f"{shown:g}" if isinstance(shown, float) else str(shown))
            tk.Entry(rows, textvariable=var, bg=SURF, fg=PARCH,
                     insertbackground=AMBER, relief="flat", font=("Consolas",10),
                     bd=5, width=12).grid(row=i, column=1, sticky="ew", pady=4)
            self._vars[key] = (var, value_type, zero_ok)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(4,8))
        _btn(self, "💾  Save", self._save, "primary",
             font=("Georgia",10,"bold"), pady=8).pack(fill="x", padx=16, pady=(0,14))

    def _save(self):
        ss = load_server_settings()
        for key, (var, value_type, zero_ok) in self._vars.items():
            raw = var.get().strip()
            try:
                value = value_type(raw)
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError
                if value < 0 or (value == 0 and not zero_ok):
                    raise ValueError
            except (TypeError, ValueError):
                messagebox.showerror("Invalid value",
                    f"'{raw}' isn't a valid value for {key}.", parent=self)
                return
            ss[key] = value
        save_server_settings(ss)
        messagebox.showinfo("Saved", "Advanced settings saved.", parent=self)
        self.destroy()
