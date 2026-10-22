"""
Mod installation logic (MelonLoader, TavernLib, CircuitsVoiceChat, TavernEssentials)
shared by both apps -- both need Install/Update buttons for the same mods,
and this was previously duplicated near-verbatim between att_client.py
and att_server.py. Client's copies used throughout (diff confirmed only
cosmetic drift against the server's).
"""
import os
import sys
import time
import html
import json
import re
import shutil
import socket
import hashlib
import threading
import tempfile
import zipfile
import struct
import contextlib
import urllib.request
import urllib.error
import urllib.parse
import http.client
from urllib.parse import urlparse

from tavern_shared.paths import _app_dir, _sha256_file

MELONLOADER_ZIP_URLS = {
    "x64": "https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x64.zip",
    "x86": "https://github.com/LavaGang/MelonLoader/releases/latest/download/MelonLoader.x86.zip",
}


TAVERNLIB_DOWNLOAD_URL = "https://github.com/ModdingTavern/TavernLib/releases/latest/download/TavernLib.dll"


TAVERNLIB_FILENAME = "TavernLib.dll"


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
            expected_hash = hashlib.sha256(downloaded_files[name]).hexdigest()
            with open(dest_path, "wb") as f:
                f.write(downloaded_files[name])
        else:
            expected_hash = _sha256_file(manual_paths[name])
            shutil.copy2(manual_paths[name], dest_path)
        # Controlled Folder Access can silently no-op a write; verify by reading back.
        if not os.path.isfile(dest_path) or _sha256_file(dest_path) != expected_hash:
            raise RuntimeError(
                f"{name} was written without any error, but checking it afterward shows "
                "it doesn't match what was just downloaded/copied. This usually means "
                "something on this PC silently blocked the write — most commonly Windows' "
                "Controlled Folder Access, or antivirus real-time protection. Try adding an "
                "exclusion for the game's install folder in Windows Security (or your "
                "antivirus), or temporarily disabling Controlled Folder Access, then try again.")

    meta = _load_mod_meta(game_dir)
    if downloaded_files is not None and tag:
        meta["circuitsvoicechat_tag"] = tag
    else:
        meta["circuitsvoicechat_tag"] = "bundled:local"
    _save_mod_meta(game_dir, meta)


TAVERNESSENTIALS_REPO = "ModdingTavern/TavernEssentials"
TAVERNESSENTIALS_FILENAME = "TavernEssentials.dll"
TAVERNESSENTIALS_DEST_DIR = "Mods"


def _get_tavernessentials_latest_tag():
    loc = _get_redirect_location(f"https://github.com/{TAVERNESSENTIALS_REPO}/releases/latest")
    if not loc:
        return None
    return loc.rstrip("/").split("/")[-1]


def _tavernessentials_bundled_path():
    """The copy shipped in Patch/. TavernEssentials.dll is used if it's there,
    but a versioned name like TavernEssentials-v1.2.dll is accepted too."""
    patch_dir = os.path.join(_app_dir(), "Patch")
    exact = os.path.join(patch_dir, TAVERNESSENTIALS_FILENAME)
    if os.path.isfile(exact):
        return exact
    try:
        for name in sorted(os.listdir(patch_dir)):
            low = name.lower()
            if low.startswith("tavernessentials") and low.endswith(".dll"):
                return os.path.join(patch_dir, name)
    except OSError:
        pass
    return None


def _tavernessentials_installed(game_dir):
    return os.path.isfile(os.path.join(game_dir, TAVERNESSENTIALS_DEST_DIR, TAVERNESSENTIALS_FILENAME))


def _tavernessentials_status(game_dir):
    """'missing', 'outdated', 'unknown' or 'current', same as the other mods."""
    if not _tavernessentials_installed(game_dir):
        return "missing"
    installed_tag = _load_mod_meta(game_dir).get("tavernessentials_tag")
    if not installed_tag or installed_tag.startswith("bundled:"):
        return "unknown"
    try:
        latest = _get_tavernessentials_latest_tag()
    except Exception:
        return "unknown"
    if not latest:
        return "unknown"
    return "current" if latest == installed_tag else "outdated"


def _release_asset_urls_from_page(repo, tag):
    """Every file attached to a release, whatever it's called, read from the
    release's asset list on github.com. Unlike the API this has no tight rate limit."""
    req = urllib.request.Request(
        f"https://github.com/{repo}/releases/expanded_assets/{tag}",
        headers={"User-Agent": "TavernLauncher/1.0"})
    with _force_ipv4():
        with urllib.request.urlopen(req, timeout=10) as resp:
            page = resp.read().decode("utf-8", "replace")
    return ["https://github.com" + html.unescape(path)
            for path in re.findall(r'href="(/[^"]+/releases/download/[^"]+)"', page)]


def _release_asset_urls_from_api(repo, tag):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/tags/{tag}",
        headers={"User-Agent": "TavernLauncher/1.0", "Accept": "application/vnd.github+json"})
    with _force_ipv4():
        with urllib.request.urlopen(req, timeout=10) as resp:
            release = json.load(resp)
    return [a["browser_download_url"] for a in release.get("assets", []) if a.get("browser_download_url")]


def _release_zip_urls(repo, tag, prefer):
    """The .zip files attached to a release, whatever they're named, with any
    whose name contains `prefer` tried first. The release page is read first;
    the rate limited API is only asked if that finds nothing that works out."""
    def name_of(u):  # just the file name -- the URL path also contains the repo name
        return urllib.parse.unquote(urlparse(u).path.rsplit("/", 1)[-1]).lower()
    seen = set()
    for lookup in (_release_asset_urls_from_page, _release_asset_urls_from_api):
        try:
            urls = lookup(repo, tag)
        except Exception:
            continue
        zips = [u for u in urls if name_of(u).endswith(".zip")]
        zips.sort(key=lambda u: prefer not in name_of(u))
        for u in zips:
            if u not in seen:
                seen.add(u)
                yield u


def _tavernessentials_zip_urls(tag):
    prefer = os.path.splitext(TAVERNESSENTIALS_FILENAME)[0].lower()
    return _release_zip_urls(TAVERNESSENTIALS_REPO, tag, prefer)


def _fetch_tavernessentials_dll(url, on_progress, have_bundled):
    """Downloads one release zip and returns TavernEssentials.dll's bytes."""
    tmp_zip = os.path.join(tempfile.gettempdir(), "tavern_tavernessentials_dl.zip")
    try:
        if have_bundled:
            _download_with_progress(url, tmp_zip, on_progress, connect_timeout=8, max_total_seconds=15)
        else:
            _download_with_progress(url, tmp_zip, on_progress)
        on_progress("Extracting TavernEssentials…")
        with _open_zip_with_retry(tmp_zip) as zf:
            match = _find_zip_entry(zf, TAVERNESSENTIALS_FILENAME)
            if not match:
                raise RuntimeError(f"The downloaded release zip didn't contain {TAVERNESSENTIALS_FILENAME}.")
            return zf.read(match)
    finally:
        try: os.remove(tmp_zip)
        except Exception: pass


def _install_tavernessentials(game_dir, on_progress):
    """Fetches the latest release from GitHub and puts TavernEssentials.dll in
    Mods/. Falls back to the copy in Patch/ if GitHub can't be reached or the
    download doesn't work out. Returns 'current' if the DLL on GitHub is
    identical to the one already installed (nothing is rewritten), else 'installed'."""
    bundled = _tavernessentials_bundled_path()

    tag = None
    try: tag = _get_tavernessentials_latest_tag()
    except Exception: pass

    dll_bytes, last_error = None, None
    if tag:  # no tag means GitHub isn't answering at all, so go straight to the fallback
        started = time.time()
        for url in _tavernessentials_zip_urls(tag):
            try:
                dll_bytes = _fetch_tavernessentials_dll(url, on_progress, bool(bundled))
                break
            except Exception as e:
                last_error = e
                if bundled and time.time() - started > 10:
                    break  # slow failure, not a quick 404 -- don't keep the user waiting

    if dll_bytes is None:
        if not bundled:
            detail = f"\n\n{last_error}" if last_error else ""
            raise RuntimeError("Couldn't get TavernEssentials from GitHub, and no bundled "
                               "copy was found in Patch/ either." + detail)
        on_progress("Couldn't reach GitHub — using the version bundled with this launcher…")

    dest_dir = os.path.join(game_dir, TAVERNESSENTIALS_DEST_DIR)
    os.makedirs(dest_dir, exist_ok=True)
    dest_path = os.path.join(dest_dir, TAVERNESSENTIALS_FILENAME)
    if dll_bytes is not None:
        expected_hash = hashlib.sha256(dll_bytes).hexdigest()
        try:
            unchanged = os.path.isfile(dest_path) and _sha256_file(dest_path) == expected_hash
        except OSError:
            unchanged = False
        if unchanged:
            meta = _load_mod_meta(game_dir)
            meta["tavernessentials_tag"] = tag
            _save_mod_meta(game_dir, meta)
            return "current"
        with open(dest_path, "wb") as f:
            f.write(dll_bytes)
    else:
        expected_hash = _sha256_file(bundled)
        shutil.copy2(bundled, dest_path)
    # Controlled Folder Access can silently no-op a write; verify by reading back.
    if not os.path.isfile(dest_path) or _sha256_file(dest_path) != expected_hash:
        raise RuntimeError(
            f"{TAVERNESSENTIALS_FILENAME} was written without any error, but checking it afterward "
            "shows it doesn't match what was just downloaded/copied. This usually means "
            "something on this PC silently blocked the write — most commonly Windows' "
            "Controlled Folder Access, or antivirus real-time protection. Try adding an "
            "exclusion for the game's install folder in Windows Security (or your "
            "antivirus), or temporarily disabling Controlled Folder Access, then try again.")

    meta = _load_mod_meta(game_dir)
    meta["tavernessentials_tag"] = tag if dll_bytes is not None else "bundled:local"
    _save_mod_meta(game_dir, meta)
    return "installed"


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
    for n in zf.namelist():
        if os.path.basename(n).lower() == wanted_filename.lower():
            return n
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

    # Controlled Folder Access can silently no-op extractall(); the two
    # files _melonloader_installed checks are a good-enough proxy.
    if not _melonloader_installed(game_dir):
        raise RuntimeError(
            "MelonLoader was extracted without any error, but checking afterward shows "
            "the expected files aren't actually there. This usually means something on "
            "this PC silently blocked the write — most commonly Windows' Controlled "
            "Folder Access, or antivirus real-time protection. Try adding an exclusion "
            "for the game's install folder in Windows Security (or your antivirus), or "
            "temporarily disabling Controlled Folder Access, then try again.")

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

    # Captured before the replace, since tmp_dest won't exist anymore
    # afterward — os.replace renames it, it doesn't leave a copy behind.
    expected_hash = _sha256_file(tmp_dest)
    os.replace(tmp_dest, dest)  # atomic on Windows — always a full swap, never a partial one
    if not os.path.isfile(dest) or _sha256_file(dest) != expected_hash:
        # A silently-blocked write (Controlled Folder Access is a
        # documented example) can leave os.replace appearing to succeed
        # with the old file — or nothing at all — actually still there.
        # Reading the result back and comparing is the only reliable way
        # to tell a real success apart from that.
        raise RuntimeError(
            "TavernLib.dll was written without any error, but checking it afterward "
            "shows it doesn't match what was just downloaded. This usually means "
            "something on this PC silently blocked the write — most commonly Windows' "
            "Controlled Folder Access, or antivirus real-time protection. Try adding an "
            "exclusion for the game's install folder in Windows Security (or your "
            "antivirus), or temporarily disabling Controlled Folder Access, then try again.")
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
    """True if either required mod is missing/outdated, or an optional mod
    (CircuitsVoiceChat, TavernEssentials) is outdated — the trigger for flashing the main
    window's Mods button. Deliberately not "missing" for the optional mod:
    not having opted into it is a normal, expected state, not something
    that needs attention. Network failures during the update checks never
    trigger a false alarm on their own — only a real missing install (a
    purely local, always-reliable check) does that unconditionally."""
    return (_melonloader_status(game_dir) in ("missing", "outdated") or
            _tavernlib_status(game_dir)   in ("missing", "outdated") or
            _circuitsvoicechat_status(game_dir) == "outdated" or
            _tavernessentials_status(game_dir) == "outdated")

