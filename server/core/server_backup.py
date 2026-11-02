"""
Timed zip backups of the server's data folder (Servers\\-1).

A backup is a zip called ServerBackup_<YYYY-MM-DD_HH-MM-SS>.zip inside a
Backups folder in that same data folder. The zip holds a single top-level
folder named after the data folder ("-1"), so extracting it into the Servers
folder puts everything back where it came from.

TavernLib has the same feature for servers run without TavernLauncher; keep
the naming, the left-out folders and the retention rule identical in both.
"""
import datetime
import os
import shutil
import time
import zipfile

BACKUP_DIR_NAME = "Backups"
NAME_PREFIX = "ServerBackup_"
STAMP_FORMAT = "%Y-%m-%d_%H-%M-%S"

# Top-level folders that are not part of a backup: the backups themselves
# (or every backup would contain all the earlier ones) and the logs, which
# are diagnostics rather than server state and can be large.
EXCLUDED_DIRS = ("backups", "logs")


def backups_dir(server_dir):
    return os.path.join(server_dir, BACKUP_DIR_NAME)


def list_backups(server_dir):
    """Paths of the finished backups, oldest first."""
    folder = backups_dir(server_dir)
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for name in names:
        if name.startswith(NAME_PREFIX) and name.lower().endswith(".zip"):
            path = os.path.join(folder, name)
            try:
                found.append((os.path.getmtime(path), name, path))
            except OSError:
                pass
    found.sort()
    return [path for _mtime, _name, path in found]


def backup_due(server_dir, hours, now=None):
    """True if backups are on (hours > 0) and the newest one is at least that
    old, or there is none yet."""
    if hours <= 0:
        return False
    paths = list_backups(server_dir)
    if not paths:
        return True
    try:
        last = os.path.getmtime(paths[-1])
    except OSError:
        return True
    now = time.time() if now is None else now
    return now - last >= hours * 3600


def create_backup(server_dir, now=None):
    """Zips server_dir into its Backups folder.

    Returns (path, files_added, skipped) where skipped lists the files that
    were open in another program and so left out. Raises on any other
    problem and leaves no partial zip behind.
    """
    if not os.path.isdir(server_dir):
        raise FileNotFoundError(f"Server folder not found: {server_dir}")
    folder = backups_dir(server_dir)
    os.makedirs(folder, exist_ok=True)

    # What an earlier backup left behind if it was interrupted mid-zip.
    for name in os.listdir(folder):
        if name.startswith(NAME_PREFIX) and name.endswith(".zip.tmp"):
            try:
                os.remove(os.path.join(folder, name))
            except OSError:
                pass

    stamp = datetime.datetime.fromtimestamp(time.time() if now is None else now).strftime(STAMP_FORMAT)
    path = os.path.join(folder, f"{NAME_PREFIX}{stamp}.zip")
    n = 1
    while os.path.exists(path):
        n += 1
        path = os.path.join(folder, f"{NAME_PREFIX}{stamp}_{n}.zip")
    tmp = path + ".tmp"

    root = os.path.normpath(server_dir)
    root_name = os.path.basename(root)
    added, skipped = 0, []
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, allowZip64=True,
                             strict_timestamps=False) as zf:
            for dirpath, dirnames, filenames in os.walk(root):
                if os.path.normpath(dirpath) == root:
                    dirnames[:] = [d for d in dirnames if d.lower() not in EXCLUDED_DIRS]
                for name in filenames:
                    full = os.path.join(dirpath, name)
                    rel = os.path.relpath(full, root)
                    try:
                        src = open(full, "rb")
                    except OSError:
                        skipped.append(rel)  # in use by another program, or gone since listing
                        continue
                    with src:
                        info = zipfile.ZipInfo.from_file(full, os.path.join(root_name, rel),
                                                         strict_timestamps=False)
                        info.compress_type = zipfile.ZIP_DEFLATED
                        with zf.open(info, "w") as dest:
                            shutil.copyfileobj(src, dest, 64 * 1024)
                    added += 1
        os.replace(tmp, path)
    except BaseException:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise
    return path, added, skipped


def prune_backups(server_dir, max_backups):
    """Deletes the oldest backups so that at most max_backups remain (0 means
    keep everything). Only files matching our own naming are ever touched.
    Returns the paths removed."""
    if max_backups <= 0:
        return []
    paths = list_backups(server_dir)
    removed = []
    for path in paths[:max(0, len(paths) - max_backups)]:
        try:
            os.remove(path)
            removed.append(path)
        except OSError:
            pass
    return removed
