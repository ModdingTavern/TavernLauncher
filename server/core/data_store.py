"""
Server-side persistent data: config, the unified users file (identity +
tokens), blacklist/whitelist, login throttling, live player status, and
the support-ticket backend (storage + the ticket_action request handler
itself -- NOT the admin-facing TicketsWindow UI, that's separate).
"""
import os
import sys
import re
import time
import json
import threading
import hashlib
import secrets
import unicodedata

FAIL_LIMIT, FAIL_WINDOW = 8, 60

from tavern_shared.paths import _app_dir, _tavern_data_dir, _sha256_file, _migrate_legacy_file
from tavern_shared.ws_console_client import WsConsoleClient

GAME_LOG_PATH = os.path.join(os.path.expanduser("~"), "AppData", "Roaming",
    "A Township Tale", "Servers", "-1", "Logs", "logs", "unity-log.csv")

PLAYERS_SAVE   = os.path.join(os.path.expanduser("~"),"AppData","Roaming",
    "A Township Tale","Servers","-1","Save","Players")


USERS_FILE     = os.path.join(_tavern_data_dir(),"users.json")


_LEGACY_BLACKLIST_FILE = os.path.join(_tavern_data_dir(),"blacklist.json")


_LEGACY_WHITELIST_FILE = os.path.join(_tavern_data_dir(),"whitelist.json")


SERVER_CFG     = os.path.join(_tavern_data_dir(),"server_settings.json")


CONFIG_FILE    = os.path.join(_tavern_data_dir(),"tavern_server.json")


CONSOLE_TOKEN_FILE = os.path.join(_tavern_data_dir(),"console_token.txt")
for _old, _new in (
    (os.path.join(_app_dir(),"users.json"), USERS_FILE),
    (os.path.join(_app_dir(),"blacklist.json"), _LEGACY_BLACKLIST_FILE),
    (os.path.join(_app_dir(),"whitelist.json"), _LEGACY_WHITELIST_FILE),
    (os.path.join(_app_dir(),"server_settings.json"), SERVER_CFG),
    (os.path.join(os.path.expanduser("~"),".tavern_server.json"), CONFIG_FILE),
    (os.path.join(_app_dir(),"console_token.txt"), CONSOLE_TOKEN_FILE),
):
    _migrate_legacy_file(_old, _new)

BASE_USER_ID   = 2000000000


USERNAME_MAX_LEN = 16


USERNAME_EXTRA_CHARS = " -_"


SERVER_NAME_MAX_LEN = 32


def _is_valid_name(name):
    """ASCII letters/digits plus space, hyphen, underscore. Shared character
    policy for both player usernames (mirrors the client-side filter in
    att_client.py — enforced here too since a bypassed or modified client
    could still send anything as username) and the server name field in
    Server Settings."""
    return all((c.isalnum() and c.isascii()) or c in USERNAME_EXTRA_CHARS
               for c in name)


DISCORD_URL   = "https://discord.gg/jNQUUDAYSj"


def load_cfg():
    try: return json.load(open(CONFIG_FILE))
    except: return {}


def save_cfg(d):
    try: json.dump(d,open(CONFIG_FILE,"w"),indent=2)
    except: pass


# The only real region tags the community backend will actually accept --
# "unknown" (lowercase, matching TavernLib's own default and the backend's
# fallback) is deliberately NOT in this list; it's the sentinel for
# "wasn't set to anything valid", not a selectable tag itself. Keep this
# in sync with community_server.py's own VALID_REGIONS -- that's the
# actual enforcement point since nothing else can bypass it, but matching
# it here means a server owner sees the same rejection locally instead of
# only finding out once their listing silently shows as "unknown" to
# everyone else.
VALID_REGIONS = ("EU", "NA", "SA", "Asia", "Oceania", "Africa")


def load_server_settings():
    """Every field here gets re-validated on every load, not just when the
    Settings UI saves it — editing server_settings.json directly (or an
    older version's schema, or plain corruption) would otherwise let an
    invalid name/limit/hostname sail straight through to the live ping
    response every connecting player sees, since that response is built
    from whatever this returns. This isn't a defense against a server
    owner tampering with their own launcher — they can always do that,
    same as with any local software — it's about keeping this launcher
    correct and consistent regardless of how the file got into a given
    state, and about not handing a malformed value straight to other
    people's screens just because it happened to sit unvalidated on disk."""
    try:
        ss = json.load(open(SERVER_CFG))
    except Exception:
        ss = {}
    if not isinstance(ss, dict):
        ss = {}

    name = str(ss.get("name", "")).strip()
    if not name or len(name) > SERVER_NAME_MAX_LEN or not _is_valid_name(name):
        name = "My Tavern Server"
    ss["name"] = name

    try:
        max_players = int(ss.get("max_players", 24))
    except (TypeError, ValueError):
        max_players = 24
    ss["max_players"] = max(1, min(999, max_players))

    ss["whitelist_enabled"] = bool(ss.get("whitelist_enabled", False))
    ss["enforce_ip_limit"]  = bool(ss.get("enforce_ip_limit", True))
    ss["community_listed"]  = bool(ss.get("community_listed", False))
    ss["quest_scene"]       = bool(ss.get("quest_scene", False))
    ss["tutorial_scene"]    = bool(ss.get("tutorial_scene", False))

    # Restricted to the exact set the community backend will actually
    # honor, same reasoning as VALID_REGIONS' own comment above.
    # Case-insensitive match against the canonical list, normalized to
    # its exact casing either way; anything else (including a genuinely
    # invalid/tampered value, or an older config that predates regions
    # entirely) falls back to "unknown".
    raw_region = str(ss.get("region", "")).strip()
    region = next((r for r in VALID_REGIONS if r.lower() == raw_region.lower()), "unknown")
    ss["region"] = region

    # A hash is either a real 64-char SHA256 hex digest or empty (no
    # password) — anything else can't be a value this launcher itself
    # ever wrote, so treat it as "no password" rather than trying to use
    # it as one.
    pw_hash = str(ss.get("password_hash", "") or "")
    if pw_hash and not re.fullmatch(r"[0-9a-f]{64}", pw_hash):
        pw_hash = ""
    ss["password_hash"] = pw_hash

    hostname = str(ss.get("public_hostname", "")).strip().lower().rstrip(".")
    if hostname and not re.fullmatch(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+", hostname):
        hostname = ""
    ss["public_hostname"] = hostname

    try:
        gc_timer = float(ss.get("garbage_collection_timer", 30))
        if gc_timer <= 0:
            raise ValueError
    except (TypeError, ValueError):
        gc_timer = 30.0
    ss["garbage_collection_timer"] = gc_timer

    return ss


def save_server_settings(d):
    try: json.dump(d,open(SERVER_CFG,"w"),indent=2)
    except: pass


_users_lock = threading.RLock()


def _migrate_to_unified_users_file():
    """One-time merge: this launcher used to keep the player database,
    whitelist, and blacklist as three separate files. Folds them into one
    — USERS_FILE, with "users"/"whitelist"/"blacklist" sections — so a
    server-side mod only ever needs to parse a single file. Safe to call
    every startup: a no-op once the file is already in the new shape."""
    with _users_lock:
        try:
            raw = json.load(open(USERS_FILE))
        except Exception:
            raw = {}
        if not isinstance(raw, dict):
            raw = {}

        if "users" in raw and ("whitelist" in raw or "blacklist" in raw):
            return  # already unified, nothing to do

        # Old flat format: the whole file WAS the username->record dict.
        old_users = {k: v for k, v in raw.items()
                     if k not in ("users", "whitelist", "blacklist")}

        old_bl = {"usernames": [], "user_ids": [], "ips": []}
        try:
            d = json.load(open(_LEGACY_BLACKLIST_FILE))
            old_bl["usernames"] = d.get("usernames", [])
            old_bl["user_ids"]  = d.get("user_ids", [])
            old_bl["ips"]       = d.get("ips", [])
        except Exception:
            pass

        old_wl = {"usernames": [], "ips": []}
        try:
            d = json.load(open(_LEGACY_WHITELIST_FILE))
            old_wl["usernames"] = d.get("usernames", [])
            old_wl["ips"]       = d.get("ips", [])
        except Exception:
            pass

        merged = {"users": old_users, "whitelist": old_wl, "blacklist": old_bl}
        try:
            json.dump(merged, open(USERS_FILE, "w"), indent=2)
        except Exception:
            return

        # The separate files are now redundant — remove them so nothing
        # (including a future version of this same migration) mistakes
        # them for the current source of truth.
        for p in (_LEGACY_BLACKLIST_FILE, _LEGACY_WHITELIST_FILE):
            try:
                if os.path.isfile(p): os.remove(p)
            except Exception: pass


def _load_all_data():
    """The whole unified file — {"users", "whitelist", "blacklist"} — with
    every section guaranteed present so callers never need to guard for a
    partially-populated or freshly-created file."""
    with _users_lock:
        try:
            d = json.load(open(USERS_FILE))
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault("users", {})
        wl = d.setdefault("whitelist", {})
        wl.setdefault("usernames", []); wl.setdefault("ips", [])
        bl = d.setdefault("blacklist", {})
        bl.setdefault("usernames", []); bl.setdefault("user_ids", []); bl.setdefault("ips", [])
        return d


def _save_all_data(d):
    with _users_lock:
        try: json.dump(d, open(USERS_FILE, "w"), indent=2)
        except Exception: pass


def _load_users():
    return _load_all_data()["users"]


def _save_users(u):
    with _users_lock:
        d = _load_all_data(); d["users"] = u; _save_all_data(d)


def _load_bl():
    return _load_all_data()["blacklist"]


def _save_bl(d):
    with _users_lock:
        full = _load_all_data(); full["blacklist"] = d; _save_all_data(full)


def _load_wl():
    return _load_all_data()["whitelist"]


def _save_wl(d):
    with _users_lock:
        full = _load_all_data(); full["whitelist"] = d; _save_all_data(full)


# TavernLib itself writes to this file (its own AuthManager handles the
# actual register_whitelist_application request on port 1762 -- this
# works the same way for headless servers with no TavernLauncher running
# at all, not just ones managed through this server.exe). Same JSON shape
# either way: {"requests": [{"username", "ip", "applied_at"}, ...]}.
WHITELIST_REQUESTS_FILE = os.path.join(_tavern_data_dir(), "whitelist_requests.json")


def _load_whitelist_requests():
    try:
        with open(WHITELIST_REQUESTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("requests", []) if isinstance(data, dict) else []
    except Exception:
        return []


def _save_whitelist_requests(requests):
    with _users_lock:
        try:
            os.makedirs(os.path.dirname(WHITELIST_REQUESTS_FILE), exist_ok=True)
            with open(WHITELIST_REQUESTS_FILE, "w", encoding="utf-8") as f:
                json.dump({"requests": requests}, f, indent=2)
        except Exception:
            pass


def _approve_whitelist_request(index):
    requests = _load_whitelist_requests()
    if index < 0 or index >= len(requests):
        return False
    req = requests.pop(index)
    wl = _load_wl()
    username = (req.get("username") or "").strip()
    ip = (req.get("ip") or "").strip()
    if username and username not in wl["usernames"]:
        wl["usernames"].append(username)
    if ip and ip not in wl["ips"]:
        wl["ips"].append(ip)
    _save_wl(wl)
    _save_whitelist_requests(requests)
    if ip and username:
        _set_whitelist_comment(ip, username)
    return True


# Kept in its own file rather than added to users.json's whitelist section
# -- TavernLib rewrites that whole file from its own C# object model on
# every player join, which has no "comments" property at all, so
# anything we wrote there would silently vanish on the next join.
WHITELIST_COMMENTS_FILE = os.path.join(_tavern_data_dir(), "whitelist_comments.json")


def _load_whitelist_comments():
    try:
        with open(WHITELIST_COMMENTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_whitelist_comments(comments):
    with _users_lock:
        try:
            os.makedirs(os.path.dirname(WHITELIST_COMMENTS_FILE), exist_ok=True)
            with open(WHITELIST_COMMENTS_FILE, "w", encoding="utf-8") as f:
                json.dump(comments, f, indent=2)
        except Exception:
            pass


def _set_whitelist_comment(value, comment):
    comments = _load_whitelist_comments()
    if comment:
        comments[value] = comment
    else:
        comments.pop(value, None)
    _save_whitelist_comments(comments)


def _deny_whitelist_request(index):
    requests = _load_whitelist_requests()
    if index < 0 or index >= len(requests):
        return False
    requests.pop(index)
    _save_whitelist_requests(requests)
    return True


def _is_blacklisted(username, user_id, ip):
    # user_id is no longer checked here — blacklisting by UID never made
    # much sense to begin with, since a banned player could just get a new
    # one by registering under a different username. Kept as a parameter
    # for call-site compatibility, just unused now.
    bl = _load_bl()
    if username and username.lower() in [u.lower() for u in bl["usernames"]]: return True
    if ip and ip in bl["ips"]: return True
    return False


def _is_whitelisted(username, ip):
    ss = load_server_settings()
    if not ss.get("whitelist_enabled"): return True
    wl = _load_wl()
    if username and username.lower() in [u.lower() for u in wl["usernames"]]: return True
    if ip and ip in wl["ips"]: return True
    return False


def kick_player(username, ban=False):
    """Kick (and optionally ban) a player via the WebSocket console."""
    try:
        with open(CONSOLE_TOKEN_FILE) as f:
            token = f.read().strip()
    except Exception:
        return False, "console_token.txt not found — start the server first"
    ws = WsConsoleClient()
    ok, msg = ws.connect("127.0.0.1", token)
    if not ok:
        return False, f"Console not available: {msg}"
    cmd = f'player ban "{username}"' if ban else f'player kick "{username}"'
    rs, rd, err = ws.send_capture(cmd, timeout=6)
    ws.disconnect()
    if err:
        return False, err
    return True, rs or "Done"


_fail_counts = {}


_fail_lock   = threading.Lock()


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


TICKETS_FILE = os.path.join(_tavern_data_dir(), "tickets.json")


_tickets_lock = threading.RLock()


TICKET_TITLE_MAX_LEN   = 80


TICKET_DESC_MAX_LEN     = 2000


TICKET_MESSAGE_MAX_LEN  = 1000


TICKET_MAX_ACTIVE_PER_USER      = 3


TICKET_CREATE_COOLDOWN_SECONDS  = 60


def _clean_ticket_text(s, max_len):
    """Strips control/formatting characters (a stray bidi override, embedded
    nulls/escapes, etc.) before truncating to max_len. Same reasoning as the
    community list's name filtering — this text gets rendered back out
    verbatim in a Tkinter Text widget on the server owner's screen (and, for
    a reply, the original player's screen too), so it's worth cleaning
    rather than trusting it's already well-formed just because it came
    through the normal ticket flow. Unlike the community list's name check,
    this strips rather than rejects outright — a stressed player submitting
    a support ticket shouldn't get bounced over an invisible paste artifact
    they didn't even know was there."""
    s = str(s)[:max_len * 2]  # a generous pre-truncate so a huge string can't make this slow
    cleaned = "".join(c for c in s if not unicodedata.category(c).startswith("C") or c in "\n\t")
    return cleaned.strip()[:max_len]


def _load_tickets():
    with _tickets_lock:
        try:
            d = json.load(open(TICKETS_FILE))
        except Exception:
            d = {}
        if not isinstance(d, dict):
            d = {}
        d.setdefault("tickets", [])
        return d


def _save_tickets(d):
    with _tickets_lock:
        try: json.dump(d, open(TICKETS_FILE, "w"), indent=2)
        except Exception: pass


def _handle_ticket_request(req, ip, log_fn):
    """Dispatches one ticket_action request and returns the dict to send
    back as the JSON response. Every action requires a real, already-
    registered username+token pair — the same identity binding used for
    joining — checked before anything else runs."""
    username = str(req.get("username","")).strip()
    token    = str(req.get("token","")).strip()
    action   = str(req.get("ticket_action","")).strip()

    if not username or not token:
        return {"status":"error","message":"Missing credentials."}
    if len(token) > 128 or len(username) > USERNAME_MAX_LEN:
        return {"status":"error","message":"Invalid credentials."}

    users = _load_users()
    entry = users.get(username.lower())
    if not entry or str(entry.get("token") or "") != token:
        return {"status":"error",
                "message":"Not recognized — join the server at least once first."}

    if _is_blacklisted(username, entry.get("user_id"), ip):
        return {"status":"error","message":"You are not permitted."}

    if action == "create":
        return _ticket_create(username, req)
    elif action == "list_mine":
        return _ticket_list_mine(username)
    elif action == "respond":
        return _ticket_respond(username, req)
    elif action == "close":
        return _ticket_close(username, req)
    return {"status":"error","message":"Unknown ticket action."}


def _ticket_create(username, req):
    title       = _clean_ticket_text(req.get("title",""), TICKET_TITLE_MAX_LEN)
    description = _clean_ticket_text(req.get("description",""), TICKET_DESC_MAX_LEN)
    server      = _clean_ticket_text(req.get("server",""), 120)
    if not title or not description:
        return {"status":"error","message":"Title and description are required."}

    with _tickets_lock:
        data = _load_tickets()
        tickets = data["tickets"]
        mine = [t for t in tickets if t["username"].lower() == username.lower()]
        open_count = sum(1 for t in mine if t["status"] == "open")
        if open_count >= TICKET_MAX_ACTIVE_PER_USER:
            return {"status":"error",
                    "message": f"You already have {TICKET_MAX_ACTIVE_PER_USER} active "
                               "tickets. Close one before opening another."}
        if mine:
            last_created = max(t["created_at"] for t in mine)
            elapsed = time.time() - last_created
            if elapsed < TICKET_CREATE_COOLDOWN_SECONDS:
                wait = int(TICKET_CREATE_COOLDOWN_SECONDS - elapsed)
                return {"status":"error",
                        "message": f"Please wait {wait}s before opening another ticket."}

        now = time.time()
        ticket = {
            "ticket_id":   secrets.token_urlsafe(8),
            "username":    username,
            "server":      server,
            "title":       title,
            "description": description,
            "status":      "open",
            "created_at":  now,
            "updated_at":  now,
            "closed_by":   None,
            "comments":    [],
        }
        tickets.append(ticket)
        _save_tickets(data)
    return {"status":"ok","ticket_id":ticket["ticket_id"]}


def _tickets_needing_owner_attention():
    """Open tickets where the player spoke last (or hasn't gotten any
    reply at all yet) -- used purely for the flashing Tickets/Players
    indicators, not for anything that affects actual ticket handling."""
    data = _load_tickets()
    count = 0
    for t in data["tickets"]:
        if t["status"] != "open":
            continue
        comments = t.get("comments", [])
        if not comments or comments[-1].get("from") == "player":
            count += 1
    return count


def _ticket_list_mine(username):
    data = _load_tickets()
    mine = [t for t in data["tickets"] if t["username"].lower() == username.lower()]
    mine.sort(key=lambda t: t["updated_at"], reverse=True)
    return {"status":"ok","tickets":mine}


def _ticket_respond(username, req):
    ticket_id = str(req.get("ticket_id","")).strip()
    message   = _clean_ticket_text(req.get("message",""), TICKET_MESSAGE_MAX_LEN)
    if not ticket_id or not message:
        return {"status":"error","message":"Missing ticket_id or message."}
    with _tickets_lock:
        data = _load_tickets()
        for t in data["tickets"]:
            if t["ticket_id"] == ticket_id:
                if t["username"].lower() != username.lower():
                    return {"status":"error","message":"That's not your ticket."}
                if t["status"] != "open":
                    return {"status":"error","message":"This ticket is closed."}
                t["comments"].append({"from":"player","message":message,"at":time.time()})
                t["updated_at"] = time.time()
                _save_tickets(data)
                return {"status":"ok"}
    return {"status":"error","message":"Ticket not found."}


def _ticket_close(username, req):
    ticket_id = str(req.get("ticket_id","")).strip()
    message   = _clean_ticket_text(req.get("message",""), TICKET_MESSAGE_MAX_LEN)
    if not ticket_id:
        return {"status":"error","message":"Missing ticket_id."}
    with _tickets_lock:
        data = _load_tickets()
        for t in data["tickets"]:
            if t["ticket_id"] == ticket_id:
                if t["username"].lower() != username.lower():
                    return {"status":"error","message":"That's not your ticket."}
                if t["status"] != "open":
                    return {"status":"error","message":"Already closed."}
                if message:
                    t["comments"].append({"from":"player","message":message,"at":time.time()})
                t["status"]     = "closed"
                t["closed_by"]  = "player"
                t["updated_at"] = time.time()
                _save_tickets(data)
                return {"status":"ok"}
    return {"status":"error","message":"Ticket not found."}

