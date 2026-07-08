"""
The Modding Tavern — Client Launcher
"""

import sys, os, subprocess, time, json, socket, secrets, csv, threading, io, hashlib, glob
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import base64, hmac as _hmac, tempfile, urllib.request, urllib.error, ctypes

# ══════════════════════════════════════════════════════════════════════════════
#  DARK TITLE BAR  (Windows 10/11 only — safe no-op elsewhere)
# ══════════════════════════════════════════════════════════════════════════════

def _enable_dark_titlebar(window):
    """Tint a Tk window's OS title bar dark so it matches the app's palette.
    Windows 10 (1809+) / 11 only. Silently does nothing anywhere else.

    Setting DWMWA_USE_IMMERSIVE_DARK_MODE only takes visual effect the next
    time DWM fully recomposes the window's caption. A SetWindowPos(...,
    SWP_FRAMECHANGED) call isn't reliably enough to trigger that full
    recompose (icon, title text, AND the min/max/close buttons) on a window's
    very first paint — but a real hide/show cycle is, which is exactly why
    clicking into the window and back out "fixes" it: that round-trip forces
    Windows to fully repaint the non-client area from scratch.

    So instead of trying to nudge DWM with a frame-changed message, we just
    do that hide/show ourselves, using raw Win32 ShowWindow calls on the
    native handle (not Tk's withdraw/deiconify) so we don't disturb Tk's own
    idea of the window's state, focus, or grab. SW_HIDE + SW_SHOWNA is
    imperceptibly quick and SW_SHOWNA specifically does not steal focus or
    reorder the window, so it's safe to run on dialogs too.

    We also run this once immediately (harmless if the window isn't mapped
    yet) and again shortly after via `after()`, since the root Tk window
    isn't actually mapped onto the screen until mainloop() starts pumping
    events — which happens after __init__ (and this call) returns.
    """
    if sys.platform != "win32":
        return

    def _apply(force_repaint):
        try:
            window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            value = ctypes.c_int(1)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+/Win11)
            ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            if ok != 0:
                # 19 = older Win10 1809/1903 builds that used the pre-release attribute id
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
            if force_repaint:
                SW_HIDE, SW_SHOWNA = 0, 8
                ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
                ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNA)
        except Exception:
            pass

    _apply(force_repaint=False)
    try:
        window.after(60, lambda: _apply(force_repaint=True))
    except Exception:
        pass



# ══════════════════════════════════════════════════════════════════════════════
#  PALETTE
# ══════════════════════════════════════════════════════════════════════════════
BG       = "#1a1210"
SURF     = "#241c17"
SURF2    = "#2e2218"
BORDER   = "#4a3828"
AMBER    = "#e8a840"
AMBERDIM = "#8a5e1a"
PARCH    = "#f0e6cc"
MUTED    = "#8a7a62"
GREEN    = "#6aaa72"
RED      = "#c45c5c"
CYAN     = "#6ab0aa"
MONO     = ("Consolas", 9)

CONFIG_FILE = os.path.join(os.path.expanduser("~"), ".tavern_launcher.json")
AUTH_PORT   = 1762

GAME_LOG_PATH = os.path.join(
    os.path.expanduser("~"), "AppData", "Roaming",
    "A Township Tale", "Client", "logs", "unity-log.csv"
)

# Community server list backend — a small Flask app the server owner runs
# at home (see community_server.py). Plain HTTP on the port they forwarded;
# it's just public server metadata, nothing sensitive.
COMMUNITY_API = "http://themoddingtavern.com:1763/servers"

# ══════════════════════════════════════════════════════════════════════════════
#  ICON
# ══════════════════════════════════════════════════════════════════════════════
_ICON_B64 = None
try:
    from icon_data import ICON_B64 as _ICON_B64
except ImportError:
    pass

def _set_window_icon(root):
    if not _ICON_B64: return
    try:
        tmp = os.path.join(tempfile.gettempdir(), "tavern_icon.ico")
        with open(tmp, "wb") as f: f.write(base64.b64decode(_ICON_B64))
        root.iconbitmap(tmp)
    except Exception: pass

# ══════════════════════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════════════════════

def _app_dir():
    if getattr(sys, "frozen", False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _safe_part(s):
    return "".join(c for c in str(s).lower() if c.isalnum() or c in "-_") or "x"

def _legacy_token_file(username):
    """Old scheme: one token file per username, shared across every server."""
    return os.path.join(_app_dir(), f".token_{_safe_part(username)}.json")

def _token_file(host, username):
    """New scheme: one token file per server+username pair, so the same
    username can hold a different, independent token on each server."""
    return os.path.join(_app_dir(),
        f".token_{_safe_part(host)}__{_safe_part(username)}.json")

def _any_token_files_exist():
    """True if at least one token file (old or new naming scheme) already
    exists next to the launcher, regardless of which server/username it's for."""
    try:
        return bool(glob.glob(os.path.join(_app_dir(), ".token_*.json")))
    except Exception:
        return False

def _get_or_create_token(host, username):
    """Returns (token, is_new). is_new is True only the first time this
    server+username pair gets a token file created on this machine."""
    path = _token_file(host, username)
    try:
        d = json.load(open(path))
        if d.get("username","").lower() == username.lower() and d.get("token"):
            return d["token"], False
    except: pass

    # One-time migration: if this username already had a token under the old
    # shared-across-all-servers scheme, reuse it so existing accounts on
    # servers the player already joined don't suddenly stop matching.
    token = None
    try:
        d = json.load(open(_legacy_token_file(username)))
        if d.get("username","").lower() == username.lower() and d.get("token"):
            token = d["token"]
    except: pass

    is_new = token is None
    if token is None:
        token = secrets.token_urlsafe(18)
    try:
        json.dump({"username": username, "host": host, "token": token}, open(path,"w"))
    except: pass
    return token, is_new

def authenticate(host, username, token, password=None, timeout=8):
    payload = {"username": username, "token": token}
    if password is not None:
        payload["password"] = hashlib.sha256(password.encode()).hexdigest()
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((host, AUTH_PORT))
        s.sendall(json.dumps(payload).encode())
        raw = s.recv(4096)
        s.close()
        resp = json.loads(raw.decode())
    except Exception as e:
        return None, f"Cannot reach server at {host}:{AUTH_PORT} — {e}"
    status = resp.get("status")
    if status == "ok":          return resp.get("user_id"), None
    if status == "needs_password": return None, "NEEDS_PASSWORD"
    if status == "wrong_password": return None, "Wrong password."
    if status == "not_whitelisted": return None, "You are not on the whitelist for this server."
    return None, resp.get("message", "Authentication failed.")

def ping_server(host, timeout=5):
    """Returns (info_dict, latency_ms) or raises."""
    t0 = time.time()
    s  = socket.socket()
    s.settimeout(timeout)
    s.connect((host, AUTH_PORT))
    s.sendall(json.dumps({"ping": True}).encode())
    raw = s.recv(4096)
    ms  = int((time.time() - t0) * 1000)
    s.close()
    return json.loads(raw.decode()), ms

# ══════════════════════════════════════════════════════════════════════════════
#  JWT
# ══════════════════════════════════════════════════════════════════════════════

def _b64url(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def _jwt(payload):
    h = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    b = _b64url(json.dumps(payload, separators=(",",":")).encode())
    s = _b64url(_hmac.new(b"offline", f"{h}.{b}".encode(), hashlib.sha256).digest())
    return f"{h}.{b}.{s}"

def build_tokens(user_id, username):
    exp, uid = 9999999999, str(user_id)
    a = _jwt({"UserId":uid,"Username":username,"role":"Access","is_verified":"True",
              "is_member":"True","Policy":["offline","play_offline","server_access_pre_alpha",
              "server_access_tutorial","game_access_public","game_access_development",
              "server_access_development","server_access_testing","game_access_testing",
              "server_owner","debug_features","admin_vr_modes","database_admin",
              "server_create_development","reuse_refresh_tokens"],
              "exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    r = _jwt({"UserId":uid,"role":"Refresh","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    i = _jwt({"UserId":uid,"Username":username,"role":"Identity","is_member":"True",
              "is_dev":"True","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    return a, r, i

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
#  LOG TAILER
# ══════════════════════════════════════════════════════════════════════════════

class GameLogTailer:
    INITIAL_TAIL_LINES = 50
    INITIAL_TAIL_BYTES = 200_000  # generous window to guarantee >= 50 lines of CSV

    def __init__(self, path, on_line, on_status=None):
        self.path, self.on_line, self.on_status = path, on_line, on_status
        self._stop = threading.Event()
    def start(self): threading.Thread(target=self._run, daemon=True).start()
    def stop(self):  self._stop.set()
    def _run(self):
        last, f, buf = -1, None, ""
        while not self._stop.is_set():
            try:
                if not os.path.exists(self.path): time.sleep(1); continue
                sz = os.path.getsize(self.path)
                if f is None or sz < last:
                    if f:
                        try: f.close()
                        except: pass
                    # Show only the tail of existing history instead of reading
                    # the whole file — on a big log that read could take a while.
                    self._emit_initial_tail(sz)
                    f = open(self.path,"r",encoding="utf-8-sig",errors="replace",newline="")
                    f.seek(0, os.SEEK_END)  # we've already shown the history above
                    buf = ""
                    if self.on_status: self.on_status("watching")
                if sz > last:
                    chunk = f.read()
                    if chunk:
                        buf += chunk
                        rows, buf = self._split(buf)
                        if rows: self._emit(rows)
                last = sz
            except: pass
            time.sleep(0.4)
        if f:
            try: f.close()
            except: pass
    def _emit_initial_tail(self, sz):
        """Read just the last chunk of the file (in binary, so an arbitrary
        byte offset is always safe to seek to) and emit only its last
        INITIAL_TAIL_LINES complete rows."""
        try:
            read_from = max(0, sz - self.INITIAL_TAIL_BYTES)
            with open(self.path, "rb") as bf:
                bf.seek(read_from)
                raw = bf.read()
            text = raw.decode("utf-8-sig", errors="replace")
            if read_from > 0:
                # We likely started mid-line — drop the truncated first line.
                nl = text.find("\n")
                text = text[nl+1:] if nl != -1 else ""
            rows, _ = self._split(text)
            tail_rows = rows[-self.INITIAL_TAIL_LINES:]
            if tail_rows: self._emit(tail_rows)
        except Exception:
            pass
    @staticmethod
    def _split(buf):
        recs, i, n, s, q = [], 0, len(buf), 0, False
        while i < n:
            c = buf[i]
            if c == '"': q = not q
            elif c == '\n' and not q: recs.append(buf[s:i+1]); s = i+1
            i += 1
        return recs, buf[s:]
    def _emit(self, rows):
        try:
            for row in csv.reader(io.StringIO("".join(rows))):
                if len(row) >= 4: t,lv,lg,msg = row[0],row[1],row[2],row[3]
                elif len(row)==3: t,lv,lg,msg = row[0],row[1],"",row[2]
                else: continue
                ts = t[11:19] if len(t)>=19 else t
                self.on_line(ts,lv,lg,msg.split("\n",1)[0])
        except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGETS
# ══════════════════════════════════════════════════════════════════════════════

def _divider(parent):
    f = tk.Frame(parent, bg=BG)
    f.pack(fill="x", padx=20, pady=8)
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=6)
    tk.Label(f, text=" ✦ ", bg=BG, fg=AMBERDIM, font=("Georgia",9)).pack(side="left")
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=6)

def _section_label(parent, text):
    tk.Label(parent, text=text, bg=BG, fg=MUTED,
             font=("Georgia",8,"bold")).pack(anchor="w", padx=22, pady=(12,4))

def _field(parent):
    f = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill="x", padx=20, pady=(0,4))
    return f

def _hint(parent, text):
    tk.Label(parent, text=text, bg=BG, fg=MUTED, justify="left",
             font=("Segoe UI",8)).pack(anchor="w", padx=22, pady=(0,4))

def _btn(parent, text, cmd, style="normal", **kw):
    colors = {
        "normal":  (SURF2, PARCH, AMBERDIM, AMBER),
        "primary": ("#3d2a0a", AMBER, "#5a3d0e", "#ffd080"),
        "danger":  ("#3d1010","#e88080","#5a1818","#ffaaaa"),
        "success": ("#1a3d1e","#a8d8a0","#2a5e2e","#c8f0c0"),
        "dim":     (SURF,     MUTED,  SURF2,   PARCH),
    }[style]
    return tk.Button(parent, text=text, bg=colors[0], fg=colors[1],
                     activebackground=colors[2], activeforeground=colors[3],
                     relief="flat", bd=0, cursor="hand2", command=cmd, **kw)

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
    def __init__(self, parent, on_select):
        super().__init__(parent)
        self.title("Community Servers")
        self.configure(bg=BG)
        self.geometry("640x420")
        self.resizable(False, False)
        self._on_select = on_select
        self._servers   = []
        self._build()
        self._refresh()
        _enable_dark_titlebar(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🌍  Community Servers", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        self._status = tk.StringVar(value="Fetching server list…")
        tk.Label(self, textvariable=self._status, bg=BG, fg=MUTED,
                 font=("Segoe UI",9)).pack(anchor="w", padx=20, pady=(8,4))

        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,8))
        self.tree = _mk_tree(lf, ("name","address","players","locked"),
                             [240,170,80,60], height=8, hscroll=True)

        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=20, pady=(0,12))
        _btn(br, "⟳ Refresh", self._refresh, font=("Segoe UI",9),
             pady=6, padx=12).pack(side="left")
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

    def _populate(self):
        for s in self._servers:
            players = f"{s.get('player_count',0)}/{s.get('player_limit',50)}"
            locked  = "🔒" if s.get("has_password") else ""
            self.tree.insert("","end",
                values=(s.get("name","?"), s.get("address","?"), players, locked))
        self._status.set(f"{len(self._servers)} servers listed." if self._servers
                         else "No servers listed yet.")

    def _connect(self):
        sel = self.tree.selection()
        if not sel: return
        idx  = self.tree.index(sel[0])
        srv  = self._servers[idx]
        # "address" is "ip:port" for display — only the host is meaningful to
        # the launcher today, since it always talks to the fixed AUTH_PORT.
        host = srv.get("address","").split(":")[0]
        self._on_select(host, srv.get("name",""))
        self.destroy()

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
            self._on_select(vals[1], vals[0]); self.destroy()

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
            cfg = load_cfg()
            saved = cfg.get("saved_servers", [])
            saved.append({"name": label, "ip": ip})
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
            self._on_select(vals[1], vals[0]); self.destroy()

        def save_fav():
            sel = self.rec_tree.selection()
            if not sel: return
            vals = self.rec_tree.item(sel[0],"values")
            ip, name = vals[1], vals[0]
            # If name is just the IP, ask for a proper label
            if name == ip or not name:
                name = simpledialog.askstring("Save Favourite",
                    f"Label for {ip}:", parent=self) or ip
            cfg = load_cfg()
            saved = cfg.get("saved_servers", [])
            if not any(s["ip"] == ip for s in saved):
                saved.append({"name": name, "ip": ip})
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
        self.title("The Modding Tavern — Client")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.geometry("540x820")
        _set_window_icon(self)
        ttk.Style().theme_use("clam")
        self._tailer      = None
        self._server_ok   = False   # True once Check Server succeeds
        self._checked_host = None
        self._build_ui()
        self._load()
        _enable_dark_titlebar(self)

    # ── UI ─────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._header()

        _section_label(self, "GAME EXECUTABLE")
        pf = _field(self)
        self.v_exe = tk.StringVar()
        tk.Entry(pf, textvariable=self.v_exe, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True)
        _btn(pf, "Browse", self._browse, font=("Segoe UI",9),
             padx=10, pady=6).pack(side="right")
        _hint(self, "Path to 'A Township Tale.exe'")

        _divider(self)

        _section_label(self, "CHOOSE YOUR USERNAME")
        nf = _field(self)
        self.v_username = tk.StringVar()
        tk.Entry(nf, textvariable=self.v_username, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(fill="x")
        _hint(self, "Your save is tied to this name.")

        _section_label(self, "CHOOSE YOUR PLATFORM")
        pf2 = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        pf2.pack(fill="x", padx=20, pady=(0,4))
        self.v_platform = tk.StringVar(value="OpenVR")
        _mk_combobox(pf2, self.v_platform, ["OpenVR","Oculus","none"])
        _hint(self, "OpenVR = SteamVR  ·  Oculus = Quest  ·  none = Flatscreen")

        _divider(self)

        _section_label(self, "DESTINATION")
        sf = _field(self)
        self.v_ip = tk.StringVar()
        self.v_ip.trace_add("write", self._on_ip_changed)
        tk.Entry(sf, textvariable=self.v_ip, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True)

        btn_row_dest = tk.Frame(self, bg=BG)
        btn_row_dest.pack(fill="x", padx=20, pady=(4,0))
        _btn(btn_row_dest, "⚑ Saved",             self._open_server_list,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(btn_row_dest, "🌍 Community Servers", self._open_community,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _hint(self, "Server IP — leave blank for local.")

        # ── Action area ──────────────────────────────────────────────────────
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=10)

        # Status line shown after Check Server — plain label, not a box
        self._check_status = tk.StringVar(value="")
        self._check_label = tk.Label(self, textvariable=self._check_status,
                 bg=BG, fg=MUTED, font=("Segoe UI",9),
                 justify="left", anchor="w", wraplength=480)
        self._check_label.pack(fill="x", padx=22, pady=(0,6))

        # Single button: starts as Check Server, becomes Enter Town after success
        self._action_btn = _btn(self, "🔍  Check Server", self._action,
                                style="primary", font=("Georgia",13,"bold"), pady=14)
        self._action_btn.pack(fill="x", padx=20, pady=(0,4))

        # ── Log ───────────────────────────────────────────────────────────────
        _section_label(self, "GAME LOG")
        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,16))
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

    def _header(self):
        h = tk.Frame(self, bg=SURF, height=64)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Frame(h, bg=AMBER, width=4).pack(side="left", fill="y")
        tk.Label(h, text="⚔", bg=SURF, fg=AMBER,
                 font=("Georgia",22)).pack(side="left", padx=(12,8))
        tf = tk.Frame(h, bg=SURF); tf.pack(side="left")
        tk.Label(tf, text="The Modding Tavern", bg=SURF, fg=AMBER,
                 font=("Georgia",14,"bold")).pack(anchor="w")
        tk.Label(tf, text="Client Launcher", bg=SURF, fg=MUTED,
                 font=("Segoe UI",9)).pack(anchor="w")

        # Token badge — created here but left unpacked; _show_token_button()
        # reveals it once we know a token file exists for the current login.
        self._token_note = (
            "A token file has been created locally in the same folder as this launcher. "
            "This file is used to prove who you are when connecting to this server with "
            "your chosen username. Make sure to keep this file safe, as you won't be able "
            "to connect with this account if it is lost. If you do lose it - please reach "
            "out to the server owner to get it back."
        )
        self._token_animating = False
        self._token_anim_job  = None
        self._token_anim_phase = 0
        self._token_btn = tk.Button(h, text="🔑 Token", bg=SURF2, fg=AMBER,
                                    activebackground=AMBERDIM, activeforeground="#ffd080",
                                    relief="flat", bd=0, cursor="hand2",
                                    font=("Segoe UI",9,"bold"), padx=10, pady=4,
                                    command=self._on_token_button_click)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    # ── Token badge / animation ─────────────────────────────────────────────

    def _show_token_button(self):
        """Reveal the token badge and make sure it's flashing. Called at
        startup if a token file already exists, and after every successful
        connection. Once shown, it keeps flashing for the rest of the
        session — it's meant to keep reminding the player the file exists."""
        if not self._token_btn.winfo_ismapped():
            self._token_btn.pack(in_=self._token_btn.master, side="right", padx=14)
        if not self._token_animating:
            self._start_token_animation()

    def _start_token_animation(self):
        self._token_animating = True
        self._token_anim_phase = 0
        self._animate_token_btn()

    def _animate_token_btn(self):
        if not self._token_animating: return
        bg, fg = (SURF2, AMBER) if self._token_anim_phase % 2 == 0 else ("#5a3d0e", "#ffd080")
        try: self._token_btn.config(bg=bg, fg=fg)
        except Exception: return
        self._token_anim_phase += 1
        self._token_anim_job = self.after(450, self._animate_token_btn)

    def _on_token_button_click(self):
        messagebox.showinfo("About Your Token File", self._token_note, parent=self)

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        cfg = load_cfg()
        self.v_exe.set(cfg.get("game_exe",""))
        self.v_username.set(cfg.get("username",""))
        self.v_platform.set(cfg.get("platform","OpenVR"))
        self.v_ip.set(cfg.get("last_ip",""))
        self._print("Ready. Enter a server IP and press Check Server.", "dim")
        self._start_log_tailer()
        if _any_token_files_exist():
            self._show_token_button()

    def _save(self):
        cfg = load_cfg()
        cfg.update({"game_exe": self.v_exe.get(), "username": self.v_username.get(),
                    "platform": self.v_platform.get(), "last_ip": self.v_ip.get()})
        save_cfg(cfg)

    def _browse(self):
        p = filedialog.askopenfilename(
            title="Select A Township Tale.exe",
            filetypes=[("Executable","*.exe"),("All","*.*")])
        if p: self.v_exe.set(p.replace("/","\\")); self._save()

    def _open_server_list(self):
        def on_select(ip, name):
            self.v_ip.set(ip); self._save()
        ServerListPanel(self, on_select)

    def _open_community(self):
        def on_select(ip, name):
            self.v_ip.set(ip); self._save()
        CommunityBrowser(self, on_select)

    def _on_ip_changed(self, *_):
        """Reset to Check Server state whenever the IP field changes."""
        self._server_ok    = False
        self._checked_host = None
        self._check_status.set("")
        try: self._check_label.config(fg=MUTED)
        except: pass
        self._set_action_mode("check")

    def _set_action_mode(self, mode):
        if mode == "check":
            self._action_btn.config(text="🔍  Check Server",
                                    bg="#3d2a0a", fg=AMBER,
                                    activebackground="#5a3d0e", activeforeground="#ffd080")
            self._check_status.set("")
        else:  # "launch"
            self._action_btn.config(text="⚔   Enter Town",
                                    bg="#1a3d1e", fg="#a8d8a0",
                                    activebackground="#2a5e2e", activeforeground="#c8f0c0")

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

    # ── Action (Check Server / Enter Town) ────────────────────────────────────

    def _action(self):
        if self._server_ok and self._checked_host == (self.v_ip.get().strip() or "127.0.0.1"):
            self._do_launch(password=None)
        else:
            self._do_check()

    def _do_check(self):
        ip   = self.v_ip.get().strip()
        host = ip if ip else "127.0.0.1"
        self._action_btn.config(state="disabled")
        self._check_status.set(f"Checking {host}…")
        try: self._check_label.config(fg=MUTED)
        except: pass
        threading.Thread(target=self._run_check, args=(host,), daemon=True).start()

    def _run_check(self, host):
        try:
            resp, ms = ping_server(host)
            if resp.get("status") == "pong":
                sv_name = resp.get("server_name", host)
                mods    = resp.get("mods", [])
                pw_req  = resp.get("password_required", False)
                wl      = resp.get("whitelist_enabled", False)
                lines   = [f"✔  {sv_name}  —  {ms} ms"]
                flags   = []
                if pw_req: flags.append("🔒 Password required")
                if wl:     flags.append("📋 Whitelist active")
                if flags:  lines.append("  ".join(flags))
                active = [m for m in mods if m.get("enabled")]
                if active:
                    names = ", ".join(m["name"] for m in active[:4])
                    lines.append(f"⚗ Mods: {names}" + ("…" if len(active)>4 else ""))
                else:
                    lines.append("⚗ No mods enforced.")
                msg = "\n".join(lines)
                self.after(0, lambda: self._check_ok(host, msg))
            else:
                self.after(0, lambda: self._check_fail(f"Unexpected response from {host}"))
        except Exception as e:
            self.after(0, lambda: self._check_fail(f"✘  Cannot reach server — {e}"))

    def _check_ok(self, host, msg):
        self._server_ok    = True
        self._checked_host = host
        self._check_status.set(msg)
        self._check_label.config(fg=GREEN)
        self._set_action_mode("launch")
        self._action_btn.config(state="normal")

    def _check_fail(self, msg):
        self._server_ok    = False
        self._checked_host = None
        self._check_status.set(msg)
        self._check_label.config(fg=RED)
        self._set_action_mode("check")
        self._action_btn.config(state="normal")

    # ── Launch ────────────────────────────────────────────────────────────────

    def _do_launch(self, password, _token_state=None):
        exe      = self.v_exe.get().strip()
        username = self.v_username.get().strip()
        platform = self.v_platform.get()
        ip       = self.v_ip.get().strip()
        host     = ip if ip else "127.0.0.1"

        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Not found",
                "Could not find the game.\nPlease browse to 'A Township Tale.exe'.")
            return
        if not username:
            messagebox.showerror("Missing name",
                "Please enter your username before connecting.")
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
        sv_name = host
        status_text = self._check_status.get()
        if status_text.startswith("✔"):
            # Parse the server name out of the status line "✔  ServerName  —  Xms"
            try: sv_name = status_text.split("✔")[1].split("—")[0].strip()
            except: pass
        recent = [r for r in cfg.get("recent_servers",[]) if r.get("ip") != host]
        recent.insert(0, {"name": sv_name, "ip": host})
        cfg["recent_servers"] = recent[:20]
        save_cfg(cfg)

        access, refresh, identity = build_tokens(user_id, username)
        args = [exe, "/force_offline",
                "/access_token", access, "/refresh_token", refresh,
                "/identity_token", identity, "/join_local_server"]

        if platform == "none":
            args.insert(-1, "/fly")
        elif platform:
            args[-1:] = ["/vrmode", platform, "/join_local_server"]
        if ip:
            args += ["/dev_server_ip", ip]

        self._print(f"Launching on {platform or 'default'}…", "warn")
        try:
            proc = subprocess.Popen(args, cwd=os.path.dirname(exe),
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self._print(f"Game running (PID {proc.pid})", "ok")
        except Exception as e:
            self._print(f"Launch failed: {e}", "err")
        self._action_btn.config(state="normal")


if __name__ == "__main__":
    app = ClientLauncher()
    app.mainloop()
