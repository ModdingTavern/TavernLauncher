"""
WebSocket client for the game console (port 1760). Shared by both apps --
server's local ConsoleWindow and client's RemoteConsoleWindow/TavernKeeper
all talk to the same protocol.
"""
import json
import threading

WS_CONSOLE_PORT = 1760
PING_INTERVAL   = 20

def _exception_text(exc):
    if not exc:
        return None
    if isinstance(exc, dict):
        return str(exc.get("Message") or exc.get("ClassName") or exc)
    return str(exc)

class WsConsoleClient:
    """WebSocket client for the game console on port 1760."""

    def __init__(self):
        self._ws        = None
        self._lock      = threading.Lock()
        self._connected = False
        self._cmd_id    = 0
        self._pending   = {}
        self._stop      = threading.Event()
        self._on_line   = None
        self._on_disc   = None

    def connect(self, host, token, on_line=None, on_disc=None, timeout=6):
        import websocket as _wslib
        self._on_line = on_line
        self._on_disc = on_disc
        self._stop.clear()
        try:
            ws = _wslib.WebSocket()
            ws.settimeout(timeout)
            ws.connect(f"ws://{host}:{WS_CONSOLE_PORT}")
            ws.send(token)
            raw = ws.recv()
            msg = json.loads(raw)
            if msg.get("type") == "SystemMessage":
                data = str(msg.get("data", ""))
                if "Connection Succeeded" in data:
                    ws.settimeout(None)
                    self._ws = ws
                    self._connected = True
                    threading.Thread(target=self._recv_loop, daemon=True).start()
                    threading.Thread(target=self._ping_loop, args=(ws,), daemon=True).start()
                    return True, data
                ws.close()
                return False, data
            ws.close()
            return False, f"Unexpected auth response: {msg}"
        except Exception as e:
            return False, str(e)

    def disconnect(self):
        self._stop.set()
        self._connected = False
        ws, self._ws = self._ws, None
        if ws:
            try: ws.close()
            except: pass
        with self._lock:
            for ev, holder in self._pending.values():
                holder["error"] = "Disconnected"
                ev.set()
            self._pending.clear()

    def send(self, cmd):
        """Fire and forget. Returns False if the command was not sent."""
        if not self._connected or not self._ws:
            return False
        with self._lock:
            self._cmd_id += 1
            cid = self._cmd_id
        try:
            self._ws.send(json.dumps({"id": cid, "content": cmd}))
        except Exception:
            return False
        return True

    def send_capture(self, cmd, timeout=20.0):
        if not self._connected or not self._ws:
            return "", None, "Not connected"
        with self._lock:
            self._cmd_id += 1
            cid    = self._cmd_id
            ev     = threading.Event()
            holder = {"result_string": "", "result_data": None, "error": None}
            self._pending[cid] = (ev, holder)
        try:
            self._ws.send(json.dumps({"id": cid, "content": cmd}))
        except Exception as e:
            with self._lock:
                self._pending.pop(cid, None)
            return "", None, str(e)
        ev.wait(timeout)
        with self._lock:
            self._pending.pop(cid, None)
        if not ev.is_set():
            return "", None, f"No reply after {timeout:g}s"
        return holder["result_string"], holder["result_data"], holder["error"]

    def _lost(self, ws, reason):
        """The link behind ws died. Fails every pending capture and calls
        on_disc once, however many threads notice."""
        with self._lock:
            if not self._connected or self._ws is not ws:
                return
            self._connected = False
            self._ws = None
            self._stop.set()
            for ev, holder in self._pending.values():
                holder["error"] = reason
                ev.set()
            self._pending.clear()
        try: ws.shutdown()
        except: pass
        if self._on_disc:
            self._on_disc(reason)

    def _recv_loop(self):
        ws = self._ws
        while not self._stop.is_set():
            try:
                raw = ws.recv()
                if not raw:
                    # recv() returns "" when the server sends a close frame
                    self._lost(ws, "Server closed the connection")
                    break
                self._handle(raw)
            except Exception as e:
                if not self._stop.is_set():
                    self._lost(ws, str(e) or "Connection lost")
                break

    def _ping_loop(self, ws):
        # A half-open link is only noticed when we write to it. Ping only,
        # no pong deadline, so a server that never answers is fine.
        while not self._stop.wait(PING_INTERVAL) and self._ws is ws:
            try:
                ws.ping()
            except Exception as e:
                self._lost(ws, str(e) or "Connection lost")
                break

    def _handle(self, raw):
        try:
            msg = json.loads(raw)
        except Exception:
            if self._on_line:
                self._on_line(raw + "\n")
            return
        msg_type = msg.get("type", "")
        data     = msg.get("data")
        cmd_id   = msg.get("commandId")

        if msg_type == "CommandResult":
            rs = ""
            rd = None
            err = None
            if isinstance(data, dict):
                rs = str(data.get("ResultString") or "")
                rd = data.get("Result")
                err = _exception_text(data.get("Exception"))
            elif data is not None:
                rs = str(data)
            if self._on_line:
                if err:
                    self._on_line(f"Error: {err}\n")
                elif rs and not rs.startswith("System."):
                    self._on_line(rs if rs.endswith("\n") else rs + "\n")
                elif rd is not None and rd != [] and rd != "":
                    # ResultString was a useless type name; show structured data
                    import json as _json
                    try:
                        display = _json.dumps(rd, indent=2)
                    except Exception:
                        display = str(rd)
                    self._on_line(display + "\n")
            if cmd_id is not None:
                with self._lock:
                    entry = self._pending.get(cmd_id)
                if entry:
                    entry[1]["result_string"] = rs
                    entry[1]["result_data"]   = rd
                    entry[1]["error"]         = err
                    entry[0].set()

        elif msg_type == "SystemMessage":
            text = str(data) if data else ""
            if text and self._on_line:
                self._on_line(f"[{text}]\n")
        else:
            if self._on_line:
                self._on_line(raw + "\n")

