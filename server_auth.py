"""
The Modding Tavern — Server auth backend.

Everything the port-1762 login handshake touches: where server settings,
the user database, and the blacklist/whitelist are persisted, the
brute-force throttle, and the handshake itself. Kept separate from the GUI
so "what happens when a player connects" can be read start-to-finish
without wading through window/widget code — att_server.py imports from
here, never the other way around.
"""

import os, json, time, threading, hashlib, socket

from tavern_common import (
    AUTH_PORT, USERNAME_MAX_LEN, _is_valid_username,
    _app_dir, _tavern_data_dir, _migrate_legacy_file, _jwt,
)

# ══════════════════════════════════════════════════════════════════════════════
#  PATHS
# ══════════════════════════════════════════════════════════════════════════════

USERS_FILE     = os.path.join(_tavern_data_dir(),"users.json")
BLACKLIST_FILE = os.path.join(_tavern_data_dir(),"blacklist.json")
WHITELIST_FILE = os.path.join(_tavern_data_dir(),"whitelist.json")
SERVER_CFG     = os.path.join(_tavern_data_dir(),"server_settings.json")
CONFIG_FILE    = os.path.join(_tavern_data_dir(),"tavern_server.json")
for _old, _new in (
    (os.path.join(_app_dir(),"users.json"), USERS_FILE),
    (os.path.join(_app_dir(),"blacklist.json"), BLACKLIST_FILE),
    (os.path.join(_app_dir(),"whitelist.json"), WHITELIST_FILE),
    (os.path.join(_app_dir(),"server_settings.json"), SERVER_CFG),
    (os.path.join(os.path.expanduser("~"),".tavern_server.json"), CONFIG_FILE),
):
    _migrate_legacy_file(_old, _new)
BASE_USER_ID   = 2000000000

def load_cfg():
    try: return json.load(open(CONFIG_FILE))
    except: return {}
def save_cfg(d):
    try: json.dump(d,open(CONFIG_FILE,"w"),indent=2)
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

        if not _is_valid_username(username):
            log_fn(f"Blocked (invalid characters): '{username}' from {ip}", "warn")
            conn.sendall(json.dumps({"status":"error",
                "message":"Usernames can only contain letters, numbers, spaces, hyphens, and underscores."}).encode())
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
