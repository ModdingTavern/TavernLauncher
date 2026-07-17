"""
The Modding Tavern — Client auth backend.

Everything the port-1762 login handshake touches from the client side:
where token files live, the handshake call itself, and the token-building
that turns a successful login into the game's own launch args. Kept
separate from the GUI so this can be read start-to-finish without wading
through window/widget code — att_client.py imports from here, never the
other way around.
"""

import os, json, socket, time, hashlib, secrets, glob

from tavern_common import AUTH_PORT, _app_dir, _tavern_data_dir, _migrate_legacy_file, _jwt

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
