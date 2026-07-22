"""
The Modding Tavern — Client Launcher
"""

# Bump this with every release you publish to
# github.com/ModdingTavern/TavernLauncher/releases (tag it vX.Y.Z to match).
APP_VERSION = "1.8.1"

# The subfolder this app occupies inside the release zip
# (TavernLauncher-vX.Y.Z.zip contains /Client and /Server side by side) —
# used by the self-updater to know which part of the zip is "ours".
UPDATE_APP_FOLDER = "Client"

import sys, os, subprocess, time, json, socket, secrets, csv, threading, io, hashlib, glob, webbrowser
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import base64, hmac as _hmac, tempfile, urllib.request, urllib.error, ctypes, zipfile, shutil, struct, contextlib
import http.client
from urllib.parse import urlparse, urlencode

_updater = None
try:
    import updater as _updater
except ImportError:
    pass

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

AUTH_PORT   = 1762

# The dropdown shows friendly platform names, but the game itself still
# needs the original /vrmode values it always expected — this is a purely
# visual simplification, not a protocol change. PLATFORM_LEGACY_TO_DISPLAY
# handles a config file saved before this change (which would have the old
# "OpenVR"/"Oculus" display string persisted) so existing users' saved
# choice still loads correctly instead of silently resetting.
PLATFORM_DISPLAY_TO_BACKEND = {"SteamVR": "openvr", "Quest": "oculus"}
PLATFORM_LEGACY_TO_DISPLAY  = {"OpenVR": "SteamVR", "Oculus": "Quest"}
USERNAME_MAX_LEN = 16
USERNAME_EXTRA_CHARS = " -_"

def _is_valid_username(username):
    """ASCII letters/digits plus space, hyphen, underscore — keeps usernames
    safe to embed in file names (token cache) and launch args without escaping."""
    return all((c.isalnum() and c.isascii()) or c in USERNAME_EXTRA_CHARS
               for c in username)

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

def _app_dir():
    if getattr(sys, "frozen", False): return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def _tavern_data_dir():
    """The one shared place this launcher's own persistent data lives —
    config and token files — regardless of which folder the exe itself
    happens to be running from. Means downloading a new build to a
    different folder, or a fresh install replacing the old one, never
    requires manually moving files over; they were never next to the exe
    in the first place. (The Patch/ folder and per-game-install files like
    .tavern_mods_meta.json deliberately stay where they are — see the
    comments at their own definitions for why.)"""
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

def _migrate_legacy_tokens():
    """One-time bulk move of every pre-existing token file (old single-
    file-per-username scheme and the newer per-server-pair scheme alike)
    from next to the exe into the shared tokens/ folder."""
    try:
        old_dir = _app_dir()
        new_dir = os.path.join(_tavern_data_dir(), "tokens")
        for old_path in glob.glob(os.path.join(old_dir, ".token_*.json")):
            new_path = os.path.join(new_dir, os.path.basename(old_path))
            _migrate_legacy_file(old_path, new_path)
    except Exception:
        pass

CONFIG_FILE = os.path.join(_tavern_data_dir(), "tavern_launcher.json")
_migrate_legacy_file(os.path.join(os.path.expanduser("~"), ".tavern_launcher.json"), CONFIG_FILE)
_migrate_legacy_tokens()

def _safe_part(s):
    return "".join(c for c in str(s).lower() if c.isalnum() or c in "-_") or "x"

def _legacy_token_file(username):
    """Old scheme: one token file per username, shared across every server."""
    return os.path.join(_tavern_data_dir(), "tokens", f".token_{_safe_part(username)}.json")

def _token_file(host, username):
    """New scheme: one token file per server+username pair, so the same
    username can hold a different, independent token on each server."""
    return os.path.join(_tavern_data_dir(), "tokens",
        f".token_{_safe_part(host)}__{_safe_part(username)}.json")

def _any_token_files_exist():
    """True if at least one token file (old or new naming scheme) already
    exists, regardless of which server/username it's for."""
    try:
        return bool(glob.glob(os.path.join(_tavern_data_dir(), "tokens", ".token_*.json")))
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
        os.makedirs(os.path.dirname(path), exist_ok=True)
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
        # Distinguishable from a real rejection — this means there was no
        # auth service to even talk to, not that one rejected the login.
        # _do_launch uses this specifically to decide whether a headless-
        # server fallback lookup is worth trying.
        return None, f"CANNOT_REACH::{e}"
    status = resp.get("status")
    if status == "ok":          return resp.get("user_id"), None
    if status == "needs_password": return None, "NEEDS_PASSWORD"
    if status == "wrong_password": return None, "Wrong password."
    if status == "not_whitelisted": return None, "You are not on the whitelist for this server."
    return None, resp.get("message", "Authentication failed.")

def ticket_request(host, action, username, token, timeout=10, **kwargs):
    """Sends one ticket_action request to a server's auth port and returns
    the parsed JSON response. Raises on a connection failure — callers
    should catch and show a clear error, same as any other network call
    here. Uses a larger receive buffer than the plain auth exchange, since
    a ticket list with several tickets and comment threads can genuinely
    exceed the smaller buffer used for a simple login response."""
    payload = {"ticket_action": action, "username": username, "token": token}
    payload.update(kwargs)
    s = socket.socket()
    s.settimeout(timeout)
    s.connect((host, AUTH_PORT))
    s.sendall(json.dumps(payload).encode())
    raw = s.recv(65536)
    s.close()
    return json.loads(raw.decode())

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

def _resolve_ip_for_game(host):
    """The game's own /dev_server_ip argument appears to require a literal
    IP address, not a hostname — passing a DNS name through connects fine
    at the auth-handshake level (that's plain Python socket code, which
    resolves hostnames automatically) but then silently fails to actually
    join: black screen, server sees no incoming connection. This resolves
    the hostname once, specifically for that one argument, so the game
    always receives a real IP regardless of whether the player joined via
    a hostname from the community list or typed one in directly."""
    try:
        return socket.gethostbyname(host)
    except socket.gaierror:
        return host


def _valid_port(value, default=1757):
    """Coerces whatever's in the port field to a sane integer, falling back
    to the game's own default if it's empty, non-numeric, or out of range."""
    try:
        p = int(str(value).strip())
        return p if 1 <= p <= 65535 else default
    except (TypeError, ValueError):
        return default


def build_tokens(user_id, username, tavern_token=""):
    """tavern_token is our OWN internal secret (the same one _get_or_create_token
    already tracks per server+username) — embedded here as an extra custom
    claim purely for a server-side mod to verify independently. UserId and
    Username alone aren't enough for that: since the "offline" HMAC key is
    necessarily public (the game itself has to know it to run in
    /force_offline mode at all), anyone can hand-craft a validly-signed JWT
    claiming any UserId/Username they like. This extra claim is the one
    thing in here a forger can't guess — a cryptographically random value
    that's only ever handed out after actually passing the auth handshake
    (password, whitelist, blacklist all included), so a mod checking it
    against the server's own records closes that gap regardless of what
    else the presented JWT claims to be."""
    exp, uid = 9999999999, str(user_id)
    a = _jwt({"UserId":uid,"Username":username,"role":"Access","is_verified":"True",
              "is_member":"True","Policy":["offline","play_offline","server_access_pre_alpha",
              "server_access_tutorial","game_access_public","game_access_development",
              "server_access_development","server_access_testing","game_access_testing",
              "server_owner","debug_features","admin_vr_modes","database_admin",
              "server_create_development","reuse_refresh_tokens"],
              "TavernToken":tavern_token,
              "exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    r = _jwt({"UserId":uid,"role":"Refresh","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    i = _jwt({"UserId":uid,"Username":username,"role":"Identity","is_member":"True",
              "is_dev":"True","TavernToken":tavern_token,
              "exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"})
    return a, r, i

# Headless/direct-connect servers have no port-1762 gate to hand out a
# user_id, so one is derived locally instead — stable per-username (so
# reconnecting as the same name keeps the same id).
#
# Range choice matters here: the game parses UserId back out as a signed
# Int32 (max 2,147,483,647). att_server.py's official ids start at
# BASE_USER_ID = 2,000,000,000 and only grow by 1 per player, so they stay
# safely under that limit — but it leaves very little headroom above it to
# put a second, non-colliding range without also blowing past Int32's max.
# So instead this range sits entirely *below* the official one: comfortably
# inside Int32, and never reachable by the official counter in practice.
HEADLESS_USER_ID_BASE  = 1_000_000_000
HEADLESS_USER_ID_RANGE = 999_999_999

def _headless_user_id(username):
    h = int(hashlib.sha256(username.strip().lower().encode()).hexdigest(), 16)
    return HEADLESS_USER_ID_BASE + (h % HEADLESS_USER_ID_RANGE)

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

def _hint(parent, text):
    tk.Label(parent, text=text, bg=BG, fg=MUTED, justify="left",
             font=("Segoe UI",8)).pack(anchor="w", padx=22, pady=(0,2))

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
            messagebox.showinfo("No selection", "Select a server first.", parent=self)
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
            messagebox.showinfo("Already saved", f"'{name}' is already in your favorites.", parent=self)
            return
        saved.append({"name": name, "ip": host, "port": port})
        cfg["saved_servers"] = saved
        save_cfg(cfg)
        messagebox.showinfo("Saved", f"'{name}' added to favorites.", parent=self)

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
                messagebox.showinfo("Saved", f"'{name}' added to favourites.", parent=self)

        _btn(br, "Connect",        connect,  "primary",
             font=("Georgia",10,"bold"), pady=6, padx=14).pack(side="left")
        _btn(br, "★ Save as Fav",  save_fav, style="normal",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)

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


# CircuitsVoiceChat ships as two DLLs (the mod itself plus the Concentus
# codec it depends on) in one release zip on its own repo — real GitHub
# releases, same "latest" alias trick as MelonLoader. Per the mod's own
# install instructions: the mod itself goes in Mods/, Concentus (a shared
# codec library) goes in UserLibs/.
CIRCUITSVOICECHAT_REPO = "CircuitLord/CircuitsVoiceChat"
CIRCUITSVOICECHAT_DESTINATIONS = {
    "CircuitsVoiceChat.dll": "Mods",
    "Concentus.dll": "UserLibs",
}

def _get_circuitsvoicechat_latest_tag():
    """Same redirect-peek trick as MelonLoader's tag check — no GitHub API
    call, no rate limit."""
    loc = _get_redirect_location(f"https://github.com/{CIRCUITSVOICECHAT_REPO}/releases/latest")
    if not loc:
        return None
    return loc.rstrip("/").split("/")[-1]

def _circuitsvoicechat_manual_paths():
    """Where a copy of both DLLs shipped with this launcher release is
    checked for, as an automatic fallback if the GitHub download fails or
    is taking too long — same reasoning as MelonLoader's bundled fallback."""
    return {name: os.path.join(_app_dir(), "Patch", name)
            for name in CIRCUITSVOICECHAT_DESTINATIONS}

def _circuitsvoicechat_installed(game_dir):
    return all(os.path.isfile(os.path.join(game_dir, subdir, name))
               for name, subdir in CIRCUITSVOICECHAT_DESTINATIONS.items())

def _circuitsvoicechat_status(game_dir):
    """Returns 'missing', 'outdated', 'unknown', or 'current' — same state
    machine as _melonloader_status, now that this has a real tag to check
    against instead of just a local file."""
    if not _circuitsvoicechat_installed(game_dir):
        return "missing"
    installed_tag = _load_mod_meta(game_dir).get("circuitsvoicechat_tag")
    if not installed_tag or installed_tag.startswith("bundled:"):
        return "unknown"
    try:
        latest = _get_circuitsvoicechat_latest_tag()
    except Exception:
        return "unknown"
    if not latest:
        return "unknown"
    return "current" if latest == installed_tag else "outdated"

def _install_circuitsvoicechat(game_dir, on_progress):
    """Tries downloading the latest CircuitsVoiceChat release first; if
    that fails, or a bundled copy exists in Patch/ and the download hasn't
    finished quickly, falls back to the bundled DLLs — the exact same
    network-first, fast-fallback pattern as _install_melonloader. Checks
    both destination files exist in whichever source is actually used
    before writing anything, so a partial zip or a missing bundled file
    can't leave the mod half-installed."""
    manual_paths = _circuitsvoicechat_manual_paths()
    have_bundled = all(os.path.isfile(p) for p in manual_paths.values())

    tag = None
    try: tag = _get_circuitsvoicechat_latest_tag()
    except Exception: pass

    downloaded_files = None  # filename -> bytes, populated only on a real successful download
    if tag:
        zip_filename = f"CircuitsVoiceChat-{tag}.zip"
        url = (f"https://github.com/{CIRCUITSVOICECHAT_REPO}/releases/latest/"
               f"download/{urllib.parse.quote(zip_filename)}")
        tmp_zip = os.path.join(tempfile.gettempdir(), "tavern_circuitsvoicechat_dl.zip")
        try:
            if have_bundled:
                # A good fallback is right there — don't make the user
                # wait long before using it.
                _download_with_progress(url, tmp_zip, on_progress,
                                         connect_timeout=8, max_total_seconds=15)
            else:
                _download_with_progress(url, tmp_zip, on_progress)
            on_progress("Extracting CircuitsVoiceChat…")
            found = {}
            with _open_zip_with_retry(tmp_zip) as zf:
                for wanted in CIRCUITSVOICECHAT_DESTINATIONS:
                    match = _find_zip_entry(zf, wanted)
                    if not match:
                        raise RuntimeError(
                            f"The downloaded release zip didn't contain {wanted}.")
                    found[wanted] = zf.read(match)
            downloaded_files = found
        except Exception:
            downloaded_files = None
            if not have_bundled:
                raise
            on_progress("Couldn't reach GitHub — using the version bundled with this launcher…")
        finally:
            try: os.remove(tmp_zip)
            except Exception: pass
    elif not have_bundled:
        raise RuntimeError(
            "Couldn't reach GitHub to check for CircuitsVoiceChat, and no bundled "
            "copy was found in Patch/ either.")

    for name, subdir in CIRCUITSVOICECHAT_DESTINATIONS.items():
        dest_dir = os.path.join(game_dir, subdir)
        os.makedirs(dest_dir, exist_ok=True)
        dest_path = os.path.join(dest_dir, name)
        if downloaded_files is not None:
            with open(dest_path, "wb") as f:
                f.write(downloaded_files[name])
        else:
            shutil.copy2(manual_paths[name], dest_path)

    meta = _load_mod_meta(game_dir)
    if downloaded_files is not None and tag:
        meta["circuitsvoicechat_tag"] = tag
    else:
        meta["circuitsvoicechat_tag"] = "bundled:local"
    _save_mod_meta(game_dir, meta)


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


def _open_zip_with_retry(path, retries=8, delay=1.0):
    """Windows sometimes briefly locks a freshly-downloaded file while
    antivirus real-time protection scans it — and a .zip containing DLLs
    is exactly the kind of file that gets scanned most aggressively. A
    plain zipfile.ZipFile() open can stall or fail unpredictably during
    that window, with no timeout of its own (this is local disk I/O, not
    network, so the download's own timeout doesn't cover it at all). This
    retries a few times with short pauses — up to ~8s total — before
    giving up for real, rather than hanging indefinitely or failing on
    what's usually just a few seconds of transient scanning."""
    last_err = None
    for _ in range(retries):
        try:
            return zipfile.ZipFile(path)
        except (PermissionError, OSError) as e:
            last_err = e
            time.sleep(delay)
    raise RuntimeError(
        f"Couldn't open the downloaded file — {last_err}\n\n"
        "This can happen if antivirus is still scanning it. Try clicking "
        "Install again, or temporarily disable real-time scanning and retry.")


def _find_zip_entry(zf, wanted_filename):
    """Finds a zip entry matching wanted_filename, tolerating a version
    suffix baked into the actual filename — e.g. the real CircuitsVoiceChat
    release ships "CircuitsVoiceChat-v1.0.4.dll" for what we track as
    "CircuitsVoiceChat.dll". That suffix changes every release, so an exact
    filename match would break on every version bump; matching by stem
    prefix + same extension instead means a new release just works without
    ever needing a code change here. Returns the zip entry's real name (for
    reading), or None if nothing matches."""
    stem, ext = os.path.splitext(wanted_filename)
    stem, ext = stem.lower(), ext.lower()
    for n in zf.namelist():
        b_stem, b_ext = os.path.splitext(os.path.basename(n))
        if b_ext.lower() == ext and b_stem.lower().startswith(stem):
            return n
    return None


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
    with _open_zip_with_retry(source_zip) as zf:
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
    """True if either required mod is missing/outdated, or the optional
    CircuitsVoiceChat is outdated — the trigger for flashing the main
    window's Mods button. Deliberately not "missing" for the optional mod:
    not having opted into it is a normal, expected state, not something
    that needs attention. Network failures during the update checks never
    trigger a false alarm on their own — only a real missing install (a
    purely local, always-reliable check) does that unconditionally."""
    return (_melonloader_status(game_dir) in ("missing", "outdated") or
            _tavernlib_status(game_dir)   in ("missing", "outdated") or
            _circuitsvoicechat_status(game_dir) == "outdated")


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


class TicketsWindow(tk.Toplevel):
    """Player-facing support tickets — create one, see the server owner's
    replies, respond, or close it yourself. Tied to whichever server +
    username the player is actually using, since a ticket only means
    anything in the context of one specific server's own ticket database."""
    def __init__(self, parent, default_host="", default_username=""):
        super().__init__(parent)
        self.title("Support Tickets")
        self.configure(bg=BG)
        self.geometry("640x600")
        self.resizable(True, True)
        _set_window_icon(self)
        ttk.Style().theme_use("clam")
        self._tickets = []
        self._selected_ticket = None
        self._build(default_host, default_username)
        _enable_dark_titlebar(self)
        self._refresh(silent=True)
        # Same reasoning as the main launcher windows — start at exactly
        # what the fully-built layout needs, then set that as the floor,
        # so shrinking the window can never clip the Reply/Close Ticket row.
        self.update_idletasks()
        fit_w = max(640, self.winfo_reqwidth())
        fit_h = max(600, self.winfo_reqheight())
        self.geometry(f"{fit_w}x{fit_h}")
        self.minsize(fit_w, fit_h)

    def _build(self, default_host, default_username):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="🎫  Support Tickets", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        sf = tk.Frame(self, bg=BG)
        sf.pack(fill="x", padx=16, pady=(10,4))
        tk.Label(sf, text="Server:", bg=BG, fg=MUTED, font=("Segoe UI",9)).pack(side="left")
        self.v_host = tk.StringVar(value=default_host)
        tk.Entry(sf, textvariable=self.v_host, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, width=20).pack(side="left", padx=(6,10))
        tk.Label(sf, text="Username:", bg=BG, fg=MUTED, font=("Segoe UI",9)).pack(side="left")
        self.v_username = tk.StringVar(value=default_username)
        tk.Entry(sf, textvariable=self.v_username, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6, width=14).pack(side="left", padx=(6,0))
        _btn(sf, "⚑ Pick Saved", self._pick_saved_server,
             font=("Segoe UI",8), pady=4, padx=6).pack(side="left", padx=(8,0))
        _hint(self, "Tickets are tied to whichever username+server you actually play on.")

        br = tk.Frame(self, bg=BG)
        br.pack(fill="x", padx=16, pady=(0,8))
        _btn(br, "⟳ Refresh My Tickets", self._refresh, "primary",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left")
        _btn(br, "+ New Ticket", self._new_ticket,
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=(6,0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=16, pady=(0,10))

        # A fixed-height outer frame for the tree — _mk_tree's own wrapper
        # always requests expand=True internally, which would otherwise
        # compete with `detail` below for space and squeeze out the Reply/
        # Close Ticket row. The tree only ever needs to show a short list,
        # so it gets just its natural size; `detail` (below) claims
        # whatever's actually left over.
        tree_container = tk.Frame(body, bg=BG)
        tree_container.pack(fill="x")
        self.tree = _mk_tree(tree_container, ("title","status","updated"), [280,80,140], height=7)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        detail = tk.Frame(body, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        detail.pack(fill="both", expand=True, pady=(8,0))

        self.v_detail_title = tk.StringVar(value="Select a ticket, or open a new one.")
        tk.Label(detail, textvariable=self.v_detail_title, bg=SURF, fg=AMBER,
                 font=("Georgia",10,"bold"), wraplength=560, justify="left"
                 ).pack(anchor="w", padx=10, pady=(10,4))

        thread_frame = tk.Frame(detail, bg=BG)
        thread_frame.pack(fill="both", expand=True, padx=10, pady=(0,6))
        self.thread_text = tk.Text(thread_frame, bg=SURF2, fg=PARCH, relief="flat",
                                   bd=0, wrap="word", state="disabled",
                                   font=("Segoe UI",9), height=8)
        tsb = _mk_scrollbar(thread_frame, self.thread_text.yview)
        tsb.pack(side="right", fill="y")
        self.thread_text.config(yscrollcommand=tsb.set)
        self.thread_text.pack(side="left", fill="both", expand=True)
        self.thread_text.tag_config("player", foreground=CYAN)
        self.thread_text.tag_config("owner", foreground=AMBER)
        self.thread_text.tag_config("meta", foreground=MUTED)

        action_row = tk.Frame(detail, bg=SURF)
        action_row.pack(fill="x", padx=10, pady=(0,10))
        self.v_reply = tk.StringVar()
        tk.Entry(action_row, textvariable=self.v_reply, bg=SURF2, fg=PARCH,
                 insertbackground=AMBER, relief="flat",
                 highlightbackground=BORDER, highlightcolor=AMBER, highlightthickness=1,
                 font=("Consolas",9), bd=6).pack(side="left", fill="x", expand=True)
        _btn(action_row, "Reply", self._respond, font=("Segoe UI",9),
             pady=6, padx=8).pack(side="left", padx=(6,0))
        _btn(action_row, "Close Ticket", self._close_ticket, "danger",
             font=("Segoe UI",9), pady=6, padx=8).pack(side="left", padx=(6,0))

    def _current_host_username(self, silent=False):
        host = self.v_host.get().strip()
        username = self.v_username.get().strip()
        if not host or not username:
            if not silent:
                messagebox.showerror("Missing info",
                    "Enter both a server and a username.", parent=self)
            return None, None
        return host, username

    def _pick_saved_server(self):
        def on_select(ip, name, port="1757"):
            self.v_host.set(ip)
            self._refresh(silent=True)
        ServerListPanel(self, on_select)

    def _refresh(self, silent=False):
        host, username = self._current_host_username(silent=silent)
        if not host: return
        resolved = _resolve_ip_for_game(host)
        token, _ = _get_or_create_token(resolved, username)
        def worker():
            try:
                resp = ticket_request(resolved, "list_mine", username, token)
            except Exception as e:
                if not silent:
                    self.after(0, lambda: messagebox.showerror(
                        "Couldn't fetch tickets", str(e), parent=self))
                return
            if resp.get("status") != "ok":
                # Most common cause here: this username+server combo has
                # never actually joined the server, so there's nothing to
                # recognize yet — completely normal the first time this
                # window is opened, not worth surfacing as an error unless
                # the player explicitly clicked Refresh to ask.
                if not silent:
                    self.after(0, lambda: messagebox.showerror(
                        "Error", resp.get("message","Unknown error"), parent=self))
                return
            self.after(0, lambda: self._apply_tickets(resp.get("tickets", [])))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_tickets(self, tickets):
        self._tickets = tickets
        for r in self.tree.get_children(): self.tree.delete(r)
        for t in sorted(tickets, key=lambda t: t["updated_at"], reverse=True):
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(t["updated_at"]))
            self.tree.insert("", "end", iid=t["ticket_id"], values=(t["title"], t["status"], ts))

    def _on_select(self, _=None):
        sel = self.tree.selection()
        if not sel: return
        t = next((x for x in self._tickets if x["ticket_id"] == sel[0]), None)
        if not t: return
        self._selected_ticket = t
        self.v_detail_title.set(f"{t['title']}  ({t['status']})")
        self.thread_text.config(state="normal")
        self.thread_text.delete("1.0", "end")
        self.thread_text.insert("end", t["description"] + "\n\n")
        for c in t.get("comments", []):
            who = "Server Owner" if c["from"] == "owner" else "You"
            tag = "owner" if c["from"] == "owner" else "player"
            ts = time.strftime("%Y-%m-%d %H:%M", time.localtime(c["at"]))
            self.thread_text.insert("end", f"[{ts}] {who}: ", tag)
            self.thread_text.insert("end", f"{c['message']}\n")
        self.thread_text.see("end")
        self.thread_text.config(state="disabled")

    def _new_ticket(self):
        host, username = self._current_host_username()
        if not host: return

        win = tk.Toplevel(self)
        win.title("New Ticket")
        win.configure(bg=BG)
        win.resizable(False, False)
        _set_window_icon(win)

        _section_label(win, "TITLE")
        tf = _field(win)
        v_title = tk.StringVar()
        tk.Entry(tf, textvariable=v_title, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(fill="x")

        _section_label(win, "DESCRIPTION")
        df = tk.Frame(win, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        df.pack(fill="both", expand=True, padx=20, pady=(0,6))
        desc_text = tk.Text(df, bg=SURF, fg=PARCH, insertbackground=AMBER,
                            relief="flat", bd=6, wrap="word", height=8,
                            font=("Segoe UI",9))
        desc_text.pack(fill="both", expand=True)

        def _submit():
            title = v_title.get().strip()
            description = desc_text.get("1.0","end").strip()
            if not title or not description:
                messagebox.showerror("Missing info",
                    "Title and description are both required.", parent=win)
                return
            resolved = _resolve_ip_for_game(host)
            token, _ = _get_or_create_token(resolved, username)
            def worker():
                try:
                    resp = ticket_request(resolved, "create", username, token,
                                          title=title, description=description, server=host)
                except Exception as e:
                    self.after(0, lambda: messagebox.showerror(
                        "Couldn't submit ticket", str(e), parent=win))
                    return
                if resp.get("status") != "ok":
                    self.after(0, lambda: messagebox.showerror(
                        "Error", resp.get("message","Unknown error"), parent=win))
                    return
                def _done():
                    win.destroy()
                    self._refresh()
                self.after(0, _done)
            threading.Thread(target=worker, daemon=True).start()

        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=20, pady=(4,6))
        _btn(win, "📨  Submit Ticket", _submit, "primary",
             font=("Georgia",11,"bold"), pady=12).pack(fill="x", padx=20, pady=(0,16))

        win.update_idletasks()
        win.geometry(f"420x{win.winfo_reqheight()}")
        _enable_dark_titlebar(win)
        win.transient(self)
        win.grab_set()

    def _selected_ticket_id(self):
        if not self._selected_ticket:
            messagebox.showinfo("No selection", "Select a ticket first.", parent=self)
            return None
        return self._selected_ticket["ticket_id"]

    def _respond(self):
        tid = self._selected_ticket_id()
        if not tid: return
        msg = self.v_reply.get().strip()
        if not msg: return
        if self._selected_ticket.get("status") != "open":
            messagebox.showinfo("Ticket closed", "This ticket is already closed.", parent=self)
            return
        host, username = self._current_host_username()
        resolved = _resolve_ip_for_game(host)
        token, _ = _get_or_create_token(resolved, username)
        def worker():
            try:
                resp = ticket_request(resolved, "respond", username, token,
                                      ticket_id=tid, message=msg)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Couldn't send reply", str(e), parent=self))
                return
            if resp.get("status") != "ok":
                self.after(0, lambda: messagebox.showerror(
                    "Error", resp.get("message","Unknown error"), parent=self))
                return
            def _done():
                self.v_reply.set("")
                self._refresh()
            self.after(0, _done)
        threading.Thread(target=worker, daemon=True).start()

    def _close_ticket(self):
        tid = self._selected_ticket_id()
        if not tid: return
        if self._selected_ticket.get("status") != "open":
            messagebox.showinfo("Already closed", "This ticket is already closed.", parent=self)
            return
        msg = simpledialog.askstring("Close Ticket",
            "Optional closing message (e.g. \"fixed it myself\"):", parent=self) or ""
        if not messagebox.askyesno("Close Ticket",
                "Close this ticket? You won't be able to reply to it afterward.", parent=self):
            return
        host, username = self._current_host_username()
        resolved = _resolve_ip_for_game(host)
        token, _ = _get_or_create_token(resolved, username)
        def worker():
            try:
                resp = ticket_request(resolved, "close", username, token,
                                      ticket_id=tid, message=msg)
            except Exception as e:
                self.after(0, lambda: messagebox.showerror(
                    "Couldn't close ticket", str(e), parent=self))
                return
            if resp.get("status") != "ok":
                self.after(0, lambda: messagebox.showerror(
                    "Error", resp.get("message","Unknown error"), parent=self))
                return
            self.after(0, self._refresh)
        threading.Thread(target=worker, daemon=True).start()


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
            cvc = _circuitsvoicechat_status(self._game_dir)
            self.after(0, lambda: self._apply_states(ml, tl, cvc))
        threading.Thread(target=worker, daemon=True).start()

    def _apply_states(self, ml_state, tl_state, cvc_state):
        self._apply_row_state(self._ml_btn, ml_state)
        self._apply_row_state(self._tl_btn, tl_state)
        self._apply_row_state(self._cvc_btn, cvc_state)
        self._status.set("")
        if self._on_status_change: self._on_status_change()

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
                self.after(0, lambda: self._finish_install(False, f"Install failed: {e}"))
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
                self.after(0, lambda: self._finish_install(False, f"Install failed: {e}"))
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
                self.after(0, lambda: self._finish_install(False, f"Install failed: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _finish_install(self, ok, msg):
        self._set_busy(False, msg)
        self._refresh_states()

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
        self._mods_animating  = False
        self._mods_anim_job   = None
        self._mods_anim_phase = 0
        self._patch_animating  = False
        self._patch_anim_job   = None
        self._patch_anim_phase = 0
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

        _section_label(self, "Path to 'A Township Tale.exe'")
        pf = _field(self)
        self.v_exe = tk.StringVar()
        self.v_exe.trace_add("write", self._on_exe_changed)
        tk.Entry(pf, textvariable=self.v_exe, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10),
                 bd=6).pack(side="left", fill="x", expand=True)
        _btn(pf, "Browse", self._browse, font=("Segoe UI",9),
             padx=10, pady=6).pack(side="right")
        btn_row_mods = tk.Frame(self, bg=BG)
        btn_row_mods.pack(fill="x", padx=20, pady=(4,0))
        self._patch_btn = _btn(btn_row_mods, "🩹 Patch", self._on_patch_click,
             font=("Segoe UI",9), pady=5, padx=10)
        self._patch_btn.pack(side="left")
        self._mods_btn = _btn(btn_row_mods, "🧪 Mods", self._open_mods,
             font=("Segoe UI",9), pady=5, padx=10)
        self._mods_btn.pack(side="left", padx=(6,0))
        _hint(self, "Please install the above mods in order before you launch the game")

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
        self.v_platform = tk.StringVar(value="SteamVR")
        _mk_combobox(pf2, self.v_platform, ["SteamVR","Quest"])

        _divider(self)

        _section_label(self, "Destination (leave blank for localhost)")
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
        _btn(btn_row_dest, "🎫 Tickets",           self._open_tickets,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")

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
        self._token_animating = False
        self._token_anim_job  = None
        self._token_anim_phase = 0
        self._token_btn = tk.Button(canvas, text="🔑 Token", bg=SURF2, fg=AMBER,
                                    activebackground=AMBERDIM, activeforeground="#ffd080",
                                    relief="flat", bd=0, cursor="hand2",
                                    font=("Segoe UI",9,"bold"), padx=10, pady=4,
                                    command=self._on_token_button_click)
        self._token_btn_item = canvas.create_window(0, 32, anchor="e",
                                                     window=self._token_btn, state="hidden")

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
        """Reveal the token badge. Called at startup if a token file already
        exists, and after every successful connection. Only starts the
        flash if the player hasn't already clicked through the "Yes, I
        understand" acknowledgment — once they have, it stays a plain,
        non-flashing button for the rest of time, on this machine."""
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
        if not self._token_animating and not load_cfg().get("token_ack", False):
            self._start_token_animation()

    def _start_token_animation(self):
        self._token_animating = True
        self._token_anim_phase = 0
        self._animate_token_btn()

    def _stop_token_animation(self):
        self._token_animating = False
        if self._token_anim_job:
            try: self.after_cancel(self._token_anim_job)
            except Exception: pass
            self._token_anim_job = None
        try: self._token_btn.config(bg=SURF2, fg=AMBER)
        except Exception: pass

    def _animate_token_btn(self):
        if not self._token_animating: return
        bg, fg = (SURF2, AMBER) if self._token_anim_phase % 2 == 0 else ("#5a3d0e", "#ffd080")
        try: self._token_btn.config(bg=bg, fg=fg)
        except Exception: return
        self._token_anim_phase += 1
        self._token_anim_job = self.after(450, self._animate_token_btn)

    def _on_token_button_click(self):
        win = tk.Toplevel(self)
        win.title("About Your Token File")
        win.configure(bg=BG)
        win.resizable(False, False)
        _set_window_icon(win)
        tk.Label(win, text=self._token_note, bg=BG, fg=PARCH, justify="left",
                 wraplength=360, font=("Segoe UI",9)).pack(padx=20, pady=(20,16))

        def _ack():
            cfg = load_cfg()
            cfg["token_ack"] = True
            save_cfg(cfg)
            self._stop_token_animation()
            win.destroy()

        _btn(win, "Yes, I understand", _ack, "primary",
             font=("Segoe UI",10,"bold"), pady=10).pack(fill="x", padx=20, pady=(0,20))
        win.update_idletasks()
        win.geometry(f"400x{win.winfo_reqheight()}")
        _enable_dark_titlebar(win)
        win.transient(self)
        win.grab_set()

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

    # ── Patch button ────────────────────────────────────────────────────────

    def _refresh_patch_alert(self, exe):
        """Flash the Patch button only while the patch DLL is actually
        present AND not already applied — a real on-disk check (see
        _patch_is_applied), so it correctly reflects reality even if the
        other launcher (client/server) already did this for the same game."""
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
                "Please set the path to 'A Township Tale.exe' above first.", parent=self)
            return

        def worker():
            try:
                apply_patch(exe)
                self.after(0, lambda: (
                    messagebox.showinfo("Patch applied",
                        "Root.Township.dll has been replaced with the Tavern patch.", parent=self),
                    self._refresh_patch_alert(exe)))
            except RuntimeError as e:
                self.after(0, lambda err=str(e): messagebox.showerror("Patch failed", err, parent=self))
        threading.Thread(target=worker, daemon=True).start()

    # ── Persistence ────────────────────────────────────────────────────────────

    def _load(self):
        cfg = load_cfg()
        self.v_exe.set(cfg.get("game_exe",""))
        self.v_username.set(cfg.get("username",""))
        # "none" (flatscreen) is temporarily disabled — exploitable — so a
        # value saved before this change doesn't silently keep working just
        # because it's already sitting in the user's config file. Also
        # translates a pre-rename save ("OpenVR"/"Oculus") to the current
        # display names, so upgrading doesn't silently reset this choice.
        saved_platform = cfg.get("platform", "SteamVR")
        saved_platform = PLATFORM_LEGACY_TO_DISPLAY.get(saved_platform, saved_platform)
        self.v_platform.set(saved_platform if saved_platform in ("SteamVR", "Quest") else "SteamVR")
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
            result = _updater.check_for_update(APP_VERSION, UPDATE_APP_FOLDER)
            if result:
                tag, url = result
                self.after(0, lambda: self._prompt_launcher_update(tag, url))
        threading.Thread(target=worker, daemon=True).start()

    def _prompt_launcher_update(self, tag, url):
        if not messagebox.askyesno("Update Available",
                f"A new version is available: {tag} (you have {APP_VERSION}).\n\n"
                "Update now? The launcher will restart automatically.", parent=self):
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
                    "The current version is unaffected — nothing was replaced.", parent=self))
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
                "This cannot be undone. Continue?", icon="warning", parent=self):
            return
        try:
            if os.path.isfile(CONFIG_FILE):
                os.remove(CONFIG_FILE)
            messagebox.showinfo("Cache Wiped",
                "Launcher cache cleared. The app will now close — "
                "reopen it for a fresh start.", parent=self)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Wipe failed", str(e), parent=self)

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

    def _open_tickets(self):
        TicketsWindow(self, default_host=self.v_ip.get().strip(),
                     default_username=self.v_username.get().strip())

    def _open_mods(self):
        exe = self.v_exe.get().strip()
        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Game not found",
                "Please set the path to 'A Township Tale.exe' above first.", parent=self)
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
        self._tailer = GameLogTailer(GAME_LOG_PATH, on_line)
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
        platform = PLATFORM_DISPLAY_TO_BACKEND.get(platform, platform)
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

        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Not found",
                "Could not find the game.\nPlease browse to 'A Township Tale.exe'.", parent=self)
            return
        if not username:
            messagebox.showerror("Missing name",
                "Please enter your username before connecting.", parent=self)
            return
        if len(username) > USERNAME_MAX_LEN:
            messagebox.showerror("Name too long",
                f"Usernames can be at most {USERNAME_MAX_LEN} characters.", parent=self)
            return
        if not _is_valid_username(username):
            messagebox.showerror("Invalid name",
                "Usernames can only contain letters, numbers, spaces, hyphens, and underscores.", parent=self)
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

        access, refresh, identity = build_tokens(user_id, username, token)
        args = [exe, "/force_offline",
                "/access_token", access, "/refresh_token", refresh,
                "/identity_token", identity, "/join_local_server"]

        if platform == "none":
            args.insert(-1, "/fly")
        elif platform:
            args[-1:] = ["/vrmode", platform, "/join_local_server"]
        if ip:
            # Already resolved to a canonical IP above — same value used for
            # the token lookup and the auth handshake, so all three agree.
            args += ["/dev_server_ip", host]
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
        platform = PLATFORM_DISPLAY_TO_BACKEND.get(platform, platform)
        ip       = self.v_ip.get().strip()
        host     = ip if ip else "127.0.0.1"

        if not exe or not os.path.isfile(exe):
            messagebox.showerror("Not found",
                "Could not find the game.\nPlease browse to 'A Township Tale.exe'.", parent=self)
            return
        if not username:
            messagebox.showerror("Missing name",
                "Please enter your username before connecting.", parent=self)
            return
        if len(username) > USERNAME_MAX_LEN:
            messagebox.showerror("Name too long",
                f"Usernames can be at most {USERNAME_MAX_LEN} characters.", parent=self)
            return
        if not _is_valid_username(username):
            messagebox.showerror("Invalid name",
                "Usernames can only contain letters, numbers, spaces, hyphens, and underscores.", parent=self)
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

        access, refresh, identity = build_tokens(user_id, username)
        args = [exe, "/force_offline",
                "/access_token", access, "/refresh_token", refresh,
                "/identity_token", identity, "/join_local_server"]

        if platform == "none":
            args.insert(-1, "/fly")
        elif platform:
            args[-1:] = ["/vrmode", platform, "/join_local_server"]
        if ip:
            args += ["/dev_server_ip", _resolve_ip_for_game(ip)]
        args += ["/dev_server_port", str(_valid_port(self.v_port.get()))]
        if self.v_debug_helper.get():
            args.append("/debug_helper")

        self._print(f"Launching on {platform or 'default'}…", "warn")
        try:
            proc = subprocess.Popen(args, cwd=os.path.dirname(exe),
                                    **self._popen_console_kwargs())
            self._print(f"Game running (PID {proc.pid})", "ok")
        except Exception as e:
            self._print(f"Launch failed: {e}", "err")
        self._action_btn.config(state="normal")


if __name__ == "__main__":
    if _updater is not None:
        _updater.finish_update_if_requested()  # never returns if this launch is finishing an update
        _updater.cleanup_previous_update()
    app = ClientLauncher()
    app.mainloop()
