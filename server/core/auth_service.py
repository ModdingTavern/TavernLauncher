"""
The auth-port service (port 1762): the single TCP socket every client
handshake, ping, and ticket request goes through, plus the JWT/console-
token construction used once a login is accepted.

Addon dispatch: _handle_auth no longer hardcodes anything about custom
asset bundles (or any other addon-provided request type) -- it just
walks _auth_dispatch_handlers, in registration order, and the first
predicate that matches handles the request. An addon-free build has an
empty list here and this loop is a no-op.
"""
import os
import sys
import json
import time
import socket
import threading
import base64
import hashlib
import hmac as _hmac
import datetime

from server.core.data_store import (
    load_cfg, load_server_settings, _throttle_ok, _record_fail,
    _pw_throttle_ok, _record_pw_fail, _read_live_player_status,
    _handle_ticket_request, _is_blacklisted, _is_whitelisted,
    _load_users, _save_users, _users_lock, BASE_USER_ID,
    CONSOLE_TOKEN_FILE, USERNAME_MAX_LEN, _is_valid_name,
    MAX_ACCOUNTS_PER_IP, PW_FAIL_LIMIT, _pw_fail_counts,
    _load_whitelist_requests, _save_whitelist_requests,
)
from tavern_shared.paths import _tavern_data_dir

AUTH_PORT = 1762

# ── addon dispatch registry ─────────────────────────────────────────────
_auth_dispatch_handlers = []


def register_auth_handler(predicate, handler):
    """predicate(req) -> bool decides whether this handler applies;
    handler(conn, req, ip, log_fn) does the work and must itself call
    conn.sendall(...) and return -- core's _handle_auth returns
    immediately once a predicate matches, same as its own built-in
    ping/ticket_action branches always have."""
    _auth_dispatch_handlers.append((predicate, handler))


SERVER_SECRET_FILE = os.path.join(_tavern_data_dir(), "server_secret.key")


def _load_or_create_server_secret():
    """
    Load the persistent per-machine server secret, or generate one if it
    doesn't exist. Stored as a 64-char hex string. Never changes unless
    the file is deleted, so console_token stays stable across restarts.
    Called fresh every time a token needs signing (see _jwt) rather than
    cached once — so deleting the file while the launcher is already
    running gets noticed and recreated on the next server start, not only
    on a full launcher restart.
    """
    if os.path.isfile(SERVER_SECRET_FILE):
        try:
            secret = bytes.fromhex(open(SERVER_SECRET_FILE).read().strip())
            if len(secret) == 32:
                return secret
        except Exception:
            pass
    secret = os.urandom(32)
    try:
        os.makedirs(_tavern_data_dir(), exist_ok=True)
        with open(SERVER_SECRET_FILE, "w") as f:
            f.write(secret.hex())
    except Exception:
        pass
    return secret


def _b64url(b): return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _jwt(payload, key=None):
    """Build a HS256 JWT signed with key (defaults to the server secret).
    Deliberately re-checks the secret file's actual current state on every
    call rather than caching it once — if server_secret.key gets deleted
    while the launcher is already running, this is what notices that on
    the next server start and recreates it, instead of only noticing on a
    full launcher restart (which is what re-running the module-level load
    used to depend on)."""
    if key is None:
        key = _load_or_create_server_secret()
    h = _b64url(b'{"alg":"HS256","typ":"JWT"}')
    b = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    s = _b64url(_hmac.new(key, f"{h}.{b}".encode(), hashlib.sha256).digest())
    return f"{h}.{b}.{s}"


def build_console_token():
    """
    Build the console auth token signed with this server's unique secret.
    Written to console_token.txt — the only credential the WS console accepts.
    """
    return _jwt({
        "UserId": "0", "Username": "Server", "role": "Access",
        "is_verified": "True", "is_member": "True", "server_id": "-1",
        "Policy": ["offline", "play_offline", "server_access_pre_alpha",
                   "game_access_public", "server_owner", "debug_features",
                   "database_admin", "reuse_refresh_tokens"],
        "exp": 9999999999, "iss": "AltaWebAPI", "aud": "AltaClient"
    })  # signed with the current server secret — see _jwt()


def build_server_tokens():
    """Build game tokens signed with 'offline' as the engine expects.
    These are NOT used for console auth."""
    exp = 9999999999
    key = b"offline"
    a = _jwt({"UserId":"0","Username":"Server","role":"Access","is_verified":"True",
              "is_member":"True","server_id":"-1",
              "Policy":["offline","play_offline","server_access_pre_alpha",
              "game_access_public","server_owner","debug_features","database_admin",
              "reuse_refresh_tokens"],"exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"}, key)
    r = _jwt({"UserId":"0","role":"Refresh","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"}, key)
    i = _jwt({"UserId":"0","Username":"Server","role":"Identity","is_member":"True",
              "is_dev":"True","exp":exp,"iss":"AltaWebAPI","aud":"AltaClient"}, key)
    return a, r, i


def _handle_auth(conn, addr, log_fn):
    ip = addr[0] if addr else "?"
    try:
        conn.settimeout(5)
        if not _throttle_ok(ip):
            conn.sendall(json.dumps({"status":"error","message":"Too many attempts."}).encode())
            return
        data = conn.recv(65536)
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

        # ── support tickets — isolated from the main join flow below, so
        # this can never affect (or be affected by) the whitelist/password
        # gate meant for actually joining the game ──
        if req.get("ticket_action"):
            resp = _handle_ticket_request(req, ip, log_fn)
            conn.sendall(json.dumps(resp).encode())
            return

        # ── whitelist applications — same whitelist_requests.json format
        # and location TavernLib's own AuthManager uses for headless
        # servers, so Player Manager sees requests the same way whether
        # this server is running through TavernLauncher or standalone.
        # IP is taken from the actual socket, never trusted from the
        # payload, same reasoning as the TavernLib side. ──
        if req.get("register_whitelist_application"):
            username = str(req.get("username","")).strip()
            if not username:
                conn.sendall(json.dumps({"status":"error","message":"Missing username"}).encode())
                return
            requests = _load_whitelist_requests()
            already_pending = any(
                r.get("username","").lower() == username.lower() and r.get("ip") == ip
                for r in requests
            )
            if not already_pending:
                requests.append({
                    "username": username, "ip": ip,
                    "applied_at": datetime.datetime.utcnow().isoformat() + "Z",
                })
                _save_whitelist_requests(requests)
            conn.sendall(json.dumps({
                "status": "whitelist_application_received",
                "already_pending": already_pending,
            }).encode())
            return

        # ── addon dispatch — e.g. custom_models registers handlers for
        # asset_manifest_request/asset_download_request here, if that addon
        # is part of this build. Core has zero knowledge of what (if
        # anything) is registered; an addon-free build just skips this
        # loop entirely. ──
        for predicate, handler in _auth_dispatch_handlers:
            if predicate(req):
                handler(conn, req, ip, log_fn)
                return

        username = str(req.get("username","")).strip()
        token    = str(req.get("token","")).strip()
        pw_hash  = str(req.get("password","")).strip()

        if not username or not token:
            conn.sendall(json.dumps({"status":"error","message":"Missing credentials."}).encode())
            return

        # A real token is secrets.token_urlsafe(18) (~24 chars) and a real
        # password field is a SHA256 hex digest (exactly 64 chars) — anything
        # wildly longer than that can't be legitimate, and rejecting it here
        # means an oversized value never gets as far as being persisted into
        # users.json (bounding what disk space a bypassed/modified client can
        # bloat by hammering registration with huge junk tokens).
        if len(token) > 128:
            log_fn(f"Blocked (token too long) from {ip}", "warn")
            conn.sendall(json.dumps({"status":"error","message":"Invalid token."}).encode())
            return
        if len(pw_hash) > 128:
            log_fn(f"Blocked (password field too long) from {ip}", "warn")
            conn.sendall(json.dumps({"status":"error","message":"Invalid password."}).encode())
            return

        if len(username) > USERNAME_MAX_LEN:
            log_fn(f"Blocked (name too long): '{username[:USERNAME_MAX_LEN]}…' from {ip}", "warn")
            conn.sendall(json.dumps({"status":"error",
                "message": f"Usernames can be at most {USERNAME_MAX_LEN} characters."}).encode())
            return

        if not _is_valid_name(username):
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
                users[key] = {"user_id": user_id, "token": token,
                              "registered_from": ip, "roles": []}
                _save_users(users)
                log_fn(f"New player: '{username}' (ID {user_id}) from {ip}", "ok")

        if _is_blacklisted(username, user_id, ip):
            conn.sendall(json.dumps({"status":"error","message":"You are not permitted."}).encode())
            return

        log_fn(f"'{username}' (ID {user_id}) from {ip}", "ok")
        conn.sendall(json.dumps({"status":"ok","user_id":user_id,
                                  "quest_scene_required": bool(ss.get("quest_scene", False)),
                                  "tutorial_scene_required": bool(ss.get("tutorial_scene", False))}).encode())
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

