"""
The Modding Tavern — Client Launcher
"""

# Bump this with every release you publish to
# github.com/ModdingTavern/TavernLauncher/releases (tag it vX.Y.Z to match).
APP_VERSION = "1.7.1"

# The subfolder this app occupies inside the release zip
# (TavernLauncher-vX.Y.Z.zip contains /Client and /Server side by side) —
# used by the self-updater to know which part of the zip is "ours".
UPDATE_APP_FOLDER = "Client"

import os, subprocess, time, json, threading, io, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import base64, urllib.request
from urllib.parse import urlencode

_updater = None
try:
    import updater as _updater
except ImportError:
    pass

from tavern_common import (
    AUTH_PORT, BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED,
    GREEN, RED, CYAN, MONO,
    _enable_dark_titlebar, _set_window_icon,
    USERNAME_MAX_LEN, USERNAME_EXTRA_CHARS, _is_valid_name,
    _tavern_data_dir, _migrate_legacy_file,
    _b64url, _jwt, GameLogTailer,
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

from client_auth import (
    _migrate_legacy_tokens, _get_or_create_token, _any_token_files_exist,
    authenticate, ping_server, _resolve_ip_for_game, _valid_port,
    build_tokens, _headless_user_id,
)

GAME_LOG_PATH = os.path.join(
    os.path.expanduser("~"), "AppData", "Roaming",
    "A Township Tale", "Client", "logs", "unity-log.csv"
)

# Community server list backend — a small Flask app the server owner runs
# at home (see community_server.py). Plain HTTP on the port they forwarded;
# it's just public server metadata, nothing sensitive.
COMMUNITY_API = "http://themoddingtavern.com:1763/servers"
DISCORD_URL   = "https://discord.gg/jNQUUDAYSj"

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
                      min_reveal=0.35, min_width=540, reveal_at_width=1400):
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
#  AUTH
# ══════════════════════════════════════════════════════════════════════════════

CONFIG_FILE = os.path.join(_tavern_data_dir(), "tavern_launcher.json")
_migrate_legacy_file(os.path.join(os.path.expanduser("~"), ".tavern_launcher.json"), CONFIG_FILE)
_migrate_legacy_tokens()

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def load_cfg():
    try: return json.load(open(CONFIG_FILE))
    except: return {}

def save_cfg(d):
    try: json.dump(d, open(CONFIG_FILE,"w"), indent=2)
    except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

def _hint(parent, text):
    tk.Label(parent, text=text, bg=BG, fg=MUTED, justify="left",
             font=("Segoe UI",8)).pack(anchor="w", padx=22, pady=(0,2))

def _mk_combobox(parent, var, values):
    style = ttk.Style()
    style.configure("Tav.TCombobox",
                    fieldbackground=SURF, background=SURF2,
                    foreground=PARCH, selectbackground=SURF,
                    selectforeground=PARCH, arrowcolor=AMBERDIM, borderwidth=0)
    style.map("Tav.TCombobox",
              fieldbackground=[("readonly",SURF)],
              foreground=[("readonly",PARCH)],
              selectbackground=[("readonly",SURF)],
              selectforeground=[("readonly",PARCH)])
    parent.option_add("*TCombobox*Listbox.background",       SURF)
    parent.option_add("*TCombobox*Listbox.foreground",       PARCH)
    parent.option_add("*TCombobox*Listbox.selectBackground", AMBERDIM)
    parent.option_add("*TCombobox*Listbox.selectForeground", "#ffd080")
    cb = ttk.Combobox(parent, textvariable=var, values=values,
                      state="readonly", font=("Consolas",10), style="Tav.TCombobox")
    cb.pack(fill="x", ipady=4, padx=6, pady=6)
    return cb

def _mk_scrollbar(parent, command, orient="vertical"):
    """A ttk scrollbar styled to match the dark theme.
    Plain tk.Scrollbar renders using native Windows visual styles and ignores
    bg/troughcolor there, which is why scrollbars stayed white — ttk under the
    'clam' theme draws its own elements instead, so our colors actually apply."""
    style = ttk.Style()
    name = "Tav.Vertical.TScrollbar" if orient == "vertical" else "Tav.Horizontal.TScrollbar"
    style.configure(name, background=SURF2, troughcolor=BG, bordercolor=BORDER,
                    arrowcolor=AMBERDIM, darkcolor=SURF2, lightcolor=SURF2, relief="flat")
    style.map(name, background=[("active", AMBERDIM), ("pressed", AMBERDIM)],
              arrowcolor=[("pressed", "#ffd080")])
    sb = ttk.Scrollbar(parent, orient=orient, command=command, style=name)
    return sb

def _mk_tree(parent, cols, widths, height=8, hscroll=False):
    style = ttk.Style()
    style.configure("Tav.Treeview", background=SURF, fieldbackground=SURF,
                    foreground=PARCH, rowheight=26, borderwidth=0)
    style.configure("Tav.Treeview.Heading", background=SURF2, foreground=AMBER,
                    font=("Georgia",9,"bold"))
    style.map("Tav.Treeview",
              background=[("selected",AMBERDIM)],
              foreground=[("selected","#ffd080")])
    f = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill="both", expand=True)

    hsb = None
    if hscroll:
        # Pack the horizontal scrollbar at the bottom first so it claims its
        # space before the tree body below fills the rest — reversing this
        # order would let the tree body crowd the scrollbar out entirely.
        hsb = _mk_scrollbar(f, None, "horizontal")
        hsb.pack(side="bottom", fill="x")

    body = tk.Frame(f, bg=SURF)
    body.pack(fill="both", expand=True, padx=2, pady=2)

    tree = ttk.Treeview(body, columns=cols, show="headings",
                        selectmode="browse", height=height, style="Tav.Treeview")
    for col, w in zip(cols, widths):
        tree.heading(col, text=col.replace("_"," ").title())
        # With a horizontal scrollbar, columns should keep their exact width
        # and overflow into scroll range rather than being squeezed to fit —
        # that squeezing is exactly what made columns unreadable before.
        tree.column(col, width=w, minwidth=w, stretch=not hscroll, anchor="w")

    vsb = _mk_scrollbar(body, tree.yview, "vertical")
    vsb.pack(side="right", fill="y")
    tree.pack(side="left", fill="both", expand=True)
    tree.config(yscrollcommand=vsb.set)
    if hsb is not None:
        hsb.config(command=tree.xview)
        tree.config(xscrollcommand=hsb.set)
    return tree

# ══════════════════════════════════════════════════════════════════════════════
#  COMMUNITY BROWSER
# ══════════════════════════════════════════════════════════════════════════════

class CommunityBrowser(tk.Toplevel):
    _COLUMNS = ("name","address","players","locked","type")
    _HEADINGS = {"name":"Name","address":"Address","players":"Players",
                 "locked":"Locked","type":"Type"}
    _SORT_KEYS = {
        "name":    lambda s: s.get("name","").lower(),
        "address": lambda s: s.get("address","").lower(),
        "players": lambda s: s.get("player_count",0),
        "locked":  lambda s: bool(s.get("has_password")),
        "type":    lambda s: s.get("kind","official"),
    }

    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("Community Servers")
        self.configure(bg=BG)
        self.geometry("640x460")
        self.resizable(False, False)
        self._on_select = on_select
        self._servers   = []   # full list, straight from the API
        self._visible    = []  # filtered + sorted subset actually shown
        self._sort_col   = None
        self._sort_reverse = False
        self._build()
        self._refresh()
        _enable_dark_titlebar(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🌍  Community Servers", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        sf = tk.Frame(self, bg=BG)
        sf.pack(fill="x", padx=20, pady=(10,4))
        tk.Label(sf, text="🔍", bg=BG, fg=MUTED, font=("Segoe UI",10)).pack(side="left")
        self.v_search = tk.StringVar(value="")
        self.v_search.trace_add("write", lambda *_: self._populate())
        tk.Entry(sf, textvariable=self.v_search, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True, padx=(6,0))

        self._status = tk.StringVar(value="Fetching server list…")
        tk.Label(self, textvariable=self._status, bg=BG, fg=MUTED,
                 font=("Segoe UI",9)).pack(anchor="w", padx=20, pady=(4,4))

        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,8))
        self.tree = _mk_tree(lf, self._COLUMNS,
                             [210,150,70,50,80], height=8, hscroll=True)
        for col in self._COLUMNS:
            self.tree.heading(col, text=self._HEADINGS[col],
                              command=lambda c=col: self._sort_by(c))

        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=20, pady=(0,12))
        _btn(br, "⟳ Refresh", self._refresh, font=("Segoe UI",9),
             pady=6, padx=12).pack(side="left")
        _btn(br, "★ Save as Favorite", self._save_favorite,
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)
        _btn(br, "Connect",   self._connect, "primary",
             font=("Georgia",10,"bold"), pady=6, padx=14).pack(side="right")

    def _refresh(self):
        self._status.set("Fetching…")
        for r in self.tree.get_children(): self.tree.delete(r)
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            req = urllib.request.Request(COMMUNITY_API,
                headers={"User-Agent":"TavernLauncher/1.0"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
            self._servers = data if isinstance(data, list) else []
            self.after(0, self._populate)
        except Exception as e:
            self.after(0, lambda: self._status.set(
                f"Could not reach community list — {e}"))

    def _sort_by(self, col):
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        self._populate()

    def _populate(self):
        query = self.v_search.get().strip().lower()
        if query:
            visible = [s for s in self._servers if
                       query in s.get("name","").lower() or
                       query in s.get("address","").lower()]
        else:
            visible = list(self._servers)

        if self._sort_col:
            key = self._SORT_KEYS[self._sort_col]
            visible.sort(key=key, reverse=self._sort_reverse)

        self._visible = visible

        for col in self._COLUMNS:
            label = self._HEADINGS[col]
            if col == self._sort_col:
                label += " ▼" if self._sort_reverse else " ▲"
            self.tree.heading(col, text=label)

        for r in self.tree.get_children(): self.tree.delete(r)
        for s in self._visible:
            players = f"{s.get('player_count',0)}/{s.get('player_limit',50)}"
            locked  = "🔒" if s.get("has_password") else ""
            kind    = s.get("kind", "official")
            type_label = "🏛 Official" if kind == "official" else "🌐 Headless"
            self.tree.insert("","end",
                values=(s.get("name","?"), s.get("address","?"), players, locked, type_label))

        if not self._servers:
            self._status.set("No servers listed yet.")
        elif query and not visible:
            self._status.set(f"No servers match '{query}'.")
        else:
            self._status.set(f"{len(visible)} of {len(self._servers)} servers shown."
                             if query else f"{len(self._servers)} servers listed.")

    def _selected_server(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Select a server first.")
            return None
        return self._visible[self.tree.index(sel[0])]

    def _connect(self):
        srv = self._selected_server()
        if not srv: return
        kind = srv.get("kind", "official")
        address = srv.get("address","")
        host = address.split(":")[0]
        port = address.split(":")[1] if ":" in address else "1757"
        # "address" is "ip:port" for display — only the host is meaningful to
        # the auth handshake / headless join today, but the port still gets
        # passed through so Join Server can hand it to the game itself.
        self._on_select(host, srv.get("name",""), kind, port)
        self.destroy()

    def _save_favorite(self):
        srv = self._selected_server()
        if not srv: return
        address = srv.get("address","")
        host = address.split(":")[0]
        port = address.split(":")[1] if ":" in address else "1757"
        name = srv.get("name") or host
        cfg = load_cfg()
        saved = cfg.get("saved_servers", [])
        if any(s.get("ip") == host for s in saved):
            messagebox.showinfo("Already saved", f"'{name}' is already in your favorites.")
            return
        saved.append({"name": name, "ip": host, "port": port})
        cfg["saved_servers"] = saved
        save_cfg(cfg)
        messagebox.showinfo("Saved", f"'{name}' added to favorites.")

# ══════════════════════════════════════════════════════════════════════════════
#  SERVER LIST PANEL  (Saved / Recent)
# ══════════════════════════════════════════════════════════════════════════════

class ServerListPanel(tk.Toplevel):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("Saved & Recent Servers")
        self.configure(bg=BG)
        self.geometry("520x460")
        self.resizable(False, False)
        self._on_select = on_select
        self._build()
        _enable_dark_titlebar(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚑  Your Servers", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        nb = ttk.Notebook(self)
        style = ttk.Style()
        style.configure("TavNB.TNotebook", background=BG, borderwidth=0)
        style.configure("TavNB.TNotebook.Tab", background=SURF2, foreground=PARCH,
                        padding=(12,5), font=("Georgia",9))
        style.map("TavNB.TNotebook.Tab",
                  background=[("selected",AMBERDIM)],
                  foreground=[("selected","#ffd080")])
        nb.configure(style="TavNB.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        fav_tab    = tk.Frame(nb, bg=BG)
        recent_tab = tk.Frame(nb, bg=BG)
        nb.add(fav_tab,    text="  Favourites  ")
        nb.add(recent_tab, text="  Recent  ")

        self._build_fav_tab(fav_tab)
        self._build_recent_tab(recent_tab)

    def _build_fav_tab(self, parent):
        lf = tk.Frame(parent, bg=BG)
        lf.pack(fill="both", expand=True, padx=8, pady=(8,4))
        self.fav_tree = _mk_tree(lf, ("label","ip"), [240,200], height=9)
        cfg = load_cfg()
        for s in cfg.get("saved_servers", []):
            self.fav_tree.insert("","end", values=(s.get("name",s.get("ip","")), s.get("ip","")))

        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,8))

        def connect():
            sel = self.fav_tree.selection()
            if not sel: return
            vals = self.fav_tree.item(sel[0],"values")
            ip = vals[1]
            entry = next((s for s in load_cfg().get("saved_servers",[])
                          if s.get("ip") == ip), {})
            self._on_select(ip, vals[0], entry.get("port","1757")); self.destroy()

        def remove():
            sel = self.fav_tree.selection()
            if not sel: return
            vals = self.fav_tree.item(sel[0],"values")
            cfg = load_cfg()
            cfg["saved_servers"] = [s for s in cfg.get("saved_servers",[])
                                    if s.get("ip") != vals[1]]
            save_cfg(cfg); self.fav_tree.delete(sel[0])

        def add_manual():
            ip = simpledialog.askstring("Add Server",
                "Server IP:", parent=self)
            if not ip: return
            ip = ip.strip()
            label = simpledialog.askstring("Add Server",
                "Label for this server:", parent=self) or ip
            port = simpledialog.askstring("Add Server",
                "Port (leave blank for 1757):", parent=self) or "1757"
            cfg = load_cfg()
            saved = cfg.get("saved_servers", [])
            saved.append({"name": label, "ip": ip, "port": port})
            cfg["saved_servers"] = saved
            save_cfg(cfg)
            self.fav_tree.insert("","end", values=(label, ip))

        _btn(br, "Connect",   connect,    "primary", font=("Georgia",10,"bold"),
             pady=6, padx=14).pack(side="left")
        _btn(br, "+ Add IP",  add_manual, style="normal",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)
        _btn(br, "✕ Remove",  remove,     "danger",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left")

    def _build_recent_tab(self, parent):
        lf = tk.Frame(parent, bg=BG)
        lf.pack(fill="both", expand=True, padx=8, pady=(8,4))
        self.rec_tree = _mk_tree(lf, ("name","ip"), [240,200], height=9)
        cfg = load_cfg()
        for s in cfg.get("recent_servers", []):
            self.rec_tree.insert("","end", values=(s.get("name",s.get("ip","")), s.get("ip","")))

        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,8))

        def connect():
            sel = self.rec_tree.selection()
            if not sel: return
            vals = self.rec_tree.item(sel[0],"values")
            ip = vals[1]
            entry = next((s for s in load_cfg().get("recent_servers",[])
                          if s.get("ip") == ip), {})
            self._on_select(ip, vals[0], entry.get("port","1757")); self.destroy()

        def save_fav():
            sel = self.rec_tree.selection()
            if not sel: return
            vals = self.rec_tree.item(sel[0],"values")
            ip, name = vals[1], vals[0]
            # If name is just the IP, ask for a proper label
            if name == ip or not name:
                name = simpledialog.askstring("Save Favourite",
                    f"Label for {ip}:", parent=self) or ip
            port = next((s.get("port","1757") for s in load_cfg().get("recent_servers",[])
                         if s.get("ip") == ip), "1757")
            cfg = load_cfg()
            saved = cfg.get("saved_servers", [])
            if not any(s["ip"] == ip for s in saved):
                saved.append({"name": name, "ip": ip, "port": port})
                cfg["saved_servers"] = saved
                save_cfg(cfg)
                messagebox.showinfo("Saved", f"'{name}' added to favourites.")

        _btn(br, "Connect",        connect,  "primary",
             font=("Georgia",10,"bold"), pady=6, padx=14).pack(side="left")
        _btn(br, "★ Save as Fav",  save_fav, style="normal",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)

# ══════════════════════════════════════════════════════════════════════════════
#  MAIN LAUNCHER
# ══════════════════════════════════════════════════════════════════════════════

class ClientLauncher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TavernLauncher - Client")
        self.configure(bg=BG)
        # This is the one window players stare at while the log scrolls —
        # letting it resize means the log area actually gets to use whatever
        # space is available instead of being locked to one fixed height.
        self.resizable(True, True)
        self.geometry("540x820")  # placeholder; resized to fit content below
        _set_window_icon(self)
        ttk.Style().theme_use("clam")
        self._tailer      = None
        self._server_ok   = False   # True once Check Server succeeds
        self._checked_host = None
        # Tracks whether the currently-filled-in server (from the Community
        # browser) is an official Tavern server or a headless/direct-connect
        # one — controls whether Join Server goes through the auth handshake
        # at all. Manually typed IPs and Saved/Recent selections always reset
        # this back to "official", matching how they've always behaved.
        self._selected_kind = "official"
        self._exe_check_job   = None
        self._build_ui()
        self._load()
        # Start at exactly the size the fully-built layout needs, then set
        # that as the floor — shrinking further would start cutting into
        # either the log area or the bottom toggle row (whichever runs out
        # of room first), while growing beyond it just gives the log more
        # room to breathe. fit_w used to be a hardcoded guess that went
        # stale every time a row gained another button/checkbox — measuring
        # it the same way fit_h already was is what actually keeps this
        # correct going forward.
        self.update_idletasks()
        fit_w = max(540, self.winfo_reqwidth())
        fit_h = self.winfo_reqheight()
        self.geometry(f"{fit_w}x{fit_h}")
        self.minsize(fit_w, fit_h)
        _enable_dark_titlebar(self)

    # ── UI ─────────────────────────────────────────────────────────────────────

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
        btn_row_mods = tk.Frame(self, bg=BG)
        btn_row_mods.pack(fill="x", padx=20, pady=(4,0))
        self._patch_btn = _btn(btn_row_mods, "🩹 Patch", self._on_patch_click,
             font=("Segoe UI",9), pady=5, padx=10)
        self._patch_btn.pack(side="left")
        self._mods_btn = _btn(btn_row_mods, "🧪 Mods", self._open_mods,
             font=("Segoe UI",9), pady=5, padx=10)
        self._mods_btn.pack(side="left", padx=(6,0))
        _hint(self, "Please install the above mods in order before you launch the game")
        self._mods_flasher  = _FlashingButton(self, self._mods_btn,
            (SURF2, AMBER), ("#5a3d0e","#ffd080"), (SURF2, PARCH))
        self._patch_flasher = _FlashingButton(self, self._patch_btn,
            ("#1a3d2a","#80d8aa"), ("#0d2419","#50aa7a"), (SURF2, PARCH))

        _divider(self)

        _section_label(self, "CHOOSE YOUR USERNAME")
        nf = _field(self)
        self.v_username = tk.StringVar()
        tk.Entry(nf, textvariable=self.v_username, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(fill="x")
        _hint(self, f"Your save is tied to this name. Max {USERNAME_MAX_LEN} characters. "
                    "Letters, numbers, spaces, hyphens, and underscores only.")

        _section_label(self, "CHOOSE YOUR PLATFORM")
        pf2 = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        pf2.pack(fill="x", padx=20, pady=(0,4))
        self.v_platform = tk.StringVar(value="OpenVR")
        _mk_combobox(pf2, self.v_platform, ["OpenVR","Oculus"])
        _hint(self, "OpenVR = SteamVR  ·  Oculus = Quest")

        _divider(self)

        _section_label(self, "DESTINATION")
        sf = _field(self)
        self.v_ip = tk.StringVar()
        self.v_ip.trace_add("write", self._on_ip_changed)
        tk.Entry(sf, textvariable=self.v_ip, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True)
        self.v_port = tk.StringVar(value="1757")
        tk.Entry(sf, textvariable=self.v_port, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, width=6, justify="center").pack(side="left", padx=(4,0))

        btn_row_dest = tk.Frame(self, bg=BG)
        btn_row_dest.pack(fill="x", padx=20, pady=(4,0))
        _btn(btn_row_dest, "⚑ Saved",             self._open_server_list,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(btn_row_dest, "🌍 Community Servers", self._open_community,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _hint(self, "Server IP — leave blank for local. Port defaults to 1757.")

        # ── Action area ──────────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=6)

        # Status line shown after Check Server — plain label, not a box
        self._check_status = tk.StringVar(value="")
        self._check_label = tk.Label(self, textvariable=self._check_status,
                 bg=BG, fg=MUTED, font=("Segoe UI",9),
                 justify="left", anchor="w", wraplength=480)
        self._check_label.pack(fill="x", padx=22, pady=(0,4))

        # Check Server and Join Server sit side by side — checking is purely
        # optional/informational now, never a gate on joining.
        action_row = tk.Frame(self, bg=BG)
        action_row.pack(fill="x", padx=20, pady=(0,4))
        self._check_btn = _btn(action_row, "🔍  Check Server", self._do_check,
                                font=("Georgia",12,"bold"), pady=14)
        self._check_btn.pack(side="left", fill="x", expand=True, padx=(0,4))
        self._action_btn = _btn(action_row, "⚔  Join Server", self._on_join_clicked,
                                style="primary", font=("Georgia",12,"bold"), pady=14)
        self._action_btn.pack(side="left", fill="x", expand=True, padx=(4,0))

        # ── Log ───────────────────────────────────────────────────────────────
        _section_label(self, "GAME LOG")
        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,8))
        lb = tk.Frame(lf, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lb.pack(fill="both", expand=True)
        self.log = tk.Text(lb, bg=SURF, fg="#b09a78", font=MONO,
                           relief="flat", bd=0, state="disabled", height=12,
                           wrap="none")
        sb = _mk_scrollbar(lb, self.log.yview)
        sb.pack(side="right", fill="y")
        self.log.config(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True, padx=6, pady=6)
        for t,c in [("ok",GREEN),("warn",AMBER),("err",RED),
                    ("cyan",CYAN),("dim",MUTED),("error",RED),
                    ("info","#b09a78"),("debug",MUTED)]:
            self.log.tag_config(t, foreground=c)
        self._log_status = tk.StringVar(value="Awaiting game…")
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
        canvas.create_text(18, 32, text="⚔", fill=AMBER, font=("Georgia",22), anchor="w")
        canvas.create_text(66, 21, text="The Modding Tavern", fill=AMBER,
                           font=("Georgia",14,"bold"), anchor="w")
        canvas.create_text(66, 42, text=f"Client Launcher  ·  v{APP_VERSION}", fill=AMBER,
                           font=("Segoe UI",9), anchor="w")

        self._discord_btn = tk.Button(canvas, text="💬 Discord", bg=SURF2, fg=AMBER,
                                      activebackground=AMBERDIM, activeforeground="#ffd080",
                                      relief="flat", bd=0, cursor="hand2",
                                      font=("Segoe UI",9,"bold"), padx=10, pady=4,
                                      command=lambda: webbrowser.open(DISCORD_URL))
        self._discord_btn_item = canvas.create_window(0, 32, anchor="e", window=self._discord_btn)

        # Token badge — a real Button (for its existing click/animation
        # logic) embedded onto the canvas so it layers correctly over the
        # banner image; created hidden, _show_token_button() reveals it.
        self._token_note = (
            "A token file has been created for you. This file is used to prove who you "
            "are when connecting to a server with your chosen username. It can be found "
            "in your %AppData%\\Roaming\\TheModdingTavern\\tokens folder. Make sure to keep "
            "this file safe, as you won't be able to connect with this account if it is "
            "lost. If you do lose it - please reach out to the server owner to get it back."
        )
        self._token_btn = tk.Button(canvas, text="🔑 Token", bg=SURF2, fg=AMBER,
                                    activebackground=AMBERDIM, activeforeground="#ffd080",
                                    relief="flat", bd=0, cursor="hand2",
                                    font=("Segoe UI",9,"bold"), padx=10, pady=4,
                                    command=self._on_token_button_click)
        self._token_btn_item = canvas.create_window(0, 32, anchor="e",
                                                     window=self._token_btn, state="hidden")
        self._token_flasher = _FlashingButton(self, self._token_btn,
            (SURF2, AMBER), ("#5a3d0e","#ffd080"), (SURF2, PARCH))

        canvas.bind("<Configure>", self._on_header_resize)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _on_header_resize(self, event):
        """Rescales the banner to fill the header exactly, and keeps the
        Discord/token badges right-aligned — none of this reflows on its
        own, since a Canvas doesn't auto-stretch or reposition children."""
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
        discord_w = self._discord_btn.winfo_reqwidth()
        self._header_canvas.coords(self._token_btn_item, w - 14 - discord_w - 10, hgt // 2)

    # ── Token badge / animation ─────────────────────────────────────────────

    def _show_token_button(self):
        """Reveal the token badge and make sure it's flashing. Called at
        startup if a token file already exists, and after every successful
        connection. Once shown, it keeps flashing for the rest of the
        session — it's meant to keep reminding the player the file exists."""
        if self._header_canvas.itemcget(self._token_btn_item, "state") != "normal":
            self._header_canvas.itemconfigure(self._token_btn_item, state="normal")
            # Position it correctly immediately — otherwise it sits at the
            # placeholder (0, ...) coordinate from creation until the next
            # window resize happens to trigger a reposition. Same formula as
            # _on_header_resize: left of the always-visible Discord button.
            w   = self._header_canvas.winfo_width()
            hgt = self._header_canvas.winfo_height()
            discord_w = self._discord_btn.winfo_reqwidth()
            self._header_canvas.coords(self._token_btn_item, w - 14 - discord_w - 10, hgt // 2)
        if not self._token_flasher.running:
            self._token_flasher.start()

    def _on_token_button_click(self):
        messagebox.showinfo("About Your Token File", self._token_note, parent=self)

    # ── Mods alert / animation ──────────────────────────────────────────────
    # Unlike the token badge, this flashes only *while there's a problem* —
    # a mod missing or out of date — and stops on its own once resolved.

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

    # ── Patch button ────────────────────────────────────────────────────────

    def _refresh_patch_alert(self, exe):
        """Flash the Patch button only while the patch DLL is actually
        present AND not already applied — a real on-disk check (see
        _patch_is_applied), so it correctly reflects reality even if the
        other launcher (client/server) already did this for the same game."""
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

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        cfg = load_cfg()
        self.v_exe.set(cfg.get("game_exe",""))
        self.v_username.set(cfg.get("username",""))
        # "none" (flatscreen) is temporarily disabled — exploitable — so a
        # value saved before this change doesn't silently keep working just
        # because it's already sitting in the user's config file.
        saved_platform = cfg.get("platform", "OpenVR")
        self.v_platform.set(saved_platform if saved_platform in ("OpenVR", "Oculus") else "OpenVR")
        self.v_ip.set(cfg.get("last_ip",""))
        self.v_port.set(cfg.get("last_port","1757"))
        self.v_debug_helper.set(cfg.get("debug_helper", False))
        self.v_show_melonloader.set(cfg.get("show_melonloader", False))
        self._print("Ready. Enter a server IP, then Check Server (optional) or Join Server.", "dim")
        self._start_log_tailer()
        if _any_token_files_exist():
            self._show_token_button()
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
        cfg = load_cfg()
        cfg.update({"game_exe": self.v_exe.get(), "username": self.v_username.get(),
                    "platform": self.v_platform.get(), "last_ip": self.v_ip.get(),
                    "last_port": self.v_port.get(),
                    "debug_helper": self.v_debug_helper.get(),
                    "show_melonloader": self.v_show_melonloader.get()})
        save_cfg(cfg)

    def _wipe_cache(self):
        if not messagebox.askyesno("Wipe Launcher Cache",
                "This will delete this launcher's saved settings file:\n\n"
                f"{CONFIG_FILE}\n\n"
                "That includes your saved username, game path, last server "
                "IP, and toggle preferences — giving you a completely fresh, "
                "unconfigured launcher next time it starts.\n\n"
                "Your token files, patch, and installed mods are NOT affected.\n\n"
                "This cannot be undone. Continue?", icon="warning"):
            return
        try:
            if os.path.isfile(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            messagebox.showinfo("Cache Wiped",
                "Launcher cache cleared. The app will now close — "
                "reopen it for a fresh start.")
            self.destroy()
        except Exception as e:
            messagebox.showerror("Wipe failed", str(e))

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select A Township Tale.exe",
            filetypes=[("Executable","*.exe"),("All","*.*")])
        if p: self.v_exe.set(p.replace("/","\\")); self._save()

    def _open_server_list(self):
        def on_select(ip, name, port="1757"):
            self.v_ip.set(ip); self.v_port.set(str(port))
            self._selected_kind = "official"; self._save()
        ServerListPanel(self, on_select)

    def _open_community(self):
        def on_select(ip, name, kind, port="1757"):
            self.v_ip.set(ip); self.v_port.set(str(port))
            self._selected_kind = kind; self._save()
        CommunityBrowser(self, on_select)

    def _open_mods(self):
        exe = self.v_exe.get().strip()
        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Game not found",
                "Please set the path to 'A Township Tale.exe' above first.")
            return
        ModsWindow(self, exe, on_status_change=self._refresh_mods_alert)

    def _on_ip_changed(self, *_):
        """Clear the stale check-status line whenever the IP field changes —
        Check Server and Join Server are both independent from here on, so
        there's no button mode to reset, just the leftover status text.
        Also resets to "official" — a manually-typed IP isn't something we
        know the kind of, so fall back to the flow that's always applied."""
        self._server_ok    = False
        self._checked_host = None
        self._selected_kind = "official"
        self._check_status.set("")
        try: self._check_label.config(fg=MUTED)
        except: pass

    # ── Log helpers ─────────────────────────────────────────────────────────

    def _print(self, msg, tag=""):
        self.log.config(state="normal")
        self.log.insert("end", f"[{time.strftime('%H:%M:%S')}] {msg}\n", tag)
        self.log.see("end"); self.log.config(state="disabled")
        self.update_idletasks()

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
                self.after(0, lambda: self._log_status.set("Watching game log…"))
        self._tailer = GameLogTailer(GAME_LOG_PATH, on_line, on_status)
        self._tailer.start()

    def _append_log(self, line, tag):
        self.log.config(state="normal")
        self.log.insert("end", line+"\n", tag)
        if float(self.log.index("end-1c").split(".")[0]) > 5000:
            self.log.delete("1.0","1000.0")
        self.log.see("end"); self.log.config(state="disabled")

    # ── Check Server (optional, informational) / Join Server ──────────────────

    def _popen_console_kwargs(self):
        """Hiding MelonLoader's console means redirecting the child's std
        handles at process-creation time — that's what makes it skip
        AllocConsole(). Showing it just means not touching them at all."""
        if self.v_show_melonloader.get():
            return {}
        return {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}

    def _on_join_clicked(self):
        if self._selected_kind == "headless":
            self._do_launch_headless()
        else:
            self._do_launch(password=None)

    def _do_check(self):
        if self._selected_kind == "headless":
            # No port-1762 auth gate exists on these — there's nothing to
            # check. Say so plainly instead of attempting a doomed connection
            # that would just read as a generic failure.
            self._check_status.set(
                "Direct-connect (headless) server — no health check available. "
                "Just press Join Server.")
            try: self._check_label.config(fg=MUTED)
            except: pass
            return
        ip   = self.v_ip.get().strip()
        host = ip if ip else "127.0.0.1"
        self._check_btn.config(state="disabled")
        self._check_status.set(f"Checking {host}…")
        try: self._check_label.config(fg=MUTED)
        except: pass
        threading.Thread(target=self._run_check, args=(host,), daemon=True).start()

    def _run_check(self, host):
        try:
            resp, ms = ping_server(host)
            if resp.get("status") == "pong":
                sv_name = resp.get("server_name", host)
                pw_req  = resp.get("password_required", False)
                wl      = resp.get("whitelist_enabled", False)
                game_port = resp.get("game_port")
                lines   = [f"✔  {sv_name}  —  {ms} ms"]
                flags   = []
                if pw_req: flags.append("🔒 Password required")
                if wl:     flags.append("📋 Whitelist active")
                if game_port: flags.append(f"Port {game_port}")
                if flags:  lines.append("  ".join(flags))
                msg = "\n".join(lines)
                self.after(0, lambda: self._check_ok(host, msg, game_port))
            else:
                self.after(0, lambda: self._check_fail(f"Unexpected response from {host}"))
        except Exception as e:
            self.after(0, lambda: self._check_fail(f"✘  Cannot reach server — {e}"))

    def _check_ok(self, host, msg, game_port=None):
        self._server_ok    = True
        self._checked_host = host
        self._check_status.set(msg)
        self._check_label.config(fg=GREEN)
        self._check_btn.config(state="normal")
        # The server just told us its actual configured port — trust that
        # over whatever was already in the field, since it's the ground truth.
        if game_port:
            self.v_port.set(str(game_port))

    def _check_fail(self, msg):
        self._server_ok    = False
        self._checked_host = None
        self._check_status.set(msg)
        self._check_label.config(fg=RED)
        self._check_btn.config(state="normal")

    # ── Launch ────────────────────────────────────────────────────────────────

    def _try_headless_fallback(self, display_host, resolved_host):
        """Only reached when the normal auth service at port 1762 couldn't
        be contacted at all. Checks the community list for a *currently
        registered* headless server at this address, and only proceeds with
        an unauthenticated join if that's confirmed — this is a fallback
        for a known, already-vouched-for server, never a way to silently
        skip auth for an address that just happens to be unreachable or
        misconfigured. Tries the exact string the player typed first (in
        case it matches a verified hostname), then the resolved IP (in case
        they typed a hostname that isn't what the server registered with,
        but happens to point at the same place)."""
        candidates = [display_host]
        if resolved_host and resolved_host != display_host:
            candidates.append(resolved_host)

        for address in candidates:
            try:
                params = urlencode({"address": address})
                req = urllib.request.Request(f"{COMMUNITY_API}/lookup?{params}",
                    headers={"User-Agent": "TavernLauncher/1.0"})
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = json.loads(resp.read().decode())
            except Exception as e:
                self._print(f"Could not check community list: {e}", "warn")
                continue

            if data.get("found") and data.get("kind") == "headless":
                self._print(f"'{address}' is a known headless server — "
                            "joining directly, no auth.", "warn")
                if data.get("port"):
                    self.v_port.set(str(data["port"]))
                self._selected_kind = "headless"
                self._do_launch_headless()
                return True

        return False

    def _do_launch(self, password, _token_state=None):
        exe      = self.v_exe.get().strip()
        username = self.v_username.get().strip()
        platform = self.v_platform.get()
        ip       = self.v_ip.get().strip()
        display_host = ip if ip else "127.0.0.1"
        # Resolved once and used everywhere identity-sensitive matters (token
        # lookup, the auth handshake, and the game's own launch arg) — a
        # server reachable by both a hostname and its IP is still one server,
        # and needs to be treated as one for token purposes. Without this,
        # joining once via "myserver.com" and later via its raw IP would look
        # like two different servers locally, generate two different tokens,
        # and get rejected as "that name is taken by someone else" the second
        # time — even though it's the same account on the same server.
        host = _resolve_ip_for_game(display_host)

        if not self._validate_launch_inputs(exe, username):
            return

        self._save()
        self._action_btn.config(state="disabled")
        self._print(f"Authenticating '{username}'…", "dim")

        # Resolve (and, on first contact with this server, create) the token
        # once per launch attempt so a password retry doesn't regenerate it.
        if _token_state is None:
            had_token_before = _any_token_files_exist()
            token, token_is_new = _get_or_create_token(host, username)
        else:
            token, token_is_new, had_token_before = _token_state

        user_id, error = authenticate(host, username, token, password=password)

        if error == "NEEDS_PASSWORD":
            self._action_btn.config(state="normal")
            pw = simpledialog.askstring("Password Required",
                "This server requires a password:", show="*", parent=self)
            if pw: self._do_launch(password=pw,
                                    _token_state=(token, token_is_new, had_token_before))
            return

        if error and error.startswith("CANNOT_REACH::"):
            detail = error.split("::", 1)[1]
            self._print(f"No official auth service at {host}:{AUTH_PORT} — "
                        "checking community list for a headless registration…", "warn")
            if self._try_headless_fallback(display_host, host):
                return
            self._print(f"Rejected: Cannot reach server at {host}:{AUTH_PORT} — {detail}", "err")
            self._action_btn.config(state="normal")
            return

        if error:
            self._print(f"Rejected: {error}", "err")
            self._action_btn.config(state="normal")
            return

        self._print(f"Welcomed as {username} (ID {user_id})", "ok")
        self._show_token_button()
        if token_is_new and not had_token_before:
            # The very first token file this launcher has ever created on this
            # machine — open the explainer immediately instead of waiting for a click.
            self._on_token_button_click()

        # Record in recent — use server_name from last ping if available
        cfg = load_cfg()
        sv_name = display_host
        status_text = self._check_status.get()
        if status_text.startswith("✔"):
            # Parse the server name out of the status line "✔  ServerName  —  Xms"
            try: sv_name = status_text.split("✔")[1].split("—")[0].strip()
            except: pass
        recent = [r for r in cfg.get("recent_servers",[]) if r.get("ip") != display_host]
        recent.insert(0, {"name": sv_name, "ip": display_host, "port": self.v_port.get()})
        cfg["recent_servers"] = recent[:20]
        save_cfg(cfg)

        # host is already resolved to a canonical IP above — same value used
        # for the token lookup and the auth handshake, so all three agree.
        self._launch_game(exe, user_id, username, platform, ip, host)

    def _validate_launch_inputs(self, exe, username):
        """Shared Not-Found/Missing-Name/Too-Long/Invalid-Chars gate for both
        the official and headless launch paths. Shows the relevant error
        dialog and returns False on the first problem found."""
        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Not found",
                "Could not find the game.\nPlease browse to 'A Township Tale.exe'.")
            return False
        if not username:
            messagebox.showerror("Missing name",
                "Please enter your username before connecting.")
            return False
        if len(username) > USERNAME_MAX_LEN:
            messagebox.showerror("Name too long",
                f"Usernames can be at most {USERNAME_MAX_LEN} characters.")
            return False
        if not _is_valid_name(username):
            messagebox.showerror("Invalid name",
                "Usernames can only contain letters, numbers, spaces, hyphens, and underscores.")
            return False
        return True

    def _launch_game(self, exe, user_id, username, platform, ip, dev_server_ip):
        """Builds the game's launch args and starts it — shared tail of both
        _do_launch and _do_launch_headless, which only differ in how user_id
        and dev_server_ip get resolved before reaching this point."""
        access, refresh, identity = build_tokens(user_id, username)
        args = [exe, "/force_offline",
                "/access_token", access, "/refresh_token", refresh,
                "/identity_token", identity, "/join_local_server"]

        if platform == "none":
            args.insert(-1, "/fly")
        elif platform:
            args[-1:] = ["/vrmode", platform, "/join_local_server"]
        if ip:
            args += ["/dev_server_ip", dev_server_ip]
        args += ["/dev_server_port", str(_valid_port(self.v_port.get()))]
        if self.v_debug_helper.get():
            args.append("/debug_helper")

        self._print(f"Launching on {platform or 'default'}…", "warn")
        try:
            # Whether MelonLoader's own console window shows up is controlled
            # by the Show MelonLoader toggle: hiding it means redirecting the
            # child's std handles at creation time (which is what makes it
            # skip AllocConsole); showing it means leaving them alone.
            proc = subprocess.Popen(args, cwd=os.path.dirname(exe),
                                    **self._popen_console_kwargs())
            self._print(f"Game running (PID {proc.pid})", "ok")
        except Exception as e:
            self._print(f"Launch failed: {e}", "err")
        self._action_btn.config(state="normal")

    def _do_launch_headless(self):
        """Same launch as _do_launch, minus the port-1762 handshake entirely —
        for servers hosted directly via the game itself with no auth gate.
        user_id has no server to come from here, so it's derived locally
        instead (see _headless_user_id); everything after that point is
        identical to the official flow."""
        exe      = self.v_exe.get().strip()
        username = self.v_username.get().strip()
        platform = self.v_platform.get()
        ip       = self.v_ip.get().strip()
        host     = ip if ip else "127.0.0.1"

        if not self._validate_launch_inputs(exe, username):
            return

        self._save()
        self._action_btn.config(state="disabled")
        self._print(f"Joining headless server directly (no auth gate) as '{username}'…", "warn")

        user_id = _headless_user_id(username)

        cfg = load_cfg()
        recent = [r for r in cfg.get("recent_servers",[]) if r.get("ip") != host]
        recent.insert(0, {"name": host, "ip": host, "port": self.v_port.get()})
        cfg["recent_servers"] = recent[:20]
        save_cfg(cfg)

        self._launch_game(exe, user_id, username, platform, ip,
                           _resolve_ip_for_game(ip) if ip else None)


if __name__ == "__main__":
    if _updater is not None:
        _updater.cleanup_previous_update()
    app = ClientLauncher()
    app.mainloop()
