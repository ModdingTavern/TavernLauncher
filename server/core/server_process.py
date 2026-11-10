"""
The game server process the Server launcher runs, remembered in a file so
that a launcher that closed without stopping it (a crash, a kill) takes it
back over on the next open instead of starting a second server beside it.
A PID only counts as the same server when its start time and exe match.
"""
import ctypes
import json
import os
import socket
import subprocess
import sys

from tavern_shared.paths import _tavern_data_dir

PROCESS_FILE = os.path.join(_tavern_data_dir(), "server_process.json")
CONSOLE_PORT = 1760

_SYNCHRONIZE = 0x00100000
_PROCESS_TERMINATE = 0x0001
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_WAIT_TIMEOUT = 0x102
_INFINITE = 0xFFFFFFFF

if sys.platform == "win32":
    from ctypes import wintypes
    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _k32.OpenProcess.restype = wintypes.HANDLE
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.WaitForSingleObject.restype = wintypes.DWORD
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    _k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD)]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]
else:
    _k32 = None


class ServerProcess:
    """A process found by PID, with the Popen calls the launcher uses."""

    def __init__(self, pid, handle):
        self.pid = pid
        self._h = handle

    @classmethod
    def open(cls, pid):
        if not _k32:
            return None
        h = _k32.OpenProcess(_SYNCHRONIZE | _PROCESS_TERMINATE | _PROCESS_QUERY_LIMITED_INFORMATION,
                             False, int(pid))
        return cls(int(pid), h) if h else None

    def poll(self):
        return None if _k32.WaitForSingleObject(self._h, 0) == _WAIT_TIMEOUT else 0

    def wait(self, timeout=None):
        ms = _INFINITE if timeout is None else int(timeout * 1000)
        if _k32.WaitForSingleObject(self._h, ms) == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired("server", timeout)
        return 0

    def terminate(self):
        _k32.TerminateProcess(self._h, 1)

    def started(self):
        t = [wintypes.FILETIME() for _ in range(4)]
        if not _k32.GetProcessTimes(self._h, *[ctypes.byref(x) for x in t]):
            return None
        return (t[0].dwHighDateTime << 32) | t[0].dwLowDateTime

    def exe(self):
        buf = ctypes.create_unicode_buffer(32768)
        size = wintypes.DWORD(len(buf))
        if not _k32.QueryFullProcessImageNameW(self._h, 0, buf, ctypes.byref(size)):
            return None
        return buf.value

    def close(self):
        if self._h:
            _k32.CloseHandle(self._h)
            self._h = None


def _same_exe(a, b):
    return bool(a and b) and os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def remember(pid, exe):
    """Called right after the launcher starts a server."""
    p = ServerProcess.open(pid)
    if not p:
        return
    try:
        record = {"pid": p.pid, "exe": exe, "started": p.started()}
    finally:
        p.close()
    tmp = PROCESS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(record, f)
        os.replace(tmp, PROCESS_FILE)
    except OSError:
        pass


def forget():
    """Called once the server the launcher ran has exited."""
    try:
        os.remove(PROCESS_FILE)
    except OSError:
        pass


def left_running():
    """The server a previous launcher started and never stopped, still
    running, or None. A file that names anything else is removed."""
    try:
        with open(PROCESS_FILE, encoding="utf-8") as f:
            record = json.load(f)
        pid, exe, started = int(record["pid"]), record["exe"], record["started"]
    except (OSError, ValueError, KeyError, TypeError):
        forget()
        return None
    p = ServerProcess.open(pid)
    if p and p.poll() is None and started is not None and p.started() == started and _same_exe(p.exe(), exe):
        return p
    if p:
        p.close()
    forget()
    return None


def console_port_free(port=CONSOLE_PORT):
    """False while a server (any server) has the console port. UDP 1757
    can't tell: it binds fine while a server is running."""
    s = socket.socket()
    try:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        s.bind(("0.0.0.0", port))
        return True
    except OSError:
        return False
    finally:
        s.close()
