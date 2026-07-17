"""
The Modding Tavern — Server Launcher
"""

# Bump this with every release you publish to
# github.com/ModdingTavern/TavernLauncher/releases (tag it vX.Y.Z to match).
APP_VERSION = "1.7.1"

# The subfolder this app occupies inside the release zip
# (TavernLauncher-vX.Y.Z.zip contains /Client and /Server side by side) —
# used by the self-updater to know which part of the zip is "ours".
UPDATE_APP_FOLDER = "Server"

import os, subprocess, threading, time, io, json, socket, hashlib, secrets, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import base64, struct, urllib.request, shutil

_updater = None
try:
    import updater as _updater
except ImportError:
    pass

from tavern_common import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED,
    GREEN, RED, CYAN, MONO,
    _enable_dark_titlebar, _set_window_icon,
    _app_dir, _tavern_data_dir, _migrate_legacy_file,
    _is_valid_name,
    GameLogTailer,
    _divider, _section_label, _field, _btn, _mk_scrollbar, _FlashingButton,
    MELONLOADER_ZIP_URLS, TAVERNLIB_DOWNLOAD_URL, TAVERNLIB_FILENAME,
    MODS_META_FILENAME, YAMLDOTNET_FILENAME,
    _mods_meta_path, _load_mod_meta, _save_mod_meta,
    _get_redirect_location, _get_melonloader_latest_tag, _fetch_remote_fingerprint,
    _detect_exe_arch, _melonloader_installed, _tavernlib_installed,
    _yamldotnet_source_path, _yamldotnet_installed, _install_yamldotnet,
    _force_ipv4, _urlopen_hard_timeout, _download_with_progress,
    _melonloader_manual_zip_path, _install_melonloader,
    _tavernlib_manual_dll_path, _install_tavernlib,
    _melonloader_status, _tavernlib_status, _mods_need_attention,
    PATCH_SOURCE_FILENAME, PATCH_TARGET_SUBDIR, PATCH_TARGET_FILENAME,
    _patch_source_path, _patch_target_path, _sha256_file, _patch_is_applied, apply_patch,
    ModsWindow,
)

from server_auth import (
    load_cfg, save_cfg, load_server_settings, save_server_settings, CONFIG_FILE,
    MAX_ACCOUNTS_PER_IP, _load_users, _save_users, _load_bl, _save_bl, _load_wl, _save_wl,
    _users_lock, _read_live_player_status, start_auth_service, build_server_tokens,
)

# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════

GAME_LOG_PATH  = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Logs","logs","unity-log.csv")
PLAYERS_SAVE   = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Save","Players")
CONSOLE_TOKEN_FILE = os.path.join(_tavern_data_dir(),"console_token.txt")
_migrate_legacy_file(os.path.join(_app_dir(),"console_token.txt"), CONSOLE_TOKEN_FILE)
CONSOLE_PORT   = 1758
SERVER_NAME_MAX_LEN = 32

# Community server list backend — the small Flask app the server owner runs
# at home (see community_server.py). Registration (POST) and unregistration
# (DELETE) both go here; the same URL is used for GET on the client side.
COMMUNITY_API = "http://themoddingtavern.com:1763/servers"
COMMUNITY_HEARTBEAT_SECONDS = 120
DISCORD_URL   = "https://discord.gg/jNQUUDAYSj"

def _get_or_create_listing_token():
    """A stable secret identifying *this* server's row on the community list,
    so heartbeats/updates/unregisters always target the right listing even
    across restarts or a dynamic IP change."""
    ss = load_server_settings()
    tok = ss.get("community_listing_token")
    if not tok:
        tok = secrets.token_urlsafe(24)
        ss["community_listing_token"] = tok
        save_server_settings(ss)
    return tok

# ══════════════════════════════════════════════════════════════════════════════
#  CONSOLE CLIENT  (sends commands to the game's remote console on port 1758)
# ══════════════════════════════════════════════════════════════════════════════

class ConsoleClient:
    """Lightweight client for the game's binary-framed remote console."""
    def __init__(self):
        self._sock   = None
        self._lock   = threading.Lock()
        self._token  = ""
        self._connected = False

    def connect(self, host="127.0.0.1", port=CONSOLE_PORT):
        token_file = CONSOLE_TOKEN_FILE
        try:
            with open(token_file) as f: self._token = f.read().strip()
        except:
            return False, "console_token.txt not found"
        try:
            s = socket.socket()
            s.settimeout(4)
            s.connect((host, port))
            s.sendall(self._token.encode("utf-8"))
            resp = s.recv(64).decode("utf-8", errors="replace").strip()
            if resp != "ok":
                s.close()
                return False, f"Console rejected token: {resp}"
            self._sock = s
            self._connected = True
            return True, "ok"
        except Exception as e:
            return False, str(e)

    def send_command(self, cmd):
        if not self._connected or not self._sock:
            return None, "Not connected"
        try:
            with self._lock:
                payload = cmd.encode("utf-8")
                # 4-byte int32 length + 1-byte type (0 = ConsoleCommand)
                header  = struct.pack("<IB", len(payload), 0)
                self._sock.sendall(header + payload)
                # Response: 2-byte ushort length + 1-byte type + payload
                raw = self._sock.recv(65536)
                if len(raw) >= 3:
                    length = struct.unpack_from("<H", raw, 0)[0]
                    text   = raw[3:3+length].decode("utf-8", errors="replace")
                    return text, None
                return "", None
        except Exception as e:
            self._connected = False
            return None, str(e)

    def disconnect(self):
        self._connected = False
        if self._sock:
            try: self._sock.close()
            except: pass
            self._sock = None

_console = ConsoleClient()

def kick_player(username, ban=False):
    """Kick (and optionally ban) a live player via the game console."""
    ok, err = _console.connect()
    if not ok:
        return False, f"Console not available: {err}"
    if ban:
        out, err = _console.send_command(f'player ban "{username}"')
    else:
        out, err = _console.send_command(f'player kick "{username}"')
    _console.disconnect()
    if err: return False, err
    return True, out or "Done"

# ══════════════════════════════════════════════════════════════════════════════
#  HEADER BANNER  (background image behind the title bar, live-resized)
# ══════════════════════════════════════════════════════════════════════════════
# Needs Pillow — tkinter's own PhotoImage can't smoothly rescale on the fly,
# only a plain sample-based zoom/subsample. If Pillow or the embedded asset
# isn't available for any reason, the header just falls back to its old flat
# background color; this never blocks the app from running.
_HEADER_BANNER_IMG = None
try:
    from PIL import Image as _PILImage, ImageTk as _PILImageTk, ImageEnhance as _PILImageEnhance
    from banner_data import BANNER_B64 as _BANNER_B64
    _HEADER_BANNER_IMG = _PILImage.open(io.BytesIO(base64.b64decode(_BANNER_B64))).convert("RGB")
except Exception:
    _HEADER_BANNER_IMG = None

def _header_crop_box(src_w, src_h, target_w, target_h,
                      min_reveal=0.35, min_width=560, reveal_at_width=1400):
    """A centered crop box (source-image pixel coordinates) matching the
    target aspect ratio exactly, so scaling it up to (target_w, target_h)
    afterward never distorts anything — unlike stretching the whole image
    to an arbitrary width, which is what made it look "stretched super far"
    on a maximized window. At the smallest window width this shows a
    modestly zoomed-in slice near the center of the artwork; widening the
    window smoothly reveals more of it (rather than stretching the same
    content further) up to showing the whole image by reveal_at_width, and
    simply staying fully revealed (scaled larger) beyond that."""
    target_w = max(int(target_w), 1)
    target_h = max(int(target_h), 1)
    span = max(1, reveal_at_width - min_width)
    reveal = min_reveal + (1.0 - min_reveal) * min(1.0, max(0.0, (target_w - min_width) / span))
    crop_w = src_w * reveal
    crop_h = crop_w * target_h / target_w
    if crop_h > src_h:
        crop_h = src_h
        crop_w = crop_h * target_w / target_h
    crop_w = min(crop_w, src_w)
    cx, cy = src_w / 2.0, src_h / 2.0
    left   = max(0, int(round(cx - crop_w / 2.0)))
    top    = max(0, int(round(cy - crop_h / 2.0)))
    right  = min(src_w, int(round(cx + crop_w / 2.0)))
    bottom = min(src_h, int(round(cy + crop_h / 2.0)))
    return (left, top, right, bottom)

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _hint(parent, text, wraplength=380):
    tk.Label(parent, text=text, bg=BG, fg=MUTED, justify="left",
             wraplength=wraplength,
             font=("Segoe UI",8)).pack(anchor="w", padx=22, pady=(0,2))

def _mk_tree(parent, cols, widths, height=8):
    style = ttk.Style()
    style.configure("PM.Treeview", background=SURF, fieldbackground=SURF,
                    foreground=PARCH, rowheight=24)
    style.configure("PM.Treeview.Heading", background=SURF2, foreground=AMBER,
                    font=("Georgia",9,"bold"))
    style.map("PM.Treeview",
              background=[("selected",AMBERDIM)],
              foreground=[("selected","#ffd080")])
    f = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill="both", expand=True, padx=8, pady=(4,4))
    tree = ttk.Treeview(f, columns=cols, show="headings",
                        selectmode="browse", height=height, style="PM.Treeview")
    for col, w in zip(cols, widths):
        tree.heading(col, text=col.replace("_"," ").title())
        tree.column(col, width=w)
    sb = _mk_scrollbar(f, tree.yview)
    sb.pack(side="right", fill="y")
    tree.config(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True, padx=2, pady=2)
    return tree

# ══════════════════════════════════════════════════════════════════════════════
#  CONSOLE WINDOW
# ══════════════════════════════════════════════════════════════════════════════
# Same binary-framed remote console protocol as the standalone att_console.py
# script, embedded directly in the server app instead of needing a separate
# terminal. Keeps its own dedicated socket rather than reusing the shared
# `_console` ConsoleClient — that one is a one-shot connect/send/disconnect
# helper for kick_player, whereas this stays connected the whole time the
# window is open so it can stream unsolicited console output live.

class ConsoleWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Console")
        self.configure(bg=BG)
        self.geometry("640x480")
        self.resizable(True, True)
        _set_window_icon(self)
        self._sock      = None
        self._connected = False
        self._stop      = threading.Event()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _enable_dark_titlebar(self)
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
        entry.bind("<Return>", lambda e: self._send())
        entry.focus_set()
        _btn(cf, "Send", self._send, "primary",
             font=("Segoe UI",9,"bold"), pady=6, padx=14).pack(side="left", padx=(6,0))

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

        def worker():
            try:
                s = socket.socket()
                s.settimeout(4)
                s.connect(("127.0.0.1", CONSOLE_PORT))
                s.sendall(token.encode("utf-8"))
                resp = s.recv(64).decode("utf-8", errors="replace").strip()
                if resp != "ok":
                    self.after(0, lambda: self._status_var.set(f"Rejected: {resp}"))
                    return
                s.settimeout(None)
                self._sock = s
                self._connected = True
                self.after(0, lambda: self._status_var.set("Connected"))
                self.after(0, lambda: self._append("[Connected]\n", "ok"))
                self._receive_loop()
            except Exception as e:
                self.after(0, lambda err=str(e): self._status_var.set(f"Error: {err}"))
        threading.Thread(target=worker, daemon=True).start()

    def _receive_loop(self):
        buf, s = b"", self._sock
        while not self._stop.is_set():
            try:
                data = s.recv(65536)
                if not data:
                    self.after(0, lambda: self._on_disconnected("Server closed the connection."))
                    return
                buf += data
                # 2-byte ushort length + 1-byte type header, matching
                # ConsoleClient.send_command's response framing.
                while len(buf) >= 3:
                    length = struct.unpack_from("<H", buf, 0)[0]
                    if len(buf) < 3 + length:
                        break
                    payload = buf[3:3+length].decode("utf-8", errors="replace")
                    buf = buf[3+length:]
                    self.after(0, lambda p=payload: self._append(p))
            except OSError:
                if not self._stop.is_set():
                    self.after(0, lambda: self._on_disconnected("Connection lost."))
                return

    def _on_disconnected(self, msg):
        self._connected = False
        self._status_var.set("Disconnected")
        self._append(f"\n[{msg}]\n", "err")

    def _send(self):
        cmd = self.v_cmd.get().strip()
        if not cmd or not self._connected or not self._sock:
            return
        self.v_cmd.set("")
        self._append(f"> {cmd}\n", "cyan")
        try:
            payload = cmd.encode("utf-8")
            # 4-byte int32 length + 1-byte type (0 = ConsoleCommand)
            header = struct.pack("<IB", len(payload), 0)
            self._sock.sendall(header + payload)
        except Exception as e:
            self._append(f"[Send failed: {e}]\n", "err")

    def _on_close(self):
        self._stop.set()
        if self._sock:
            try: self._sock.close()
            except Exception: pass
        self.destroy()

# ══════════════════════════════════════════════════════════════════════════════
#  PLAYER MANAGER WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class PlayerManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Player Manager")
        self.configure(bg=BG)
        self.geometry("700x660")
        self.resizable(False, False)
        _set_window_icon(self)
        ttk.Style().theme_use("clam")
        self._build()
        self._refresh_players()
        self._refresh_bllist()
        self._refresh_wllist()
        _enable_dark_titlebar(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚑  Player Manager", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        nb = ttk.Notebook(self)
        style = ttk.Style()
        style.configure("PM.TNotebook", background=BG, borderwidth=0)
        style.configure("PM.TNotebook.Tab", background=SURF2, foreground=PARCH,
                        padding=(12,5), font=("Georgia",9))
        style.map("PM.TNotebook.Tab",
                  background=[("selected",AMBERDIM)],
                  foreground=[("selected","#ffd080")])
        nb.configure(style="PM.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        p_tab  = tk.Frame(nb, bg=BG)
        bl_tab = tk.Frame(nb, bg=BG)
        wl_tab = tk.Frame(nb, bg=BG)
        nb.add(p_tab,  text="  Players  ")
        nb.add(bl_tab, text="  Blacklist  ")
        nb.add(wl_tab, text="  Whitelist  ")
        self._build_players(p_tab)
        self._build_list_tab(bl_tab, "bl", ["username","user_id","ip"],
                             "Blocked players are rejected at login.")
        self._build_list_tab(wl_tab, "wl", ["username","ip"],
                             "When whitelist is enabled, only these entries may join.")

    # ── Players tab ────────────────────────────────────────────────────────────

    def _build_players(self, parent):
        self.p_tree = _mk_tree(parent, ("username","user_id"), [240,120], height=10)
        self.p_detail = tk.StringVar(value="Select a player.")
        df = tk.Frame(parent, bg=SURF, highlightbackground=BORDER,
                      highlightthickness=1, height=60)
        df.pack(fill="x", padx=8, pady=(0,4)); df.pack_propagate(False)
        tk.Label(df, textvariable=self.p_detail, bg=SURF, fg=PARCH,
                 font=MONO, justify="left", anchor="nw", wraplength=640
                 ).pack(fill="both", expand=True, padx=8, pady=8)
        self.p_tree.bind("<<TreeviewSelect>>", self._on_player_select)
        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,6))
        _btn(br, "⟳ Refresh",       self._refresh_players,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "✏ Change User ID", self._change_uid,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "♻ Reset User Token", self._reset_token,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "♻ Reset All Tokens", self._reset_all_tokens, "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "👢 Kick",          self._kick_player, "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "🚫 Kick & Ban",    self._kick_ban,    "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "📁 Save Folder",   self._open_saves,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="right")

    def _refresh_players(self):
        for r in self.p_tree.get_children(): self.p_tree.delete(r)
        for uname, entry in sorted(_load_users().items()):
            self.p_tree.insert("","end", iid=uname,
                               values=(uname, entry.get("user_id","?")))
        self.p_detail.set("Select a player.")

    def _on_player_select(self, _=None):
        sel = self.p_tree.selection()
        if not sel: return
        entry = _load_users().get(sel[0],{})
        self.p_detail.set(f"Username: {sel[0]}    User ID: {entry.get('user_id','?')}")

    def _selected_username(self):
        sel = self.p_tree.selection()
        if not sel:
            messagebox.showinfo("No selection","Select a player first.")
            return None
        return sel[0]

    def _kick_player(self):
        uname = self._selected_username()
        if not uname: return
        if not messagebox.askyesno("Kick Player",
                f"Kick '{uname}' from the server?\nThey can rejoin after."): return
        ok, msg = kick_player(uname, ban=False)
        messagebox.showinfo("Done" if ok else "Error", msg or "Sent kick command.")

    def _kick_ban(self):
        uname = self._selected_username()
        if not uname: return
        if not messagebox.askyesno("Kick & Ban",
                f"Kick and ban '{uname}'?\nThis will also add them to the blacklist."): return
        # Add to blacklist
        bl = _load_bl()
        if uname.lower() not in [u.lower() for u in bl["usernames"]]:
            bl["usernames"].append(uname)
            _save_bl(bl)
        # Kick live session
        ok, msg = kick_player(uname, ban=True)
        detail = msg or "Sent ban command."
        messagebox.showinfo("Banned", f"'{uname}' added to blacklist.\n{detail}")

    def _change_uid(self):
        uname = self._selected_username()
        if not uname: return
        current = _load_users().get(uname,{}).get("user_id","")
        prompt = tk.Toplevel(self)
        prompt.title("Change User ID"); prompt.configure(bg=BG)
        prompt.resizable(False,False); prompt.geometry("380x230")
        tk.Label(prompt, text=f"New User ID for '{uname}'",
                 bg=BG, fg=PARCH, font=("Georgia",11,"bold")).pack(pady=(16,4))
        tk.Label(prompt, text="Maps this username to a different save file.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9)).pack()
        var = tk.StringVar(value=str(current))
        ef = tk.Frame(prompt, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        ef.pack(padx=30, pady=10, fill="x")
        tk.Entry(ef, textvariable=var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, justify="center").pack(fill="x")
        def confirm():
            try: new_id = int(var.get().strip())
            except ValueError: messagebox.showerror("Invalid","Must be a number."); return
            with _users_lock:
                u = _load_users()
                if uname in u: u[uname]["user_id"] = new_id; _save_users(u)
            prompt.destroy(); self._refresh_players()
            messagebox.showinfo("Done", f"'{uname}' → ID {new_id}.")
        _btn(prompt, "Save", confirm, "primary",
             font=("Georgia",10,"bold"), pady=8).pack(fill="x", padx=30, pady=(0,14))
        _enable_dark_titlebar(prompt)

    def _reset_token(self):
        uname = self._selected_username()
        if not uname: return
        if not messagebox.askyesno("Reset User Token",
                f"Reset the token for '{uname}'?\n\n"
                "Their token will be cleared. The next time anyone connects using "
                "this username, whatever token their launcher sends will be "
                "automatically accepted and saved as the new token — this is how "
                "a player recovers from a lost token file."):
            return
        with _users_lock:
            u = _load_users()
            if uname in u:
                u[uname]["token"] = ""
                _save_users(u)
        self._refresh_players()
        messagebox.showinfo("Token Reset",
            f"'{uname}'s token has been cleared.\n"
            "The next login for this username will be accepted automatically.")

    def _reset_all_tokens(self):
        with _users_lock:
            u = _load_users()
        count = len(u)
        if count == 0:
            messagebox.showinfo("No players", "There are no known users to reset.")
            return
        if not messagebox.askyesno("Reset All Tokens",
                f"Reset the token for ALL {count} known user(s)?\n\n"
                "Every username's token will be cleared. The next time anyone "
                "connects with any of these usernames, whatever token their "
                "launcher sends will be automatically accepted and saved as the "
                "new token — useful right after resetting the server, so "
                "everyone can reconnect cleanly.\n\n"
                "This cannot be undone."):
            return
        with _users_lock:
            u = _load_users()
            for entry in u.values():
                entry["token"] = ""
            _save_users(u)
        self._refresh_players()
        messagebox.showinfo("All Tokens Reset",
            f"Cleared tokens for {count} user(s).\n"
            "The next login for each username will be accepted automatically.")

    def _open_saves(self):
        try: os.makedirs(PLAYERS_SAVE, exist_ok=True); os.startfile(PLAYERS_SAVE)
        except Exception as e: messagebox.showerror("Error", str(e))

    # ── Generic list tab ───────────────────────────────────────────────────────

    def _build_list_tab(self, parent, key, kinds, hint_text):
        _section_label(parent, ("BLOCKED" if key=="bl" else "ALLOWED") +
                       " — " + " / ".join(k.upper() for k in kinds))
        tree = _mk_tree(parent, ("type","value"), [110,320], height=10)
        setattr(self, f"_{key}_tree", tree)
        _hint(parent, hint_text)
        ar = tk.Frame(parent, bg=BG)
        ar.pack(fill="x", padx=8, pady=(0,4))
        type_var = tk.StringVar(value=kinds[0])
        style = ttk.Style()
        style.configure("PM.TCombobox", fieldbackground=SURF, background=SURF2,
                        foreground=PARCH, arrowcolor=AMBERDIM)
        cb = ttk.Combobox(ar, textvariable=type_var, values=kinds,
                          state="readonly", width=12, style="PM.TCombobox")
        cb.pack(side="left", padx=(0,6))
        val_var = tk.StringVar()
        vf = tk.Frame(ar, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        vf.pack(side="left", fill="x", expand=True, padx=(0,6))
        tk.Entry(vf, textvariable=val_var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=MONO, bd=5).pack(fill="x")
        def add():
            kind = type_var.get(); value = val_var.get().strip()
            if not value: return
            if key=="bl":
                bl = _load_bl()
                if kind=="username" and value.lower() not in [u.lower() for u in bl["usernames"]]:
                    bl["usernames"].append(value)
                elif kind=="user_id":
                    try:
                        uid = int(value)
                        if uid not in bl["user_ids"]: bl["user_ids"].append(uid)
                    except: return
                elif kind=="ip" and value not in bl["ips"]:
                    bl["ips"].append(value)
                _save_bl(bl)
            else:
                wl = _load_wl()
                if kind=="username" and value.lower() not in [u.lower() for u in wl["usernames"]]:
                    wl["usernames"].append(value)
                elif kind=="ip" and value not in wl["ips"]:
                    wl["ips"].append(value)
                _save_wl(wl)
            val_var.set("")
            getattr(self, f"_refresh_{key}list")()
        def remove():
            sel = tree.selection()
            if not sel: return
            kind, value = tree.item(sel[0],"values")
            if key=="bl":
                bl = _load_bl()
                if kind=="username": bl["usernames"]=[u for u in bl["usernames"] if u.lower()!=str(value).lower()]
                elif kind=="user_id": bl["user_ids"]=[u for u in bl["user_ids"] if str(u)!=str(value)]
                elif kind=="ip": bl["ips"]=[i for i in bl["ips"] if i!=value]
                _save_bl(bl)
            else:
                wl = _load_wl()
                if kind=="username": wl["usernames"]=[u for u in wl["usernames"] if u.lower()!=str(value).lower()]
                elif kind=="ip": wl["ips"]=[i for i in wl["ips"] if i!=value]
                _save_wl(wl)
            getattr(self, f"_refresh_{key}list")()
        _btn(ar, "+ Add",    add,    font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,6))
        _btn(br, "✕ Remove", remove, "danger", font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "⟳ Refresh", getattr(self, f"_refresh_{key}list"),
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)

    def _refresh_bllist(self):
        for r in self._bl_tree.get_children(): self._bl_tree.delete(r)
        bl = _load_bl()
        for u   in bl.get("usernames",[]): self._bl_tree.insert("","end",values=("username",u))
        for uid in bl.get("user_ids", []): self._bl_tree.insert("","end",values=("user_id",uid))
        for ip  in bl.get("ips",      []): self._bl_tree.insert("","end",values=("ip",ip))

    def _refresh_wllist(self):
        for r in self._wl_tree.get_children(): self._wl_tree.delete(r)
        wl = _load_wl()
        for u  in wl.get("usernames",[]): self._wl_tree.insert("","end",values=("username",u))
        for ip in wl.get("ips",      []): self._wl_tree.insert("","end",values=("ip",ip))


# ══════════════════════════════════════════════════════════════════════════════
#  SERVER SETTINGS WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class ServerSettingsWindow(tk.Toplevel):
    def __init__(self, parent, on_save=None):
        super().__init__(parent)
        self.title("Server Settings")
        self.configure(bg=BG)
        self.geometry("440x430")  # placeholder; resized to fit content below
        self.resizable(False, False)
        self._on_save = on_save
        self._build()
        # Fixed-size windows don't grow to fit their content automatically —
        # size to whatever the fully-built layout actually needs, so adding
        # a field later never silently clips the Save button off the bottom.
        self.update_idletasks()
        self.geometry(f"440x{self.winfo_reqheight()}")
        _enable_dark_titlebar(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚙  Server Settings", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        ss = load_server_settings()
        _section_label(self, "SERVER NAME")
        nf = _field(self)
        self.v_name = tk.StringVar(value=ss.get("name","My Tavern Server"))
        tk.Entry(nf, textvariable=self.v_name, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        _hint(self, f"Shown to players who check your server. Max {SERVER_NAME_MAX_LEN} characters. "
                    "Letters, numbers, spaces, hyphens, and underscores only.")
        _divider(self)
        _section_label(self, "MAX PLAYERS")
        mf = _field(self)
        self.v_max_players = tk.StringVar(value=str(ss.get("max_players", 24)))
        tk.Entry(mf, textvariable=self.v_max_players, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        _hint(self, "Shown on the community list as a player-count cap.")
        _divider(self)
        _section_label(self, "PASSWORD  (leave blank to keep current / remove)")
        pf = _field(self)
        self.v_password = tk.StringVar()
        tk.Entry(pf, textvariable=self.v_password, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, show="●").pack(fill="x")
        self._pw_hint = tk.StringVar(
            value="● Password is set." if ss.get("password_hash") else "○ No password set.")
        tk.Label(self, textvariable=self._pw_hint, bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).pack(anchor="w", padx=22)
        _btn(self, "✕ Remove Password", self._clear_pw, "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(anchor="w", padx=22, pady=(4,0))
        _hint(self, "Players are prompted for this before connecting.")
        _section_label(self, "WHITELIST")
        wlf = tk.Frame(self, bg=BG)
        wlf.pack(anchor="w", padx=22, pady=(0,6))
        self.v_whitelist = tk.BooleanVar(value=ss.get("whitelist_enabled",False))
        tk.Checkbutton(wlf, variable=self.v_whitelist,
                       text="Enable whitelist (only listed players/IPs may join)",
                       bg=BG, fg=PARCH, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",9)).pack(side="left")
        _section_label(self, "ANTI-ABUSE")
        ipf = tk.Frame(self, bg=BG)
        ipf.pack(anchor="w", padx=22, pady=(0,2))
        self.v_ip_limit = tk.BooleanVar(value=ss.get("enforce_ip_limit", True))
        tk.Checkbutton(ipf, variable=self.v_ip_limit,
                       text=f"Limit new accounts to {MAX_ACCOUNTS_PER_IP} per IP address",
                       bg=BG, fg=PARCH, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",9)).pack(side="left")
        _hint(self, "Turn off if legitimate players share one address (e.g. NAT/shared "
                     "connections) and are getting blocked from creating accounts.")
        _section_label(self, "COMMUNITY SERVER LIST")
        clf = tk.Frame(self, bg=BG)
        clf.pack(anchor="w", padx=22, pady=(0,2))
        self.v_community = tk.BooleanVar(value=ss.get("community_listed", False))
        tk.Checkbutton(clf, variable=self.v_community,
                       text="Add this server to the global community list?",
                       bg=BG, fg=PARCH, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",9)).pack(side="left")
        _hint(self, "Shares this server's name, IP, and port publicly so it shows "
                     "up in every player's Community Servers list while it's online.")

        _section_label(self, "PUBLIC HOSTNAME  (optional)")
        hf = _field(self)
        self.v_hostname = tk.StringVar(value=ss.get("public_hostname",""))
        tk.Entry(hf, textvariable=self.v_hostname, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        self._hostname_hint = tk.StringVar(value=
            "e.g. myserver.com — used instead of your raw IP once it resolves here.")
        tk.Label(self, textvariable=self._hostname_hint, bg=BG, fg=MUTED,
                 justify="left", wraplength=380, font=("Segoe UI",8)
        ).pack(anchor="w", padx=22, pady=(0,3))
        _hint(self, "Point an A record at this connection's public IP first — the "
                     "community list only uses it once that resolution actually matches.")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10,6))
        _btn(self, "💾  Save Settings", self._save, "primary",
             font=("Georgia",11,"bold"), pady=12).pack(fill="x", padx=20, pady=(0,16))

        _section_label(self, "DANGER ZONE")
        _btn(self, "🗑  Wipe Server Data", self._wipe_server, "danger",
             font=("Segoe UI",10,"bold"), pady=10).pack(fill="x", padx=20, pady=(0,4))
        _hint(self, "Deletes %AppData%\\Roaming\\A Township Tale\\Servers entirely — "
                     "every server hosted on this machine, not just this one. "
                     "Cannot be undone.")

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
                "Are you sure you want to continue?", icon="warning"):
            return
        try:
            if os.path.isdir(target):
                shutil.rmtree(target)
                messagebox.showinfo("Wiped", "Server data has been removed.")
            else:
                messagebox.showinfo("Nothing to do",
                    "That folder doesn't exist — there's nothing to wipe.")
        except Exception as e:
            messagebox.showerror("Wipe failed", str(e))

    def _clear_pw(self):
        ss = load_server_settings()
        ss["password_hash"] = ""
        save_server_settings(ss)
        self._pw_hint.set("○ No password set.")
        messagebox.showinfo("Cleared", "Password removed.")

    def _save(self):
        name = self.v_name.get().strip()
        if name:
            if len(name) > SERVER_NAME_MAX_LEN:
                messagebox.showerror("Name too long",
                    f"Server name can be at most {SERVER_NAME_MAX_LEN} characters.")
                return
            if not _is_valid_name(name):
                messagebox.showerror("Invalid name",
                    "Server name can only contain letters, numbers, spaces, hyphens, and underscores.")
                return
        ss = load_server_settings()
        ss["name"] = name or "My Tavern Server"
        ss["whitelist_enabled"] = self.v_whitelist.get()
        ss["enforce_ip_limit"] = self.v_ip_limit.get()
        ss["community_listed"] = self.v_community.get()
        ss["public_hostname"] = self.v_hostname.get().strip().lower()
        try: ss["max_players"] = max(1, int(self.v_max_players.get().strip()))
        except ValueError: ss["max_players"] = 24
        pw = self.v_password.get()
        if pw:
            ss["password_hash"] = hashlib.sha256(
                hashlib.sha256(pw.encode()).hexdigest().encode()
            ).hexdigest()
            self._pw_hint.set("● Password is set.")
            self.v_password.set("")
        save_server_settings(ss)
        if self._on_save: self._on_save(ss["name"])
        messagebox.showinfo("Saved","Server settings saved.")
        self.destroy()


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LAUNCHER
# ══════════════════════════════════════════════════════════════════════════════

class ServerLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TavernLauncher - Server")
        self.configure(bg=BG)
        # Same reasoning as the client launcher — this window's log is the
        # thing worth resizing for, so let the whole window resize.
        self.resizable(True, True)
        self.geometry("560x760")  # placeholder; resized to fit content below
        _set_window_icon(self)
        ttk.Style().theme_use("clam")
        self._proc     = None
        self._auth_on  = False
        self._tailer   = None
        self._mgr_win  = None
        self._mods_win = None
        self._sett_win = None
        self._console_win = None
        self._community_registered = False
        self._community_stop = threading.Event()
        self._community_thread = None
        self._exe_check_job   = None
        self._build_ui()
        self._load()
        self._start_log_tailer()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        # Same reasoning as the client launcher — fit_w used to be a
        # hardcoded guess that went stale every time a row gained another
        # button/checkbox; measuring it the same way fit_h already was is
        # what actually keeps this correct going forward.
        self.update_idletasks()
        fit_w = max(560, self.winfo_reqwidth())
        fit_h = self.winfo_reqheight()
        self.geometry(f"{fit_w}x{fit_h}")
        self.minsize(fit_w, fit_h)
        _enable_dark_titlebar(self)

    def _build_ui(self):
        self._header()
        _section_label(self, "GAME EXECUTABLE")
        pf = _field(self)
        self.v_exe = tk.StringVar()
        self.v_exe.trace_add("write", self._on_exe_changed)
        tk.Entry(pf, textvariable=self.v_exe, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True)
        _btn(pf, "Browse", self._browse, font=("Segoe UI",9),
             padx=10, pady=6).pack(side="right")
        _hint(self, "Path to 'A Township Tale.exe'")
        _section_label(self, "GAME PORT")
        pf2 = _field(self)
        self.v_port = tk.StringVar(value="1757")
        tk.Entry(pf2, textvariable=self.v_port, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6).pack(fill="x")
        _hint(self, "Forward 1757–1762 (UDP+TCP) for remote players.")
        _divider(self)
        self._sv_name_var = tk.StringVar(value="—")
        nf = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        nf.pack(fill="x", padx=20, pady=(0,4))
        tk.Label(nf, text="SERVER NAME", bg=SURF, fg=MUTED,
                 font=("Segoe UI",8,"bold")).pack(side="left", padx=10, pady=6)
        tk.Label(nf, textvariable=self._sv_name_var, bg=SURF, fg=AMBER,
                 font=("Georgia",11,"bold")).pack(side="left", padx=4, pady=6)
        tr = tk.Frame(self, bg=BG)
        tr.pack(fill="x", padx=20, pady=(4,4))
        _btn(tr, "⚙ Settings", self._open_settings, font=("Segoe UI",9),
             pady=7, padx=12).pack(side="left")
        _btn(tr, "👤 Players",  self._open_manager,  font=("Segoe UI",9),
             pady=7, padx=12).pack(side="left", padx=6)
        _btn(tr, "🖥 Console",  self._open_console,  font=("Segoe UI",9),
             pady=7, padx=12).pack(side="left", padx=6)
        self._patch_btn = _btn(tr, "🩹 Patch", self._on_patch_click,
                               font=("Segoe UI",9), pady=7, padx=12)
        self._patch_btn.pack(side="left")
        self._mods_btn = _btn(tr, "🧪 Mods", self._open_mods,
                              font=("Segoe UI",9), pady=7, padx=12)
        self._mods_btn.pack(side="left", padx=6)
        self._mods_flasher  = _FlashingButton(self, self._mods_btn,
            (SURF2, AMBER), ("#5a3d0e","#ffd080"), (SURF2, PARCH))
        self._patch_flasher = _FlashingButton(self, self._patch_btn,
            ("#1a3d2a","#80d8aa"), ("#0d2419","#50aa7a"), (SURF2, PARCH))
        _btn(tr, "📁 Saves",    self._open_saves,    font=("Segoe UI",9),
             pady=7, padx=12).pack(side="right")
        _divider(self)
        sf = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        sf.pack(fill="x", padx=20, pady=(0,6))
        self._dot = tk.Canvas(sf, width=10, height=10, bg=SURF, highlightthickness=0)
        self._dot.pack(side="left", padx=(10,6), pady=8)
        self._dot.create_oval(1,1,9,9, fill=MUTED, outline="", tags="dot")
        self._status_var = tk.StringVar(value="Offline")
        tk.Label(sf, textvariable=self._status_var, bg=SURF, fg=MUTED,
                 font=("Segoe UI",10)).pack(side="left")
        self._pid_var = tk.StringVar()
        tk.Label(sf, textvariable=self._pid_var, bg=SURF, fg=AMBERDIM,
                 font=MONO).pack(side="right", padx=10)
        bf = tk.Frame(self, bg=BG)
        bf.pack(fill="x", padx=20, pady=(0,6))
        self._btn_start = _btn(bf, "⚔   Open Server", self._start, "success",
                               font=("Georgia",12,"bold"), pady=12)
        self._btn_start.pack(fill="x", pady=(0,6))
        self._btn_stop = _btn(bf, "✕   Close Server", self._stop, "danger",
                              font=("Georgia",12,"bold"), pady=12)
        self._btn_stop.pack(fill="x")
        self._btn_stop.config(state="disabled")
        _section_label(self, "SERVER LOG")
        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,8))
        lb = tk.Frame(lf, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True)
        self.log = tk.Text(lb, bg=SURF, fg="#b09a78", font=MONO,
                           relief="flat", bd=0, state="disabled", height=9,
                           wrap="none")
        sb = _mk_scrollbar(lb, self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        for t,c in [("ok",GREEN),("warn",AMBER),("err",RED),
                    ("cyan",CYAN),("dim",MUTED),("error",RED),
                    ("info","#b09a78"),("debug",MUTED)]:
            self.log.tag_config(t, foreground=c)
        self._log_status = tk.StringVar(value="Awaiting server…")
        tk.Label(lf, textvariable=self._log_status, bg=BG, fg=MUTED,
                 font=("Segoe UI",8)).pack(anchor="w", pady=(3,0))

        # ── Enhanced Debugging / Show MelonLoader toggles ────────────────────
        df = tk.Frame(self, bg=BG)
        df.pack(side="bottom", fill="x", padx=14, pady=(0,6))
        self.v_debug_helper = tk.BooleanVar(value=False)
        tk.Checkbutton(df, text="Enhanced Debugging", variable=self.v_debug_helper,
                       command=self._save, bg=BG, fg=MUTED, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",8)).pack(side="left")
        self.v_show_melonloader = tk.BooleanVar(value=False)
        tk.Checkbutton(df, text="Show MelonLoader", variable=self.v_show_melonloader,
                       command=self._save, bg=BG, fg=MUTED, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",8)).pack(side="left", padx=(14,0))
        self.v_show_game = tk.BooleanVar(value=False)
        tk.Checkbutton(df, text="Show Game", variable=self.v_show_game,
                       command=self._save, bg=BG, fg=MUTED, selectcolor=SURF,
                       activebackground=BG, activeforeground=AMBER,
                       font=("Segoe UI",8)).pack(side="left", padx=(14,0))
        _btn(df, "🗑 Wipe Cache", self._wipe_cache,
             font=("Segoe UI",7), pady=2, padx=6).pack(side="right")

    def _header(self):
        h = tk.Frame(self, bg=SURF, height=64)
        h.pack(fill="x"); h.pack_propagate(False)

        canvas = tk.Canvas(h, bg=SURF, highlightthickness=0, bd=0)
        canvas.pack(fill="both", expand=True)
        self._header_canvas   = canvas
        self._header_bg_photo = None
        self._header_bg_item  = None
        if _HEADER_BANNER_IMG is not None:
            self._header_bg_item = canvas.create_image(0, 0, anchor="nw")

        canvas.create_rectangle(0, 0, 4, 64, fill=AMBER, width=0)
        canvas.create_text(18, 32, text="⚒", fill=AMBER, font=("Georgia",22), anchor="w")
        canvas.create_text(66, 21, text="The Modding Tavern", fill=AMBER,
                           font=("Georgia",14,"bold"), anchor="w")
        canvas.create_text(66, 42, text=f"Server Launcher  ·  v{APP_VERSION}", fill=AMBER,
                           font=("Segoe UI",9), anchor="w")

        self._discord_btn = tk.Button(canvas, text="💬 Discord", bg=SURF2, fg=AMBER,
                                      activebackground=AMBERDIM, activeforeground="#ffd080",
                                      relief="flat", bd=0, cursor="hand2",
                                      font=("Segoe UI",9,"bold"), padx=10, pady=4,
                                      command=lambda: webbrowser.open(DISCORD_URL))
        self._discord_btn_item = canvas.create_window(0, 32, anchor="e", window=self._discord_btn)

        canvas.bind("<Configure>", self._on_header_resize)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _on_header_resize(self, event):
        """Rescales the banner to fill the header exactly, and keeps the
        Discord badge right-aligned — a Canvas doesn't auto-stretch or
        reposition its own children, so this has to be done by hand."""
        w, hgt = event.width, event.height
        if w < 2 or hgt < 2:
            return
        if _HEADER_BANNER_IMG is not None and self._header_bg_item is not None:
            try:
                box = _header_crop_box(_HEADER_BANNER_IMG.width, _HEADER_BANNER_IMG.height, w, hgt)
                resized = _HEADER_BANNER_IMG.crop(box).resize((w, hgt), _PILImage.LANCZOS)
                # Uniform darken so the amber/parchment text stays legible
                # regardless of which part of the artwork ends up behind it.
                resized = _PILImageEnhance.Brightness(resized).enhance(0.5)
                photo = _PILImageTk.PhotoImage(resized)
                self._header_canvas.itemconfig(self._header_bg_item, image=photo)
                self._header_bg_photo = photo  # keep a reference or Tk drops it
            except Exception:
                pass
        self._header_canvas.coords(self._discord_btn_item, w - 14, hgt // 2)

    def _load(self):
        cfg = load_cfg()
        self.v_exe.set(cfg.get("server_exe",""))
        self.v_port.set(cfg.get("server_port","1757"))
        self.v_debug_helper.set(cfg.get("debug_helper", False))
        self.v_show_melonloader.set(cfg.get("show_melonloader", False))
        self.v_show_game.set(cfg.get("show_game", False))
        ss = load_server_settings()
        self._sv_name_var.set(ss.get("name","—"))
        self._print("Tavern server ready.", "ok")
        self._print("Set game exe and click Open Server.", "dim")
        # Immediate check at startup — the trace-driven debounce from
        # v_exe.set above will also fire, but 800ms later; this makes the
        # Patch/Mods button states correct from the very first frame.
        self._refresh_tool_states()
        # Update check runs a couple seconds after startup, off the UI
        # thread, so it never delays the window actually appearing.
        self.after(2000, self._check_for_launcher_update)

    def _check_for_launcher_update(self):
        if _updater is None:
            return
        def worker():
            result = _updater.check_for_update(APP_VERSION)
            if result:
                tag, url = result
                self.after(0, lambda: self._prompt_launcher_update(tag, url))
        threading.Thread(target=worker, daemon=True).start()

    def _prompt_launcher_update(self, tag, url):
        if not messagebox.askyesno("Update Available",
                f"A new version is available: {tag} (you have {APP_VERSION}).\n\n"
                "Update now? The launcher will restart automatically."):
            return
        self._print(f"Updating to {tag}…", "warn")
        def worker():
            try:
                _updater.download_and_apply_update(url, UPDATE_APP_FOLDER,
                    on_progress=lambda m: self.after(0, lambda: self._print(m, "warn")))
                # download_and_apply_update relaunches and calls os._exit()
                # on success — if we get here at all, something went wrong
                # after the point of no return.
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Update failed",
                    f"Couldn't apply the update:\n{e}\n\n"
                    "The current version is unaffected — nothing was replaced."))
        threading.Thread(target=worker, daemon=True).start()

    def _save(self):
        save_cfg({**load_cfg(), "server_exe": self.v_exe.get(),
                  "server_port": self.v_port.get(),
                  "debug_helper": self.v_debug_helper.get(),
                  "show_melonloader": self.v_show_melonloader.get(),
                  "show_game": self.v_show_game.get()})

    def _wipe_cache(self):
        if not messagebox.askyesno("Wipe Launcher Cache",
                "This will delete this launcher's saved settings file:\n\n"
                f"{CONFIG_FILE}\n\n"
                "That includes your saved game path, port, and toggle "
                "preferences — giving you a completely fresh, unconfigured "
                "launcher next time it starts.\n\n"
                "Your player data, server settings, tokens, patch, and "
                "installed mods are NOT affected — only this launcher's own "
                "remembered fields.\n\n"
                "This cannot be undone. Continue?", icon="warning"):
            return
        try:
            if os.path.isfile(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            messagebox.showinfo("Cache Wiped",
                "Launcher cache cleared. The app will now close — "
                "reopen it for a fresh start.")
            self._on_close()
        except Exception as e:
            messagebox.showerror("Wipe failed", str(e))

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select A Township Tale.exe",
            filetypes=[("Executable","*.exe"),("All","*.*")])
        if p: self.v_exe.set(p.replace("/","\\")); self._save()

    def _open_settings(self):
        if self._sett_win and self._sett_win.winfo_exists():
            self._sett_win.lift(); return
        def on_save(name):
            self._sv_name_var.set(name)
            self._apply_community_listing_state(
                bool(self._proc and self._proc.poll() is None))
        self._sett_win = ServerSettingsWindow(self, on_save)

    def _open_manager(self):
        if self._mgr_win and self._mgr_win.winfo_exists():
            self._mgr_win.lift(); return
        self._mgr_win = PlayerManagerWindow(self)

    def _open_console(self):
        if self._console_win and self._console_win.winfo_exists():
            self._console_win.lift(); return
        self._console_win = ConsoleWindow(self)

    def _open_mods(self):
        exe = self.v_exe.get().strip()
        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Game not found",
                "Please set the path to 'A Township Tale.exe' above first.")
            return
        if self._mods_win and self._mods_win.winfo_exists():
            self._mods_win.lift(); return
        self._mods_win = ModsWindow(self, exe, on_status_change=self._refresh_mods_alert)

    # ── Patch / Mods buttons (same mechanism as the client launcher) ────────

    def _on_exe_changed(self, *_):
        if self._exe_check_job:
            try: self.after_cancel(self._exe_check_job)
            except Exception: pass
        self._exe_check_job = self.after(800, self._refresh_tool_states)

    def _refresh_tool_states(self):
        """Enables/disables the Patch and Mods buttons based on whether a
        valid game exe is selected, then separately refreshes each button's
        own flashing-alert condition. State is only ever touched here, and
        the animation loops below only ever touch bg/fg — kept deliberately
        separate so neither path can clobber the other."""
        exe = self.v_exe.get().strip()
        valid = bool(exe and os.path.isfile(exe))
        state = "normal" if valid else "disabled"
        try: self._patch_btn.config(state=state)
        except Exception: pass
        try: self._mods_btn.config(state=state)
        except Exception: pass
        self._refresh_mods_alert()
        self._refresh_patch_alert(exe)

    def _refresh_mods_alert(self):
        exe = self.v_exe.get().strip()
        if not exe or not os.path.isfile(exe):
            self._set_mods_alert(False)
            return
        game_dir = os.path.dirname(exe)
        def worker():
            try:
                need = _mods_need_attention(game_dir)
            except Exception:
                need = False
            self.after(0, lambda: self._set_mods_alert(need))
        threading.Thread(target=worker, daemon=True).start()

    def _set_mods_alert(self, needed):
        if needed: self._mods_flasher.start()
        else:      self._mods_flasher.stop()

    def _refresh_patch_alert(self, exe):
        """Flash the Patch button only while the patch DLL is actually
        present AND not already applied — a real on-disk check, so it
        correctly reflects reality even if the client launcher already did
        this for the same game (both point at the same target files)."""
        if not exe or not os.path.isfile(exe):
            self._patch_flasher.stop()
            return
        def worker():
            try:
                need = os.path.isfile(_patch_source_path()) and not _patch_is_applied(exe)
            except Exception:
                need = False
            self.after(0, lambda: self._patch_flasher.start() if need else self._patch_flasher.stop())
        threading.Thread(target=worker, daemon=True).start()

    def _on_patch_click(self):
        exe = self.v_exe.get().strip()
        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Game not found",
                "Please set the path to 'A Township Tale.exe' above first.")
            return

        def worker():
            try:
                apply_patch(exe)
                self.after(0, lambda: (
                    messagebox.showinfo("Patch applied",
                        "Root.Township.dll has been replaced with the Tavern patch."),
                    self._refresh_patch_alert(exe)))
            except RuntimeError as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Patch failed", err))
        threading.Thread(target=worker, daemon=True).start()

    def _open_saves(self):
        try: os.makedirs(PLAYERS_SAVE, exist_ok=True); os.startfile(PLAYERS_SAVE)
        except Exception as e: messagebox.showerror("Error", str(e))

    def _print(self, msg, tag=""):
        def _do():
            self.log.config(state="normal")
            self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n", tag)
            self.log.see("end"); self.log.config(state="disabled")
        self.after(0, _do)

    def _start_log_tailer(self):
        TAG = {"error":"err","Error":"err","warn":"warn","Warn":"warn",
               "info":"info","Info":"info","debug":"debug","Debug":"debug"}
        def on_line(ts, lv, lg, msg):
            tag = TAG.get(lv,"info")
            short = lg.split(".")[-1] if lg else ""
            pre   = f"[{ts}]" + (f" [{short}]" if short else "")
            self.after(0, lambda: self._append_log(f"{pre} {msg}", tag))
        def on_status(s):
            if s == "watching":
                self.after(0, lambda: self._log_status.set("Watching server log…"))
        self._tailer = GameLogTailer(GAME_LOG_PATH, on_line, on_status)
        self._tailer.start()

    def _append_log(self, line, tag):
        self.log.config(state="normal")
        self.log.insert("end", line+"\n", tag)
        if float(self.log.index("end-1c").split(".")[0]) > 5000:
            self.log.delete("1.0","1000.0")
        self.log.see("end"); self.log.config(state="disabled")

    def _start(self):
        exe = self.v_exe.get().strip()
        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Not found",
                "Could not find the game.\nPlease browse first.")
            return
        try: port = int(self.v_port.get())
        except: port = 1757
        self._save()
        access, refresh, identity = build_server_tokens()
        try:
            with open(CONSOLE_TOKEN_FILE,"w") as f:
                f.write(access)
        except: pass
        if not self._auth_on:
            start_auth_service(self._print)
            self._auth_on = True
        args = [exe, "/force_offline",
                "/access_token", access, "/refresh_token", refresh,
                "/identity_token", identity]
        if not self.v_show_game.get():
            args += ["-batchmode", "-nographics"]
        args += ["/fly", "/noapi", "/start_server", "-1", "false", str(port)]
        if self.v_debug_helper.get():
            args.append("/debug_helper")
        self._print(f"Opening server on port {port}…", "warn")
        try:
            # Whether MelonLoader's console shows up is controlled by the
            # Show MelonLoader toggle: hiding it means redirecting the
            # child's std handles at creation time (skips AllocConsole);
            # showing it means leaving them alone.
            kwargs = {} if self.v_show_melonloader.get() else \
                     {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
            self._proc = subprocess.Popen(args, cwd=os.path.dirname(exe), **kwargs)
        except Exception as e:
            self._print(f"Failed: {e}", "err"); return
        self._set_running(True)
        self._print(f"Server running (PID {self._proc.pid})", "ok")
        threading.Thread(target=self._watch, daemon=True).start()

    def _watch(self):
        time.sleep(8)
        if self._proc and self._proc.poll() is None:
            self._print("Server ready. Players may connect.", "ok")
        else:
            self._print("Server exited unexpectedly.", "err")
            self.after(0, lambda: self._set_running(False))

    def _stop(self):
        if self._proc:
            try: self._proc.terminate(); self._print("Closing server…", "warn")
            except Exception as e: self._print(f"Stop failed: {e}", "err")
        self._set_running(False); self._proc = None

    def _set_running(self, on):
        def _do():
            self._dot.itemconfig("dot", fill=GREEN if on else MUTED)
            self._status_var.set("Online" if on else "Offline")
            self._pid_var.set(f"PID {self._proc.pid}" if on and self._proc else "")
            self._btn_start.config(state="disabled" if on else "normal")
            self._btn_stop.config(state="normal" if on else "disabled")
            self._apply_community_listing_state(on)
        self.after(0, _do)

    # ── Community server list ───────────────────────────────────────────────

    def _apply_community_listing_state(self, server_online):
        """Start or stop the background heartbeat so the community listing
        tracks both the settings checkbox and whether the server is actually
        online — flip either one and this brings the listing in line."""
        ss = load_server_settings()
        want_listed = bool(ss.get("community_listed")) and server_online
        if want_listed and not self._community_registered:
            self._community_registered = True
            self._community_stop.clear()
            self._community_thread = threading.Thread(
                target=self._community_loop, daemon=True)
            self._community_thread.start()
        elif not want_listed and self._community_registered:
            self._community_registered = False
            self._community_stop.set()

    def _community_loop(self):
        first = True
        while True:
            self._register_community_listing(log=first)
            first = False
            if self._community_stop.wait(COMMUNITY_HEARTBEAT_SECONDS):
                break
        self._unregister_community_listing()

    def _register_community_listing(self, log=False):
        ss = load_server_settings()
        try: port = int(self.v_port.get())
        except: port = 1757
        payload = {
            "listing_token": _get_or_create_listing_token(),
            "name": ss.get("name", "My Tavern Server"),
            "port": port,
            "player_limit": ss.get("max_players", 24),
            "has_password": bool(ss.get("password_hash")),
            "kind": "official",
        }
        # Prefer real numbers from a mod (e.g. TavernLib) reporting the
        # game's actual live connection count, if it's there and fresh —
        # falling back to the admin-configured Max Players setting for the
        # limit, and just omitting player_count entirely if we have no
        # real data rather than reporting a made-up 0.
        live_count, live_limit = _read_live_player_status()
        if live_count is not None:
            payload["player_count"] = live_count
        if live_limit is not None and live_limit > 0:
            payload["player_limit"] = live_limit
        hostname = ss.get("public_hostname", "").strip()
        if hostname:
            payload["hostname"] = hostname
        try:
            req = urllib.request.Request(COMMUNITY_API,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "TavernServer/1.0"},
                method="POST")
            resp = json.loads(urllib.request.urlopen(req, timeout=8).read().decode())
            if log:
                self._print("Listed on the community server list.", "ok")
                if hostname and resp.get("hostname_verified") is False:
                    self._print(
                        f"Note: '{hostname}' doesn't currently resolve to this "
                        "server's IP — showing your raw IP instead until it does.",
                        "warn")
        except Exception as e:
            if log: self._print(f"Could not reach community list: {e}", "warn")

    def _unregister_community_listing(self):
        try:
            req = urllib.request.Request(COMMUNITY_API,
                data=json.dumps({"listing_token": _get_or_create_listing_token()}).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "TavernServer/1.0"},
                method="DELETE")
            urllib.request.urlopen(req, timeout=5).read()
            self._print("Removed from the community server list.", "dim")
        except Exception:
            pass

    def _on_close(self):
        stopped_now = False
        if self._proc and self._proc.poll() is None:
            if messagebox.askyesno("Server running",
                                   "Stop the server before closing?"):
                self._stop()
                stopped_now = True
        if self._community_registered and not stopped_now:
            # _stop() above already triggers this via _set_running(False);
            # only needed here if the server was left running on close.
            self._community_stop.set()
            self._community_registered = False
            self._unregister_community_listing()
        self.destroy()


if __name__ == "__main__":
    if _updater is not None:
        _updater.cleanup_previous_update()
    app = ServerLauncher()
    app.mainloop()
