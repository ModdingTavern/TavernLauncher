"""Server settings (name/password/whitelist toggle/etc) window."""
import os
import shutil
import hashlib
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar, _fix_combobox_popdown_colors,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from server.core.data_store import (
    load_server_settings, save_server_settings,
    MAX_ACCOUNTS_PER_IP, SERVER_NAME_MAX_LEN, _is_valid_name, VALID_REGIONS,
)
from server.core.advanced_settings import AdvancedSettingsWindow

class ServerSettingsWindow(tk.Toplevel):
    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Server Settings")
        self.configure(bg=BG)
        self.geometry("560x400")  # placeholder; resized to fit content below
        self.resizable(False, False)
        _set_window_icon(self)
        self._on_save = on_save
        self._build()
        self.update_idletasks()
        self.geometry(f"560x{self.winfo_reqheight()}")
        _finish_dark_window(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚙  Server Settings", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        _btn(h, "Advanced", self._open_advanced,
             font=("Segoe UI",8), pady=4, padx=10).pack(side="right", padx=16)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        ss = load_server_settings()

        # ── Top row: Name + Max Players side by side ──────────────────────
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=16, pady=(10,0))
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=1)

        tk.Label(top, text="SERVER NAME", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).grid(row=0, column=0, sticky="w", padx=(4,0))
        tk.Label(top, text="MAX PLAYERS", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).grid(row=0, column=1, sticky="w", padx=(8,0))

        self.v_name = tk.StringVar(value=ss.get("name","My Tavern Server"))
        tk.Entry(top, textvariable=self.v_name, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).grid(row=1, column=0, sticky="ew", padx=(0,0))

        self.v_max_players = tk.StringVar(value=str(ss.get("max_players", 24)))
        tk.Entry(top, textvariable=self.v_max_players, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, width=6, justify="center").grid(row=1, column=1, sticky="ew", padx=(8,0))

        # ── Password row ──────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(10,0))
        pr = tk.Frame(self, bg=BG)
        pr.pack(fill="x", padx=16, pady=(6,0))
        pr.columnconfigure(0, weight=1)

        tk.Label(pr, text="PASSWORD", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).grid(row=0, column=0, sticky="w", padx=4)
        self._pw_hint = tk.StringVar(
            value="● Set" if ss.get("password_hash") else "○ None")
        tk.Label(pr, textvariable=self._pw_hint, bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).grid(row=0, column=1, sticky="e", padx=4)

        self.v_password = tk.StringVar()
        tk.Entry(pr, textvariable=self.v_password, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, show="●").grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0,0))

        pwbtns = tk.Frame(self, bg=BG)
        pwbtns.pack(anchor="w", padx=16, pady=(4,0))
        _btn(pwbtns, "Set Password", self._set_pw,
             font=("Segoe UI",9), pady=4, padx=10).pack(side="left")
        _btn(pwbtns, "Remove", self._clear_pw, "danger",
             font=("Segoe UI",9), pady=4, padx=10).pack(side="left", padx=(6,0))

        # ── Toggle options in a 2-col grid ────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(10,0))
        og = tk.Frame(self, bg=BG)
        og.pack(fill="x", padx=16, pady=(8,0))
        og.columnconfigure(0, weight=1)
        og.columnconfigure(1, weight=1)

        def _cb(parent, var, text, row, col):
            tk.Checkbutton(parent, variable=var, text=text,
                           bg=BG, fg=PARCH, selectcolor=SURF,
                           activebackground=BG, activeforeground=AMBER,
                           font=("Segoe UI",9), wraplength=200, justify="left",
                           anchor="nw").grid(row=row, column=col, sticky="nw",
                                            padx=(0 if col else 0, 8), pady=3)

        self.v_whitelist = tk.BooleanVar(value=ss.get("whitelist_enabled", False))
        _cb(og, self.v_whitelist, "Enable whitelist", 0, 0)

        self.v_ip_limit = tk.BooleanVar(value=ss.get("enforce_ip_limit", True))
        _cb(og, self.v_ip_limit, f"Limit to {MAX_ACCOUNTS_PER_IP} accounts per IP", 0, 1)

        self.v_community = tk.BooleanVar(value=ss.get("community_listed", False))
        _cb(og, self.v_community, "List on community server browser", 1, 0)

        region_frame = tk.Frame(og, bg=BG)
        region_frame.grid(row=1, column=1, sticky="nw", pady=3)
        tk.Label(region_frame, text="Region:", bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).pack(side="left", padx=(0,4))
        # "Unknown" is shown as a selectable option (stored lowercase to
        # match TavernLib's/the backend's own sentinel) so choosing "no
        # region" is a deliberate action here, same as any other setting --
        # not just whatever happens to be left over from before this field
        # existed. Only VALID_REGIONS' actual tags plus this are offered;
        # nothing else can be typed in, since the backend wouldn't accept
        # it anyway.
        region_display_values = ["Unknown"] + list(VALID_REGIONS)
        current_region = ss.get("region", "unknown")
        initial_display = current_region if current_region in VALID_REGIONS else "Unknown"
        self.v_region = tk.StringVar(value=initial_display)
        style = ttk.Style()
        style.configure("PM.Region.TCombobox", fieldbackground=SURF, background=SURF2,
                        foreground=PARCH, arrowcolor=AMBERDIM)
        region_combo = ttk.Combobox(region_frame, textvariable=self.v_region, values=region_display_values,
                     state="readonly", width=9, style="PM.Region.TCombobox",
                     font=("Consolas",9))
        region_combo.pack(side="left")
        _fix_combobox_popdown_colors(region_combo, SURF, PARCH, AMBERDIM, "#ffd080")

        # ── Hostname + Auto-reboot side by side ───────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(10,0))
        hr = tk.Frame(self, bg=BG)
        hr.pack(fill="x", padx=16, pady=(8,0))
        hr.columnconfigure(0, weight=1)
        hr.columnconfigure(1, weight=1)

        # Hostname (left)
        tk.Label(hr, text="PUBLIC HOSTNAME  (optional)", bg=BG, fg=AMBERDIM,
                 font=("Segoe UI",7,"bold")).grid(row=0, column=0, sticky="w", padx=4)
        self.v_hostname = tk.StringVar(value=ss.get("public_hostname",""))
        tk.Entry(hr, textvariable=self.v_hostname, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).grid(row=1, column=0, sticky="ew", padx=(0,8))
        tk.Label(hr, text="e.g. myserver.com", bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).grid(row=2, column=0, sticky="w", padx=4)

        # Auto-reboot (right)
        ar = tk.Frame(hr, bg=BG)
        ar.grid(row=0, column=1, rowspan=3, sticky="nsew", padx=(8,0))

        self.v_auto_reboot = tk.BooleanVar(value=ss.get("auto_reboot_enabled", False))
        tk.Checkbutton(ar, variable=self.v_auto_reboot, text="Auto-reboot",
                       bg=BG, fg=PARCH, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",9,"bold")).pack(anchor="w")

        self.v_reboot_mode = tk.StringVar(value=ss.get("auto_reboot_mode", "time"))

        t_row = tk.Frame(ar, bg=BG)
        t_row.pack(anchor="w", pady=(2,0))
        tk.Radiobutton(t_row, text="At:", variable=self.v_reboot_mode, value="time",
                       bg=BG, fg=PARCH, selectcolor=SURF,
                       activebackground=BG, font=("Segoe UI",9)).pack(side="left")
        self.v_reboot_hour = tk.StringVar(value=str(ss.get("auto_reboot_hour", 4)))
        tk.Entry(t_row, textvariable=self.v_reboot_hour, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=3, justify="center").pack(side="left", padx=(4,2))
        tk.Label(t_row, text=":", bg=BG, fg=MUTED,
                 font=("Segoe UI",9)).pack(side="left")
        self.v_reboot_minute = tk.StringVar(value=str(ss.get("auto_reboot_minute", 0)))
        tk.Entry(t_row, textvariable=self.v_reboot_minute, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=3, justify="center").pack(side="left", padx=(2,2))
        tk.Label(t_row, text="(HH:MM)", bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).pack(side="left", padx=(2,0))

        i_row = tk.Frame(ar, bg=BG)
        i_row.pack(anchor="w", pady=(2,0))
        tk.Radiobutton(i_row, text="Every:", variable=self.v_reboot_mode, value="interval",
                       bg=BG, fg=PARCH, selectcolor=SURF,
                       activebackground=BG, font=("Segoe UI",9)).pack(side="left")
        self.v_reboot_interval = tk.StringVar(value=str(ss.get("auto_reboot_interval", 6)))
        tk.Entry(i_row, textvariable=self.v_reboot_interval, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=4, width=3, justify="center").pack(side="left", padx=(4,2))
        tk.Label(i_row, text="hours", bg=BG, fg=MUTED,
                 font=("Segoe UI",9)).pack(side="left")

        # ── Save + Danger ─────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(12,6))
        _btn(self, "💾  Save Settings", self._save, "primary",
             font=("Georgia",11,"bold"), pady=10).pack(fill="x", padx=16, pady=(0,8))

        _btn(self, "🗑  Wipe Server Data", self._wipe_server, "danger",
             font=("Segoe UI",9), pady=7).pack(fill="x", padx=16, pady=(0,12))

    def _open_advanced(self):
        AdvancedSettingsWindow(self)

    def _wipe_server(self):
        target = os.path.join(
            os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming")),
            "A Township Tale", "Servers")
        if not messagebox.askyesno("Wipe Server Data",
                "This will permanently delete:\n\n"
                f"{target}\n\n"
                "That removes EVERY server hosted on this machine — all "
                "server data, player saves, and configuration for A "
                "Township Tale stored there. This cannot be undone.\n\n"
                "Are you sure you want to continue?", icon="warning", parent=self):
            return
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
                messagebox.showinfo("Wiped", "Server data has been removed.", parent=self)
            else:
                messagebox.showinfo("Nothing to do",
                    "That folder doesn't exist — there's nothing to wipe.", parent=self)
        except Exception as e:
            messagebox.showerror("Wipe failed", str(e), parent=self)

    def _set_pw(self):
        pw = self.v_password.get()
        if not pw:
            messagebox.showinfo("Nothing to set",
                "Type a password first — or use Remove Password to clear the "
                "current one instead.", parent=self)
            return
        ss = load_server_settings()
        ss["password_hash"] = hashlib.sha256(
            hashlib.sha256(pw.encode()).hexdigest().encode()
        ).hexdigest()
        save_server_settings(ss)
        self._pw_hint.set("● Password is set.")
        self.v_password.set("")
        messagebox.showinfo("Set", "Password updated.", parent=self)

    def _clear_pw(self):
        ss = load_server_settings()
        ss["password_hash"] = ""
        save_server_settings(ss)
        self._pw_hint.set("○ No password set.")
        messagebox.showinfo("Cleared", "Password removed.", parent=self)

    def _save(self):
        ss = load_server_settings()
        ss["auto_reboot_enabled"]  = self.v_auto_reboot.get()
        ss["auto_reboot_mode"]     = self.v_reboot_mode.get()
        try:    ss["auto_reboot_hour"]     = max(0, min(23, int(self.v_reboot_hour.get())))
        except: ss["auto_reboot_hour"]     = 4
        try:    ss["auto_reboot_minute"]   = max(0, min(59, int(self.v_reboot_minute.get())))
        except: ss["auto_reboot_minute"]   = 0
        try:    ss["auto_reboot_interval"] = max(1, int(self.v_reboot_interval.get()))
        except: ss["auto_reboot_interval"] = 6
        save_server_settings(ss)
        name = self.v_name.get().strip()
        if name:
            if len(name) > SERVER_NAME_MAX_LEN:
                messagebox.showerror("Name too long",
                    f"Server name can be at most {SERVER_NAME_MAX_LEN} characters.", parent=self)
                return
            if not _is_valid_name(name):
                messagebox.showerror("Invalid name",
                    "Server name can only contain letters, numbers, spaces, hyphens, and underscores.", parent=self)
                return
        ss = load_server_settings()
        ss["name"] = name or "My Tavern Server"
        ss["whitelist_enabled"] = self.v_whitelist.get()
        ss["enforce_ip_limit"] = self.v_ip_limit.get()
        ss["community_listed"] = self.v_community.get()
        selected_region = self.v_region.get().strip()
        ss["region"] = selected_region if selected_region in VALID_REGIONS else "unknown"
        ss["public_hostname"] = self.v_hostname.get().strip().lower()
        try: ss["max_players"] = max(1, int(self.v_max_players.get().strip()))
        except ValueError: ss["max_players"] = 24
        save_server_settings(ss)
        if self._on_save: self._on_save(ss["name"])
        messagebox.showinfo("Saved","Server settings saved.", parent=self)
        self.destroy()

