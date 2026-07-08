"""
The Modding Tavern — Server Launcher
"""

import sys, os, subprocess, threading, time, csv, io, json, socket, hashlib, secrets
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import base64, hmac as _hmac, tempfile, struct, ctypes, urllib.request, urllib.error

# ══════════════════════════════════════════════════════════════════════════════
#  DARK TITLE BAR  (Windows 10/11 — safe no-op elsewhere)
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

# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════

def _app_dir():
    if getattr(sys,"frozen",False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

GAME_LOG_PATH  = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Logs","logs","unity-log.csv")
PLAYERS_SAVE   = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Save","Players")
USERS_FILE     = os.path.join(_app_dir(),"users.json")
BLACKLIST_FILE = os.path.join(_app_dir(),"blacklist.json")
WHITELIST_FILE = os.path.join(_app_dir(),"whitelist.json")
SERVER_CFG     = os.path.join(_app_dir(),"server_settings.json")
MODS_STATE     = os.path.join(_app_dir(),"mods_state.json")
CONFIG_FILE    = os.path.join(os.path.expanduser("~"),".tavern_server.json")
AUTH_PORT      = 1762
CONSOLE_PORT   = 1758
BASE_USER_ID   = 2000000000

# Community server list backend — the small Flask app the server owner runs
# at home (see community_server.py). Registration (POST) and unregistration
# (DELETE) both go here; the same URL is used for GET on the client side.
COMMUNITY_API = "http://themoddingtavern.com:1763/servers"
COMMUNITY_HEARTBEAT_SECONDS = 120

def load_cfg():
    try: return json.load(open(CONFIG_FILE))
    except: return {}
def save_cfg(d):
    try: json.dump(d,open(CONFIG_FILE,"w"),indent=2)
    except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  MODS  (module-level so auth ping can report them)
# ══════════════════════════════════════════════════════════════════════════════

_DEFAULT_MODS = [
    {"name": "Placeholder 1", "author": "TavernDev", "version": "0.0.1", "enabled": False},
    {"name": "Placeholder 2", "author": "TavernDev", "version": "0.0.1", "enabled": False},
]

def load_mods():
    try:
        saved = json.load(open(MODS_STATE))
        # Merge saved enabled states into defaults (handles new mods being added)
        state = {m["name"]: m["enabled"] for m in saved}
        result = []
        for m in _DEFAULT_MODS:
            mod = m.copy()
            if m["name"] in state:
                mod["enabled"] = state[m["name"]]
            result.append(mod)
        return result
    except:
        return [m.copy() for m in _DEFAULT_MODS]

def save_mods(mods):
    try: json.dump(mods, open(MODS_STATE,"w"), indent=2)
    except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  SERVER SETTINGS
# ══════════════════════════════════════════════════════════════════════════════

def load_server_settings():
    try: return json.load(open(SERVER_CFG))
    except: return {"name":"My Tavern Server","password_hash":"","whitelist_enabled":False}

def save_server_settings(d):
    try: json.dump(d,open(SERVER_CFG,"w"),indent=2)
    except: pass

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
#  USER DB / BLACKLIST / WHITELIST
# ══════════════════════════════════════════════════════════════════════════════

_users_lock = threading.Lock()

def _load_users():
    try: return json.load(open(USERS_FILE))
    except: return {}
def _save_users(u):
    try: json.dump(u,open(USERS_FILE,"w"),indent=2)
    except: pass

def _load_bl():
    try:
        d = json.load(open(BLACKLIST_FILE))
        d.setdefault("usernames",[]); d.setdefault("user_ids",[]); d.setdefault("ips",[])
        return d
    except: return {"usernames":[],"user_ids":[],"ips":[]}
def _save_bl(d):
    try: json.dump(d,open(BLACKLIST_FILE,"w"),indent=2)
    except: pass

def _load_wl():
    try:
        d = json.load(open(WHITELIST_FILE))
        d.setdefault("usernames",[]); d.setdefault("ips",[])
        return d
    except: return {"usernames":[],"ips":[]}
def _save_wl(d):
    try: json.dump(d,open(WHITELIST_FILE,"w"),indent=2)
    except: pass

def _is_blacklisted(username, user_id, ip):
    bl = _load_bl()
    if username and username.lower() in [u.lower() for u in bl["usernames"]]: return True
    if user_id is not None and user_id in bl["user_ids"]: return True
    if ip and ip in bl["ips"]: return True
    return False

def _is_whitelisted(username, ip):
    ss = load_server_settings()
    if not ss.get("whitelist_enabled"): return True
    wl = _load_wl()
    if username and username.lower() in [u.lower() for u in wl["usernames"]]: return True
    if ip and ip in wl["ips"]: return True
    return False

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
        token_file = os.path.join(_app_dir(), "console_token.txt")
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
        out, err = _console.send_command(f"player ban {username}")
    else:
        out, err = _console.send_command(f"player kick {username}")
    _console.disconnect()
    if err: return False, err
    return True, out or "Done"

# ══════════════════════════════════════════════════════════════════════════════
#  AUTH SERVICE
# ══════════════════════════════════════════════════════════════════════════════

_fail_counts = {}
_fail_lock   = threading.Lock()
FAIL_LIMIT, FAIL_WINDOW = 8, 60
MAX_ACCOUNTS_PER_IP  = 5     # max new accounts one IP can register
PW_FAIL_LIMIT        = 5     # wrong-password attempts before IP throttle tightens

def _throttle_ok(ip):
    now = time.time()
    with _fail_lock:
        c, last = _fail_counts.get(ip,(0,0))
        if now-last > FAIL_WINDOW: c = 0
        return c < FAIL_LIMIT

def _record_fail(ip):
    now = time.time()
    with _fail_lock:
        c, last = _fail_counts.get(ip,(0,0))
        if now-last > FAIL_WINDOW: c = 0
        _fail_counts[ip] = (c+1,now)

_pw_fail_counts = {}   # separate tracker for wrong-password attempts

def _record_pw_fail(ip):
    now = time.time()
    with _fail_lock:
        c, last = _pw_fail_counts.get(ip,(0,0))
        if now-last > FAIL_WINDOW: c = 0
        _pw_fail_counts[ip] = (c+1,now)

def _pw_throttle_ok(ip):
    now = time.time()
    with _fail_lock:
        c, last = _pw_fail_counts.get(ip,(0,0))
        if now-last > FAIL_WINDOW: c = 0
        return c < PW_FAIL_LIMIT

def _handle_auth(conn, addr, log_fn):
    ip = addr[0] if addr else "?"
    try:
        conn.settimeout(5)
        if not _throttle_ok(ip):
            conn.sendall(json.dumps({"status":"error","message":"Too many attempts."}).encode())
            return
        data = conn.recv(4096)
        if not data: return
        req = json.loads(data.decode())

        # ── ping / info probe ──
        if req.get("ping"):
            ss   = load_server_settings()
            mods = load_mods()
            conn.sendall(json.dumps({
                "status":            "pong",
                "server_name":       ss.get("name","Tavern Server"),
                "password_required": bool(ss.get("password_hash","")),
                "whitelist_enabled": bool(ss.get("whitelist_enabled",False)),
                "mods": [{"name":m["name"],"enabled":m["enabled"]} for m in mods],
            }).encode())
            return

        username = str(req.get("username","")).strip()
        token    = str(req.get("token","")).strip()
        pw_hash  = str(req.get("password","")).strip()

        if not username or not token:
            conn.sendall(json.dumps({"status":"error","message":"Missing credentials."}).encode())
            return

        if _is_blacklisted(username, None, ip):
            log_fn(f"Blocked (blacklist): '{username}' from {ip}", "err")
            conn.sendall(json.dumps({"status":"error","message":"You are not permitted."}).encode())
            return

        ss = load_server_settings()
        stored_pw = ss.get("password_hash","").strip()
        if stored_pw:
            if not pw_hash:
                conn.sendall(json.dumps({"status":"needs_password"}).encode())
                return
            # Check password brute-force throttle before even validating
            if not _pw_throttle_ok(ip):
                conn.sendall(json.dumps({"status":"error",
                    "message":"Too many failed password attempts. Try again later."}).encode())
                return
            if hashlib.sha256(pw_hash.encode()).hexdigest() != stored_pw:
                _record_pw_fail(ip)
                _record_fail(ip)
                remaining = max(0, PW_FAIL_LIMIT - _pw_fail_counts.get(ip,(0,0))[0])
                log_fn(f"Wrong password: '{username}' from {ip} ({remaining} attempts left)", "warn")
                conn.sendall(json.dumps({"status":"wrong_password",
                    "message": f"Wrong password. {remaining} attempt(s) remaining."}).encode())
                return

        if not _is_whitelisted(username, ip):
            log_fn(f"Blocked (whitelist): '{username}' from {ip}", "warn")
            conn.sendall(json.dumps({"status":"not_whitelisted",
                                      "message":"You are not on the whitelist."}).encode())
            return

        key = username.lower()
        with _users_lock:
            users = _load_users()
            if key in users:
                entry = users[key]
                stored_token = str(entry.get("token") or "")
                if stored_token == "":
                    # Token was reset by an admin — claim it for whoever connects
                    # next with this username, so a lost token can be recovered.
                    entry["token"] = token
                    entry["registered_from"] = ip
                    users[key] = entry
                    _save_users(users)
                    user_id = entry["user_id"]
                    log_fn(f"Token re-claimed: '{username}' (ID {user_id}) from {ip}", "ok")
                elif stored_token != token:
                    _record_fail(ip)
                    log_fn(f"Token mismatch: '{username}' from {ip}", "warn")
                    conn.sendall(json.dumps({"status":"error",
                        "message":"That name is taken by someone else."}).encode())
                    return
                else:
                    user_id = entry["user_id"]
            else:
                # Per-IP registration limit — prevent one IP flooding with accounts
                ip_count = sum(1 for u in users.values() if u.get("registered_from") == ip)
                if ip_count >= MAX_ACCOUNTS_PER_IP:
                    _record_fail(ip)
                    log_fn(f"Registration limit hit: {ip} already has {ip_count} accounts", "warn")
                    conn.sendall(json.dumps({"status":"error",
                        "message":"Too many accounts registered from your address."}).encode())
                    return
                existing = [u["user_id"] for u in users.values()]
                user_id  = max(existing, default=BASE_USER_ID) + 1
                users[key] = {"user_id": user_id, "token": token, "registered_from": ip}
                _save_users(users)
                log_fn(f"New player: '{username}' (ID {user_id}) from {ip}", "ok")

        if _is_blacklisted(username, user_id, ip):
            conn.sendall(json.dumps({"status":"error","message":"You are not permitted."}).encode())
            return

        log_fn(f"'{username}' (ID {user_id}) from {ip}", "ok")
        conn.sendall(json.dumps({"status":"ok","user_id":user_id}).encode())
    except Exception as e:
        try: conn.sendall(json.dumps({"status":"error","message":str(e)}).encode())
        except: pass
        log_fn(f"Auth error: {e}", "err")
    finally:
        try: conn.close()
        except: pass

def start_auth_service(log_fn, port=AUTH_PORT):
    def serve():
        try:
            s = socket.socket()
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", port)); s.listen(8)
            log_fn(f"Auth service listening on :{port}", "dim")
            while True:
                conn, addr = s.accept()
                threading.Thread(target=_handle_auth,
                                  args=(conn,addr,log_fn), daemon=True).start()
        except Exception as e:
            log_fn(f"Auth service failed: {e}", "err")
    threading.Thread(target=serve, daemon=True).start()

# ══════════════════════════════════════════════════════════════════════════════
#  JWT
# ══════════════════════════════════════════════════════════════════════════════

def _b64url(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def _jwt(payload):
    h = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    b = _b64url(json.dumps(payload,separators=(",",":")).encode())
    s = _b64url(_hmac.new(b"offline",f"{h}.{b}".encode(),hashlib.sha256).digest())
    return f"{h}.{b}.{s}"

def build_server_tokens():
    exp = 9999999999
    a = _jwt({"UserId":"0","Username":"Server","role":"Access","is_verified":"True",
              "is_member":"True","Policy":["offline","play_offline","server_access_pre_alpha",
              "game_access_public","server_owner","debug_features","database_admin",
              "reuse_refresh_tokens"],"exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    r = _jwt({"UserId":"0","role":"Refresh","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    i = _jwt({"UserId":"0","Username":"Server","role":"Identity","is_member":"True",
              "is_dev":"True","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    return a, r, i

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
            elif c == '\n' and not q: recs.append(buf[s:i+1]); s=i+1
            i += 1
        return recs, buf[s:]
    def _emit(self, rows):
        try:
            for row in csv.reader(io.StringIO("".join(rows))):
                if len(row)>=4: t,lv,lg,msg = row[0],row[1],row[2],row[3]
                elif len(row)==3: t,lv,lg,msg = row[0],row[1],"",row[2]
                else: continue
                ts = t[11:19] if len(t)>=19 else t
                self.on_line(ts,lv,lg,msg.split("\n",1)[0])
        except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  ICON
# ══════════════════════════════════════════════════════════════════════════════
_ICON_B64 = None
try:
    from icon_data import ICON_B64 as _ICON_B64
except ImportError: pass

def _set_window_icon(root):
    if not _ICON_B64: return
    try:
        tmp = os.path.join(tempfile.gettempdir(), "tavern_icon.ico")
        with open(tmp,"wb") as f: f.write(base64.b64decode(_ICON_B64))
        root.iconbitmap(tmp)
    except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  WIDGET HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _divider(parent):
    f = tk.Frame(parent, bg=BG)
    f.pack(fill="x", padx=20, pady=6)
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=6)
    tk.Label(f, text=" ✦ ", bg=BG, fg=AMBERDIM, font=("Georgia",9)).pack(side="left")
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=6)

def _section_label(parent, text):
    tk.Label(parent, text=text, bg=BG, fg=MUTED,
             font=("Georgia",8,"bold")).pack(anchor="w", padx=22, pady=(10,3))

def _field(parent):
    f = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill="x", padx=20, pady=(0,3))
    return f

def _hint(parent, text, wraplength=380):
    tk.Label(parent, text=text, bg=BG, fg=MUTED, justify="left",
             wraplength=wraplength,
             font=("Segoe UI",8)).pack(anchor="w", padx=22, pady=(0,3))

def _btn(parent, text, cmd, style="normal", **kw):
    colors = {
        "normal":  (SURF2, PARCH, AMBERDIM, AMBER),
        "primary": ("#3d2a0a", AMBER, "#5a3d0e","#ffd080"),
        "danger":  ("#3d1010","#e88080","#5a1818","#ffaaaa"),
        "success": ("#1a3d1e","#a8d8a0","#2a5e2e","#c8f0c0"),
    }[style]
    return tk.Button(parent, text=text, bg=colors[0], fg=colors[1],
                     activebackground=colors[2], activeforeground=colors[3],
                     relief="flat", bd=0, cursor="hand2", command=cmd, **kw)

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

    def _refresh_blacklist(self): self._refresh_bllist()
    def _refresh_whitelist(self): self._refresh_wllist()

# ══════════════════════════════════════════════════════════════════════════════
#  MODS WINDOW
# ══════════════════════════════════════════════════════════════════════════════

class ModsWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("Mods")
        self.configure(bg=BG)
        self.geometry("560x320")
        self.resizable(False, False)
        _set_window_icon(self)
        self._mods = load_mods()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _enable_dark_titlebar(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚗  Installed Mods", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        tk.Label(self,
            text="Mods listed here will be enforced on connecting clients.",
            bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=520
        ).pack(anchor="w", padx=20, pady=(10,6))
        lf = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        lf.pack(fill="x", padx=20, pady=(0,8))
        style = ttk.Style()
        style.configure("Mod.Treeview", background=SURF, fieldbackground=SURF,
                        foreground=PARCH, rowheight=26)
        style.configure("Mod.Treeview.Heading", background=SURF2, foreground=AMBER,
                        font=("Georgia",9,"bold"))
        style.map("Mod.Treeview",
                  background=[("selected",AMBERDIM)],
                  foreground=[("selected","#ffd080")])
        self.tree = ttk.Treeview(lf, columns=("status","name","author","version"),
                                  show="headings", selectmode="browse",
                                  height=4, style="Mod.Treeview")
        self.tree.heading("status",  text="")
        self.tree.heading("name",    text="Mod Name")
        self.tree.heading("author",  text="Author")
        self.tree.heading("version", text="Version")
        self.tree.column("status",  width=36, anchor="center")
        self.tree.column("name",    width=220)
        self.tree.column("author",  width=140)
        self.tree.column("version", width=80, anchor="center")
        sb = _mk_scrollbar(lf, self.tree.yview)
        sb.pack(side="right", fill="y")
        self.tree.config(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True, padx=2, pady=2)
        self._populate()
        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=20, pady=(0,14))
        _btn(br, "✔ Enable",  self._enable,  "success",
             font=("Segoe UI",9), pady=6, padx=12).pack(side="left")
        _btn(br, "✘ Disable", self._disable, "danger",
             font=("Segoe UI",9), pady=6, padx=12).pack(side="left", padx=6)
        tk.Label(br, text="Changes are saved automatically.",
                 bg=BG, fg=MUTED, font=("Segoe UI",8)).pack(side="right")

    def _populate(self):
        for r in self.tree.get_children(): self.tree.delete(r)
        for i, m in enumerate(self._mods):
            self.tree.insert("","end", iid=str(i),
                values=("●" if m["enabled"] else "○", m["name"], m["author"], m["version"]))

    def _toggle(self, enabled):
        sel = self.tree.selection()
        if not sel: return
        idx = int(sel[0])
        self._mods[idx]["enabled"] = enabled
        save_mods(self._mods)
        self._populate()
        self.tree.selection_set(str(idx))

    def _enable(self):  self._toggle(True)
    def _disable(self): self._toggle(False)

    def _on_close(self):
        save_mods(self._mods)
        self.destroy()

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
        _hint(self, "Shown to players who check your server.")
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
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(10,6))
        _btn(self, "💾  Save Settings", self._save, "primary",
             font=("Georgia",11,"bold"), pady=12).pack(fill="x", padx=20, pady=(0,16))

    def _clear_pw(self):
        ss = load_server_settings()
        ss["password_hash"] = ""
        save_server_settings(ss)
        self._pw_hint.set("○ No password set.")
        messagebox.showinfo("Cleared", "Password removed.")

    def _save(self):
        ss = load_server_settings()
        ss["name"] = self.v_name.get().strip() or "My Tavern Server"
        ss["whitelist_enabled"] = self.v_whitelist.get()
        ss["community_listed"] = self.v_community.get()
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
        self.title("The Modding Tavern — Server")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.geometry("560x760")
        _set_window_icon(self)
        ttk.Style().theme_use("clam")
        self._proc     = None
        self._auth_on  = False
        self._tailer   = None
        self._mgr_win  = None
        self._mods_win = None
        self._sett_win = None
        self._community_registered = False
        self._community_stop = threading.Event()
        self._community_thread = None
        self._build_ui()
        self._load()
        self._start_log_tailer()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        _enable_dark_titlebar(self)

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
        _btn(tr, "⚗ Mods",     self._open_mods,     font=("Segoe UI",9),
             pady=7, padx=12).pack(side="left")
        _btn(tr, "📁 Saves",    self._open_saves,    font=("Segoe UI",9),
             pady=7, padx=12).pack(side="right")
        _divider(self)
        sf = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        sf.pack(fill="x", padx=20, pady=(0,10))
        self._dot = tk.Canvas(sf, width=10, height=10, bg=SURF, highlightthickness=0)
        self._dot.pack(side="left", padx=(10,6), pady=10)
        self._dot.create_oval(1,1,9,9, fill=MUTED, outline="", tags="dot")
        self._status_var = tk.StringVar(value="Offline")
        tk.Label(sf, textvariable=self._status_var, bg=SURF, fg=MUTED,
                 font=("Segoe UI",10)).pack(side="left")
        self._pid_var = tk.StringVar()
        tk.Label(sf, textvariable=self._pid_var, bg=SURF, fg=AMBERDIM,
                 font=MONO).pack(side="right", padx=10)
        bf = tk.Frame(self, bg=BG)
        bf.pack(fill="x", padx=20, pady=(0,10))
        self._btn_start = _btn(bf, "⚔   Open Server", self._start, "success",
                               font=("Georgia",12,"bold"), pady=12)
        self._btn_start.pack(fill="x", pady=(0,6))
        self._btn_stop = _btn(bf, "✕   Close Server", self._stop, "danger",
                              font=("Georgia",12,"bold"), pady=12)
        self._btn_stop.pack(fill="x")
        self._btn_stop.config(state="disabled")
        _section_label(self, "SERVER LOG")
        lf = tk.Frame(self, bg=BG)
        lf.pack(fill="both", expand=True, padx=20, pady=(0,16))
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

    def _header(self):
        h = tk.Frame(self, bg=SURF, height=64)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Frame(h, bg=AMBER, width=4).pack(side="left", fill="y")
        tk.Label(h, text="⚒", bg=SURF, fg=AMBER,
                 font=("Georgia",22)).pack(side="left", padx=(12,8))
        tf = tk.Frame(h, bg=SURF); tf.pack(side="left")
        tk.Label(tf, text="The Modding Tavern", bg=SURF, fg=AMBER,
                 font=("Georgia",14,"bold")).pack(anchor="w")
        tk.Label(tf, text="Server Launcher", bg=SURF, fg=MUTED,
                 font=("Segoe UI",9)).pack(anchor="w")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _load(self):
        cfg = load_cfg()
        self.v_exe.set(cfg.get("server_exe",""))
        self.v_port.set(cfg.get("server_port","1757"))
        ss = load_server_settings()
        self._sv_name_var.set(ss.get("name","—"))
        self._print("Tavern server ready.", "ok")
        self._print("Set game exe and click Open Server.", "dim")

    def _save(self):
        save_cfg({**load_cfg(), "server_exe": self.v_exe.get(),
                  "server_port": self.v_port.get()})

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

    def _open_mods(self):
        if self._mods_win and self._mods_win.winfo_exists():
            self._mods_win.lift(); return
        self._mods_win = ModsWindow(self)

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
            with open(os.path.join(_app_dir(),"console_token.txt"),"w") as f:
                f.write(access)
        except: pass
        if not self._auth_on:
            start_auth_service(self._print)
            self._auth_on = True
        args = [exe, "/force_offline",
                "/access_token", access, "/refresh_token", refresh,
                "/identity_token", identity,
                "-batchmode", "-nographics", "/fly",
                "/start_server", "-1", "false", str(port)]
        self._print(f"Opening server on port {port}…", "warn")
        try:
            self._proc = subprocess.Popen(args, cwd=os.path.dirname(exe),
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
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
        }
        try:
            req = urllib.request.Request(COMMUNITY_API,
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json",
                         "User-Agent": "TavernServer/1.0"},
                method="POST")
            urllib.request.urlopen(req, timeout=8).read()
            if log: self._print("Listed on the community server list.", "ok")
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
    app = ServerLauncher()
    app.mainloop()
