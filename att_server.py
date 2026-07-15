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

import sys, os, subprocess, threading, time, csv, io, json, socket, hashlib, secrets, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import base64, hmac as _hmac, tempfile, struct, ctypes, urllib.request, urllib.error, contextlib
import zipfile, shutil
import http.client
from urllib.parse import urlparse

_updater = None
try:
    import updater as _updater
except ImportError:
    pass

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

def _tavern_data_dir():
    """The one shared place this launcher's own persistent data lives —
    config, the player database, whitelist/blacklist, the console token —
    regardless of which folder the exe itself happens to be running from.
    Means downloading a new build to a different folder, or a fresh
    install replacing the old one, never requires manually moving files
    over; they were never next to the exe in the first place. (The Patch/
    folder deliberately stays where it is — it ships fresh with every
    release, so it never has this problem to begin with.)"""
    base = os.environ.get("APPDATA", os.path.join(os.path.expanduser("~"), "AppData", "Roaming"))
    path = os.path.join(base, "TheModdingTavern")
    try: os.makedirs(path, exist_ok=True)
    except Exception: pass
    return path

def _migrate_legacy_file(old_path, new_path):
    """One-time move from before file storage was unified into
    _tavern_data_dir(). Safe to call every startup — a no-op once the file
    has already been moved, or if it never existed at the old location."""
    try:
        if os.path.isfile(old_path) and not os.path.isfile(new_path):
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            shutil.move(old_path, new_path)
    except Exception:
        pass

GAME_LOG_PATH  = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Logs","logs","unity-log.csv")
PLAYERS_SAVE   = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Save","Players")
USERS_FILE     = os.path.join(_tavern_data_dir(),"users.json")
BLACKLIST_FILE = os.path.join(_tavern_data_dir(),"blacklist.json")
WHITELIST_FILE = os.path.join(_tavern_data_dir(),"whitelist.json")
SERVER_CFG     = os.path.join(_tavern_data_dir(),"server_settings.json")
CONFIG_FILE    = os.path.join(_tavern_data_dir(),"tavern_server.json")
CONSOLE_TOKEN_FILE = os.path.join(_tavern_data_dir(),"console_token.txt")
for _old, _new in (
    (os.path.join(_app_dir(),"users.json"), USERS_FILE),
    (os.path.join(_app_dir(),"blacklist.json"), BLACKLIST_FILE),
    (os.path.join(_app_dir(),"whitelist.json"), WHITELIST_FILE),
    (os.path.join(_app_dir(),"server_settings.json"), SERVER_CFG),
    (os.path.join(os.path.expanduser("~"),".tavern_server.json"), CONFIG_FILE),
    (os.path.join(_app_dir(),"console_token.txt"), CONSOLE_TOKEN_FILE),
):
    _migrate_legacy_file(_old, _new)
AUTH_PORT      = 1762
CONSOLE_PORT   = 1758
BASE_USER_ID   = 2000000000
USERNAME_MAX_LEN = 16

# Community server list backend — the small Flask app the server owner runs
# at home (see community_server.py). Registration (POST) and unregistration
# (DELETE) both go here; the same URL is used for GET on the client side.
COMMUNITY_API = "http://themoddingtavern.com:1763/servers"
COMMUNITY_HEARTBEAT_SECONDS = 120
DISCORD_URL   = "https://discord.gg/jNQUUDAYSj"

def load_cfg():
    try: return json.load(open(CONFIG_FILE))
    except: return {}
def save_cfg(d):
    try: json.dump(d,open(CONFIG_FILE,"w"),indent=2)
    except: pass

# ══════════════════════════════════════════════════════════════════════════════
#  MODS  (module-level so auth ping can report them)
# ══════════════════════════════════════════════════════════════════════════════


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

# ── Live player count ────────────────────────────────────────────────────────
# The Python launcher has no visibility into the actual game process's
# runtime state — it only gatekeeps the initial auth handshake, then the
# game runs on its own. Real player counts have to come from something
# running *inside* the game process instead, e.g. a MelonLoader/TavernLib
# plugin, which can read them directly off the game's own ServerHandler
# (decompiled source confirms: ServerHandler.Current.Connections is the
# live count, ServerHandler.Current.PlayerLimit is the configured max —
# both are plain public properties on a static singleton).
#
# The integration point this expects: such a mod periodically writes
#   {"player_count": <int>, "player_limit": <int>}
# to PLAYER_STATUS_FILENAME in the shared %AppData%\TheModdingTavern folder
# (same place everything else this launcher owns lives — see
# _tavern_data_dir()), not anywhere relative to the game's own install. If
# that file doesn't exist, or hasn't been updated recently, this reports
# "unknown" rather than a stale/fake number.
PLAYER_STATUS_FILENAME = "tavern_player_status.json"
PLAYER_STATUS_MAX_AGE_SECONDS = 60

def _read_live_player_status():
    """Returns (player_count, player_limit), each an int or None if not
    available (file missing, malformed, or too old to trust)."""
    path = os.path.join(_tavern_data_dir(), PLAYER_STATUS_FILENAME)
    try:
        if time.time() - os.path.getmtime(path) > PLAYER_STATUS_MAX_AGE_SECONDS:
            return None, None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        count = data.get("player_count")
        limit = data.get("player_limit")
        count = int(count) if isinstance(count, (int, float)) else None
        limit = int(limit) if isinstance(limit, (int, float)) else None
        return count, limit
    except Exception:
        return None, None

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
            cfg  = load_cfg()
            try: game_port = int(cfg.get("server_port", 1757))
            except (TypeError, ValueError): game_port = 1757
            resp = {
                "status":            "pong",
                "server_name":       ss.get("name","Tavern Server"),
                "password_required": bool(ss.get("password_hash","")),
                "whitelist_enabled": bool(ss.get("whitelist_enabled",False)),
                "game_port":         game_port,
            }
            live_count, live_limit = _read_live_player_status()
            if live_count is not None: resp["player_count"] = live_count
            if live_limit is not None and live_limit > 0: resp["player_limit"] = live_limit
            conn.sendall(json.dumps(resp).encode())
            return

        username = str(req.get("username","")).strip()
        token    = str(req.get("token","")).strip()
        pw_hash  = str(req.get("password","")).strip()

        if not username or not token:
            conn.sendall(json.dumps({"status":"error","message":"Missing credentials."}).encode())
            return

        if len(username) > USERNAME_MAX_LEN:
            log_fn(f"Blocked (name too long): '{username[:USERNAME_MAX_LEN]}…' from {ip}", "warn")
            conn.sendall(json.dumps({"status":"error",
                "message": f"Usernames can be at most {USERNAME_MAX_LEN} characters."}).encode())
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
                # Per-IP registration limit — prevent one IP flooding with
                # accounts. Toggleable in Server Settings, defaults to on.
                if ss.get("enforce_ip_limit", True):
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

def _divider(parent):
    f = tk.Frame(parent, bg=BG)
    f.pack(fill="x", padx=20, pady=5)
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=4)
    tk.Label(f, text=" ✦ ", bg=BG, fg=AMBERDIM, font=("Georgia",9)).pack(side="left")
    tk.Frame(f, bg=BORDER, height=1).pack(side="left", fill="x", expand=True, pady=4)

def _section_label(parent, text):
    tk.Label(parent, text=text, bg=BG, fg=MUTED,
             font=("Georgia",8,"bold")).pack(anchor="w", padx=22, pady=(7,3))

def _field(parent):
    f = tk.Frame(parent, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
    f.pack(fill="x", padx=20, pady=(0,3))
    return f

def _hint(parent, text, wraplength=380):
    tk.Label(parent, text=text, bg=BG, fg=MUTED, justify="left",
             wraplength=wraplength,
             font=("Segoe UI",8)).pack(anchor="w", padx=22, pady=(0,2))

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

    def _refresh_blacklist(self): self._refresh_bllist()
    def _refresh_whitelist(self): self._refresh_wllist()


# ══════════════════════════════════════════════════════════════════════════════
#  MOD INSTALLATION  (MelonLoader + TavernLib)
# ══════════════════════════════════════════════════════════════════════════════

# The official MelonLoader project (Apache-2.0, github.com/LavaGang/MelonLoader)
# publishes these exact "always the latest release" download links itself —
# it's the same URL their own install guide points people to, just automated
# here instead of asking the player to click it. Note the org name: LavaGang,
# no hyphen — there are copy-cat repos with similar names floating around
# that should NOT be used as a source for this.
MELONLOADER_ZIP_URLS = {
    "x64": "https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x64.zip",
    "x86": "https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x86.zip",
}

# Fill this in with wherever you host TavernLib releases — a GitHub Releases
# asset URL or a raw.githubusercontent.com link both work fine, since this is
# just downloaded as a plain file.
TAVERNLIB_DOWNLOAD_URL = "https://github.com/ModdingTavern/TavernLib/releases/latest/download/TavernLib.dll"
TAVERNLIB_FILENAME = "TavernLib.dll"

# A small marker file dropped next to the game exe recording what we last
# installed, so later we can tell "outdated" apart from "never checked".
MODS_META_FILENAME = ".tavern_mods_meta.json"


def _mods_meta_path(game_dir):
    return os.path.join(game_dir, MODS_META_FILENAME)


def _load_mod_meta(game_dir):
    try:
        with open(_mods_meta_path(game_dir), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_mod_meta(game_dir, meta):
    try:
        with open(_mods_meta_path(game_dir), "w", encoding="utf-8") as f:
            json.dump(meta, f)
    except Exception:
        pass


def _get_redirect_location(url, timeout=10):
    """HEAD-requests a URL and returns the Location header of the *first*
    redirect hop, without following it. Used to read a GitHub 'latest
    release' download alias's resolved tag (e.g. 'v0.7.3') straight out of
    the redirect target, without downloading anything."""
    parsed = urlparse(url)
    conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    with _force_ipv4():
        conn = conn_cls(parsed.netloc, timeout=timeout)
        try:
            path = parsed.path + (("?" + parsed.query) if parsed.query else "")
            conn.request("HEAD", path, headers={"User-Agent": "TavernLauncher/1.0",
                                                 "Host": parsed.netloc})
            resp = conn.getresponse()
            resp.read()
            if 300 <= resp.status < 400:
                return resp.getheader("Location")
            return None
        finally:
            conn.close()


def _get_melonloader_latest_tag():
    """Reads the current MelonLoader release tag (e.g. 'v0.7.3') from the
    redirect target of its 'latest' download alias — no GitHub API call,
    no rate limit, and no need to download the (large) release zip."""
    loc = _get_redirect_location(
        "https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x64.zip")
    if not loc:
        return None
    # .../releases/download/v0.7.3/MelonLoader.x64.zip -> "v0.7.3"
    parts = loc.rstrip("/").split("/")
    try:
        return parts[parts.index("download") + 1]
    except (ValueError, IndexError):
        return None


def _fetch_remote_fingerprint(url, timeout=10):
    """A lightweight 'has this file changed' check — HEAD for ETag (falls
    back to Last-Modified, then Content-Length), without downloading the
    file. Needed for TavernLib specifically because its releases stay on a
    single tag name that never changes, so tag comparison can't detect
    updates the way it can for MelonLoader."""
    def _read(resp):
        h = resp.headers
        return h.get("ETag") or h.get("Last-Modified") or h.get("Content-Length") or ""
    with _force_ipv4():
        req = urllib.request.Request(url, method="HEAD",
            headers={"User-Agent": "TavernLauncher/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                fp = _read(resp)
                if fp: return fp
        except Exception:
            pass
        # Fallback for hosts that don't support HEAD on the (often presigned)
        # redirect target: a 1-byte ranged GET still reveals the same headers.
        req = urllib.request.Request(url, headers={
            "User-Agent": "TavernLauncher/1.0", "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return _read(resp)


def _detect_exe_arch(exe_path):
    """Reads the PE header to tell whether the game exe is 32- or 64-bit,
    so we grab the matching MelonLoader build. Returns 'x64', 'x86', or
    None if it can't be determined (unusual/corrupt file, unknown arch)."""
    try:
        with open(exe_path, "rb") as f:
            if f.read(2) != b"MZ":
                return None
            f.seek(0x3C)
            pe_offset = struct.unpack("<I", f.read(4))[0]
            f.seek(pe_offset)
            if f.read(4) != b"PE\0\0":
                return None
            machine = struct.unpack("<H", f.read(2))[0]
            return {0x8664: "x64", 0x14c: "x86"}.get(machine)
    except Exception:
        return None


def _melonloader_installed(game_dir):
    return (os.path.isdir(os.path.join(game_dir, "MelonLoader")) and
            os.path.isfile(os.path.join(game_dir, "version.dll")))


def _tavernlib_installed(game_dir):
    return os.path.isfile(os.path.join(game_dir, "Plugins", TAVERNLIB_FILENAME))


# YamlDotNet.dll now ships in the same Patch/ folder as themoddingtavern.dll,
# so — unlike the earlier NuGet-only situation — this is just a local file
# copy into UserLibs, same idea as TavernLib's install but a different
# destination folder. No version/update tracking: it's bundled with the
# launcher release, not fetched from anywhere.
YAMLDOTNET_FILENAME = "YamlDotNet.dll"

def _yamldotnet_source_path():
    return os.path.join(_app_dir(), "Patch", YAMLDOTNET_FILENAME)

def _yamldotnet_installed(game_dir):
    return os.path.isfile(os.path.join(game_dir, "UserLibs", YAMLDOTNET_FILENAME))

def _install_yamldotnet(game_dir):
    """Copy YamlDotNet.dll from the local Patch/ folder into the game's
    UserLibs folder. Raises RuntimeError with a user-friendly message if the
    source file isn't there."""
    src = _yamldotnet_source_path()
    if not os.path.isfile(src):
        raise RuntimeError(
            f"YamlDotNet.dll not found:\n{src}\n\n"
            "Make sure the Patch folder is in the same directory as this launcher.")
    dest_dir = os.path.join(game_dir, "UserLibs")
    os.makedirs(dest_dir, exist_ok=True)
    shutil.copy2(src, os.path.join(dest_dir, YAMLDOTNET_FILENAME))


@contextlib.contextmanager
def _force_ipv4():
    """Temporarily makes socket.getaddrinfo only return IPv4 results.
    Fixes a common real-world failure: a network where IPv6 is technically
    configured but the actual route is dead/blackholed, so anything that
    tries the (often-preferred) IPv6 address first just hangs instead of
    failing over. Browsers and curl dodge this automatically by racing both
    address families ("happy eyeballs"); plain urllib doesn't, so this
    nudges it into only ever trying IPv4."""
    _orig = socket.getaddrinfo
    def _ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return _orig(host, port, socket.AF_INET, type, proto, flags)
    socket.getaddrinfo = _ipv4_only
    try:
        yield
    finally:
        socket.getaddrinfo = _orig


def _urlopen_hard_timeout(req, connect_timeout=20, socket_timeout=20):
    """Runs urlopen() in a helper thread so a hung DNS lookup can't block
    forever — urlopen's own timeout= only bounds the socket connect/read
    once a connection attempt actually starts; DNS resolution happens
    before that and isn't covered by it at all. This is very likely what
    "stuck on Downloading MelonLoader, even as admin" actually was for at
    least some users: a permissions fix wouldn't touch a hung DNS lookup.
    If nothing happens within connect_timeout seconds, this gives up and
    raises rather than waiting on it — the abandoned attempt is a daemon
    thread, so it can't keep the app running even if it eventually returns."""
    result = {}
    def _do():
        try:
            result["resp"] = urllib.request.urlopen(req, timeout=socket_timeout)
        except Exception as e:
            result["error"] = e
    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(connect_timeout)
    if t.is_alive():
        raise RuntimeError(
            f"Connecting to {urlparse(req.full_url).netloc} took too long and was "
            "abandoned. This usually means DNS resolution or the connection itself "
            "is hanging on this machine — often a VPN, a misconfigured router, or "
            "security software silently intercepting it rather than refusing it "
            "outright. Worth trying: disable any active VPN, try a different "
            "network (e.g. a phone hotspot) to confirm, or temporarily disable "
            "antivirus/firewall and retry.")
    if "error" in result:
        raise result["error"]
    return result["resp"]


def _download_with_progress(url, dest_path, on_progress,
                             connect_timeout=20, max_total_seconds=90, chunk_size=1<<16):
    """Downloads url to dest_path, reporting live progress and enforcing a
    real wall-clock cap on the whole operation — a plain urlopen timeout=
    only guards a single socket operation, so a connection that trickles
    data just fast enough to dodge that never trips it and looks like a
    permanent hang rather than a slow download. Returns the response
    headers on success (some callers use these, e.g. for an ETag). Raises
    RuntimeError with a specific, actionable message on failure, and never
    leaves a partially-downloaded file at dest_path."""
    start = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": "TavernLauncher/1.0"})
    with _force_ipv4():
        try:
            resp = _urlopen_hard_timeout(req, connect_timeout=connect_timeout)
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Couldn't connect to {urlparse(url).netloc} — {getattr(e,'reason',e)}\n\n"
                "This is usually a network/firewall/antivirus issue on this machine, "
                "not something wrong with the launcher itself. Worth trying:\n"
                "  • Run the launcher as Administrator\n"
                "  • Temporarily disable antivirus/VPN and retry\n"
                "  • Check whether a firewall is blocking outbound HTTPS for this app")

        total = resp.headers.get("Content-Length")
        total = int(total) if total and total.isdigit() else None
        downloaded = 0
        try:
            with resp, open(dest_path, "wb") as out:
                while True:
                    if time.time() - start > max_total_seconds:
                        raise RuntimeError(
                            f"Download stalled for over {max_total_seconds}s — giving up. "
                            "The connection may be extremely slow, or something is "
                            "silently throttling it (security software, a captive "
                            "portal, etc.) rather than blocking it outright.")
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    out.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded * 100 / max(1, total))
                        on_progress(f"Downloading… {pct}%  ({downloaded//1024:,} / {total//1024:,} KB)")
                    else:
                        on_progress(f"Downloading… {downloaded//1024:,} KB")
        except Exception:
            try: os.remove(dest_path)
            except Exception: pass
            raise
        return dict(resp.headers)


def _melonloader_manual_zip_path(arch):
    """Where a copy of MelonLoader shipped with this launcher release is
    checked for, as an automatic fallback if the network download fails
    or is taking too long. Some networks (school/corporate proxies that
    need PAC/WPAD config Python doesn't evaluate, antivirus intercepting
    the download for scanning, firewalls that only allowlist browser
    traffic) block this app's own outbound request in ways no amount of
    retry/timeout logic can fix from the inside — bundling a known-good
    copy means the install still succeeds either way, with no user action
    needed. The network attempt still goes first, since it's the only way
    to get anything newer than whatever shipped with this build."""
    return os.path.join(_app_dir(), "Patch", f"MelonLoader.{arch}.zip")


def _install_melonloader(game_dir, arch, on_progress):
    """Tries downloading the latest official MelonLoader release first;
    if that fails, or a bundled copy exists and the download hasn't
    finished quickly, falls back to whatever shipped in Patch/ — so this
    succeeds either way without ever needing the user to do anything.
    Raises only if neither a working download nor a bundled copy exists."""
    manual_zip  = _melonloader_manual_zip_path(arch)
    have_bundled = os.path.isfile(manual_zip)
    url = MELONLOADER_ZIP_URLS.get(arch)
    if not url and not have_bundled:
        raise RuntimeError(f"Unsupported or unrecognized game architecture ({arch}).")

    tag = None
    downloaded_ok = False
    tmp_zip = os.path.join(tempfile.gettempdir(), "tavern_melonloader_dl.zip")

    if url:
        try: tag = _get_melonloader_latest_tag()
        except Exception: pass
        try:
            if have_bundled:
                # A good fallback is right there — don't make the user
                # wait long before using it.
                _download_with_progress(url, tmp_zip, on_progress,
                                         connect_timeout=8, max_total_seconds=15)
            else:
                _download_with_progress(url, tmp_zip, on_progress)
            downloaded_ok = True
        except Exception:
            if not have_bundled:
                raise
            on_progress("Couldn't reach GitHub — using the version bundled with this launcher…")

    source_zip = tmp_zip if downloaded_ok else manual_zip
    on_progress("Extracting MelonLoader…")
    with zipfile.ZipFile(source_zip) as zf:
        zf.extractall(game_dir)
    if downloaded_ok:
        try: os.remove(tmp_zip)
        except Exception: pass

    meta = _load_mod_meta(game_dir)
    if downloaded_ok and tag:
        meta["melonloader_tag"] = tag
    elif not downloaded_ok:
        # No real tag to record — a marker distinct enough that a later
        # status check (once network access works again) can still tell
        # this apart from "definitely current", prompting a real update.
        meta["melonloader_tag"] = f"bundled:{_sha256_file(manual_zip)[:12]}"
    _save_mod_meta(game_dir, meta)


def _tavernlib_manual_dll_path():
    """Same idea as _melonloader_manual_zip_path — a copy of TavernLib.dll
    shipped with this launcher release, used automatically as a fallback
    if the network download fails or is taking too long."""
    return os.path.join(_app_dir(), "Patch", "TavernLib.dll")


def _install_tavernlib(game_dir, on_progress):
    """Tries downloading the latest TavernLib.dll first; if that fails, or
    a bundled copy exists and the download hasn't finished quickly, falls
    back to whatever shipped in Patch/ — so this succeeds either way
    without ever needing the user to do anything. Always swaps the result
    in atomically, so a failed/interrupted attempt can never leave a
    corrupt half-downloaded file in place."""
    plugins_dir = os.path.join(game_dir, "Plugins")
    os.makedirs(plugins_dir, exist_ok=True)
    dest = os.path.join(plugins_dir, TAVERNLIB_FILENAME)
    tmp_dest = dest + ".download"

    manual_dll   = _tavernlib_manual_dll_path()
    have_bundled = os.path.isfile(manual_dll)
    fingerprint  = ""
    try:
        if have_bundled:
            headers = _download_with_progress(TAVERNLIB_DOWNLOAD_URL, tmp_dest, on_progress,
                                                connect_timeout=8, max_total_seconds=15)
        else:
            headers = _download_with_progress(TAVERNLIB_DOWNLOAD_URL, tmp_dest, on_progress)
        fingerprint = headers.get("ETag") or headers.get("Last-Modified") or ""
    except Exception:
        if not have_bundled:
            raise
        on_progress("Couldn't reach GitHub — using the version bundled with this launcher…")
        shutil.copy2(manual_dll, tmp_dest)
        fingerprint = f"bundled:{_sha256_file(manual_dll)[:12]}"

    os.replace(tmp_dest, dest)  # atomic on Windows — always a full swap, never a partial one
    if fingerprint:
        meta = _load_mod_meta(game_dir)
        meta["tavernlib_fingerprint"] = fingerprint
        _save_mod_meta(game_dir, meta)


def _melonloader_status(game_dir):
    """Returns 'missing', 'outdated', 'unknown' (installed, but we have no
    baseline to compare — e.g. it was installed by hand before this feature
    existed, or the update check failed), or 'current'."""
    if not _melonloader_installed(game_dir):
        return "missing"
    installed_tag = _load_mod_meta(game_dir).get("melonloader_tag")
    if not installed_tag:
        return "unknown"
    try:
        latest = _get_melonloader_latest_tag()
    except Exception:
        return "unknown"
    if not latest:
        return "unknown"
    return "current" if latest == installed_tag else "outdated"


def _tavernlib_status(game_dir):
    if not _tavernlib_installed(game_dir):
        return "missing"
    installed_fp = _load_mod_meta(game_dir).get("tavernlib_fingerprint")
    if not installed_fp:
        return "unknown"
    try:
        latest_fp = _fetch_remote_fingerprint(TAVERNLIB_DOWNLOAD_URL)
    except Exception:
        return "unknown"
    if not latest_fp:
        return "unknown"
    return "current" if latest_fp == installed_fp else "outdated"


def _mods_need_attention(game_dir):
    """True if either mod is missing or outdated — the trigger for flashing
    the main window's Mods button. Network failures during the update checks
    never trigger a false alarm on their own — only a real missing install
    (a purely local, always-reliable check) does that unconditionally."""
    return (_melonloader_status(game_dir) in ("missing", "outdated") or
            _tavernlib_status(game_dir)   in ("missing", "outdated"))


# ── Patch ─────────────────────────────────────────────────────────────────────
# themoddingtavern.dll lives in a Patch/ folder next to this launcher exe.
# Applying the patch means copying it into the game's Assembly folder under
# the name Root.Township.dll (replacing whatever was there before).
PATCH_SOURCE_FILENAME = "themoddingtavern.dll"
PATCH_TARGET_SUBDIR   = os.path.join("A Township Tale_Data", "Managed")
PATCH_TARGET_FILENAME = "Root.Township.dll"


def _patch_source_path():
    """Full path to themoddingtavern.dll in the Patch/ folder next to the launcher."""
    return os.path.join(_app_dir(), "Patch", PATCH_SOURCE_FILENAME)


def _patch_target_path(game_exe):
    """Full path where Root.Township.dll lives in the game's Managed folder."""
    game_dir = os.path.dirname(game_exe)
    return os.path.join(game_dir, PATCH_TARGET_SUBDIR, PATCH_TARGET_FILENAME)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _patch_is_applied(game_exe):
    """True if the installed Root.Township.dll's content exactly matches the
    local Patch/themoddingtavern.dll. This is a real on-disk comparison, not
    a remembered "I clicked this before" flag — so if the client launcher
    already patched a given game install, the server launcher (or vice
    versa) correctly sees it as already done too, as long as they're both
    pointed at the same game folder. No re-patching, no re-flashing."""
    src = _patch_source_path()
    dst = _patch_target_path(game_exe)
    try:
        if not (os.path.isfile(src) and os.path.isfile(dst)):
            return False
        if os.path.getsize(src) != os.path.getsize(dst):
            return False
        return _sha256_file(src) == _sha256_file(dst)
    except OSError:
        return False


def apply_patch(game_exe):
    """Copy themoddingtavern.dll -> <game>/.../Managed/Root.Township.dll.
    Raises RuntimeError with a user-friendly message on any failure."""
    src = _patch_source_path()
    if not os.path.isfile(src):
        raise RuntimeError(
            f"Patch file not found:\n{src}\n\n"
            "Make sure the Patch folder is in the same directory as this launcher.")
    dst = _patch_target_path(game_exe)
    managed_dir = os.path.dirname(dst)
    if not os.path.isdir(managed_dir):
        raise RuntimeError(
            f"Game Managed folder not found:\n{managed_dir}\n\n"
            "Double-check the game exe path at the top of the launcher.")
    shutil.copy2(src, dst)


class ModsWindow(tk.Toplevel):
    def __init__(self, parent, exe_path, on_status_change=None):
        super().__init__(parent)
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
        _enable_dark_titlebar(self)

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
        ).pack(anchor="w", padx=20, pady=(10,8))

        self._ml_btn = self._mod_row(
            "MelonLoader", "The mod loader itself — required before anything else.",
            self._on_melonloader_click)
        self._yaml_btn = self._mod_row(
            "YamlDotNet.dll", "A .NET YAML library some mods depend on.",
            self._on_yamldotnet_click)
        self._tl_btn = self._mod_row(
            "TavernLib", "Our plugin — adds this server's mod support to the game.",
            self._on_tavernlib_click)

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

    def _refresh_states(self):
        self._status.set("Checking status…")
        def worker():
            ml = _melonloader_status(self._game_dir)
            tl = _tavernlib_status(self._game_dir)
            yaml_ok = _yamldotnet_installed(self._game_dir)
            self.after(0, lambda: self._apply_states(ml, tl, yaml_ok))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_states(self, ml_state, tl_state, yaml_ok):
        self._apply_row_state(self._ml_btn, ml_state)
        self._apply_row_state(self._tl_btn, tl_state)
        self._apply_yaml_state(yaml_ok)
        self._status.set("")
        if self._on_status_change: self._on_status_change()

    def _apply_yaml_state(self, installed):
        """YamlDotNet ships in Patch/ alongside themoddingtavern.dll now, so
        this is a plain local-file install like TavernLib — just no update
        tracking, since it's bundled with the launcher rather than fetched."""
        self._yaml_btn._dotvar.set("●" if installed else "○")
        self._yaml_btn._dotlabel.config(fg=GREEN if installed else MUTED)
        self._yaml_btn.config(text="⟳ Reinstall" if installed else "⬇ Install")
        note = "Detected in UserLibs." if installed else None
        self._yaml_btn._subvar.set(f"{self._yaml_btn._subtitle}  ·  {note}" if note else self._yaml_btn._subtitle)

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
        self._yaml_btn.config(state=state)
        self._tl_btn.config(state=state)
        self._status.set(msg)

    def _on_yamldotnet_click(self):
        if self._busy: return
        if not _melonloader_installed(self._game_dir):
            messagebox.showwarning("Install MelonLoader first",
                "YamlDotNet loads alongside MelonLoader's other libraries — "
                "install MelonLoader above first.")
            return
        self._set_busy(True, "Installing YamlDotNet…")

        def worker():
            try:
                _install_yamldotnet(self._game_dir)
                self.after(0, lambda: self._finish_install(True, "YamlDotNet installed."))
            except Exception as e:
                self.after(0, lambda: self._finish_install(False, f"Install failed: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_melonloader_click(self):
        if self._busy: return
        arch = _detect_exe_arch(self._exe)
        if not arch:
            messagebox.showerror("Can't tell architecture",
                "Couldn't determine whether the game is 32- or 64-bit from "
                "the selected .exe. Try re-browsing to it on the main screen.")
            return
        self._set_busy(True, f"Detected {arch} game — starting install…")

        def worker():
            try:
                _install_melonloader(self._game_dir, arch,
                    lambda m: self.after(0, lambda: self._status.set(m)))
                self.after(0, lambda: self._finish_install(True, "MelonLoader installed."))
            except Exception as e:
                self.after(0, lambda: self._finish_install(False, f"Install failed: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _on_tavernlib_click(self):
        if self._busy: return
        if not _melonloader_installed(self._game_dir):
            messagebox.showwarning("Install MelonLoader first",
                "TavernLib is a MelonLoader plugin — install MelonLoader above first.")
            return
        self._set_busy(True, "Starting TavernLib install…")

        def worker():
            try:
                _install_tavernlib(self._game_dir,
                    lambda m: self.after(0, lambda: self._status.set(m)))
                self.after(0, lambda: self._finish_install(True, "TavernLib installed."))
            except Exception as e:
                self.after(0, lambda: self._finish_install(False, f"Install failed: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_install(self, ok, msg):
        self._set_busy(False, msg)
        self._refresh_states()


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
        ss = load_server_settings()
        ss["name"] = self.v_name.get().strip() or "My Tavern Server"
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
        self._community_registered = False
        self._community_stop = threading.Event()
        self._community_thread = None
        self._mods_animating  = False
        self._mods_anim_job   = None
        self._mods_anim_phase = 0
        self._patch_animating  = False
        self._patch_anim_job   = None
        self._patch_anim_phase = 0
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
        self._patch_btn = _btn(tr, "🩹 Patch", self._on_patch_click,
                               font=("Segoe UI",9), pady=7, padx=12)
        self._patch_btn.pack(side="left")
        self._mods_btn = _btn(tr, "🧪 Mods", self._open_mods,
                              font=("Segoe UI",9), pady=7, padx=12)
        self._mods_btn.pack(side="left", padx=6)
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
        if needed: self._start_mods_animation()
        else:      self._stop_mods_animation()

    def _start_mods_animation(self):
        if self._mods_animating: return
        self._mods_animating = True
        self._mods_anim_phase = 0
        self._animate_mods_btn()

    def _animate_mods_btn(self):
        if not self._mods_animating: return
        bg, fg = (SURF2, AMBER) if self._mods_anim_phase % 2 == 0 else ("#5a3d0e", "#ffd080")
        try: self._mods_btn.config(bg=bg, fg=fg)
        except Exception: return
        self._mods_anim_phase += 1
        self._mods_anim_job = self.after(450, self._animate_mods_btn)

    def _stop_mods_animation(self):
        self._mods_animating = False
        if self._mods_anim_job:
            try: self.after_cancel(self._mods_anim_job)
            except Exception: pass
            self._mods_anim_job = None
        try: self._mods_btn.config(bg=SURF2, fg=PARCH)
        except Exception: pass

    def _refresh_patch_alert(self, exe):
        """Flash the Patch button only while the patch DLL is actually
        present AND not already applied — a real on-disk check, so it
        correctly reflects reality even if the client launcher already did
        this for the same game (both point at the same target files)."""
        if not exe or not os.path.isfile(exe):
            self._stop_patch_animation()
            return
        def worker():
            try:
                need = os.path.isfile(_patch_source_path()) and not _patch_is_applied(exe)
            except Exception:
                need = False
            self.after(0, lambda: self._start_patch_animation() if need else self._stop_patch_animation())
        threading.Thread(target=worker, daemon=True).start()

    def _start_patch_animation(self):
        if self._patch_animating: return
        self._patch_animating = True
        self._patch_anim_phase = 0
        self._animate_patch_btn()

    def _animate_patch_btn(self):
        if not self._patch_animating: return
        bg, fg = ("#1a3d2a", "#80d8aa") if self._patch_anim_phase % 2 == 0 else ("#0d2419", "#50aa7a")
        try: self._patch_btn.config(bg=bg, fg=fg)
        except Exception: return
        self._patch_anim_phase += 1
        self._patch_anim_job = self.after(450, self._animate_patch_btn)

    def _stop_patch_animation(self):
        self._patch_animating = False
        if self._patch_anim_job:
            try: self.after_cancel(self._patch_anim_job)
            except Exception: pass
            self._patch_anim_job = None
        try: self._patch_btn.config(bg=SURF2, fg=PARCH)
        except Exception: pass

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
