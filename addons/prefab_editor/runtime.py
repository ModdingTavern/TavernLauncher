"""Loopback RPC into the existing TavernKeeper session; never stores its token."""
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time

ROOT = Path(__file__).resolve().parent


class SessionTransport:
    def __init__(self, client):
        self.client = client
        self.pending = {}
        self.lock = threading.Lock()
        self.original = client._handle
        self.handler = self.handle
        client._handle = self.handler

    def handle(self, raw):
        try:
            message = json.loads(raw)
            if message.get('type') == 'CommandResult':
                with self.lock:
                    request = self.pending.get(message.get('commandId'))
                if request:
                    request[1]['message'] = message
                    request[0].set()
                    return  # Keep editor scans out of the console log/UI thread.
        except (ValueError, AttributeError):
            pass
        self.original(raw)

    def capture(self, command, timeout=25):
        if not self.client._connected:
            raise RuntimeError('TavernKeeper disconnected. Reconnect and start Prefab Editor again.')
        with self.client._lock:
            self.client._cmd_id += 1
            cid = self.client._cmd_id
        event, holder = threading.Event(), {}
        with self.lock:
            self.pending[cid] = (event, holder)
        try:
            self.client._ws.send(json.dumps({'id': cid, 'content': command}))
            deadline = time.monotonic() + timeout
            while not event.wait(min(.2, max(0, deadline - time.monotonic()))):
                if not self.client._connected:
                    raise RuntimeError('Console disconnected; command outcome may be unknown. Refresh before retrying.')
                if time.monotonic() >= deadline:
                    raise RuntimeError('Console timed out; command outcome may be unknown. Refresh before retrying.')
            if 'error' in holder:
                raise RuntimeError(holder['error'])
            return holder['message']
        finally:
            with self.lock:
                self.pending.pop(cid, None)

    def close(self):
        if self.client._handle is self.handler:
            self.client._handle = self.original
        with self.lock:
            for event, holder in self.pending.values():
                holder['error'] = 'Prefab Editor stopped'
                event.set()


def install(game, side):
    game = Path(game)
    if not (game / 'A Township Tale_Data').is_dir():
        raise RuntimeError('Choose the game folder containing A Township Tale_Data, not Mods or the launcher folder.')
    if not (game / 'MelonLoader').is_dir():
        raise RuntimeError('Use Tavern Launcher to patch this game with MelonLoader first.')
    files = ['PrefabEditorCore.dll'] if side == 'server' else ['PrefabEditor.dll', 'PrefabEditorCatalog.json', 'PrefabEditorImages']
    mods = game / 'Mods'
    mods.mkdir(exist_ok=True)
    for name in files:
        source, target = ROOT / 'payload' / name, mods / name
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            if target.exists() and source.read_bytes() != target.read_bytes():
                shutil.copy2(target, target.with_name(name + '.before-tavern-' + str(time.time_ns())))
            shutil.copy2(source, target)


class Bridge:
    def __init__(self, client, game, state):
        self.transport = SessionTransport(client)
        self.game, self.state = Path(game), Path(state)
        self.process = None
        self.connection = self.game / 'UserData' / 'PrefabEditorConnection.json'
        self.previous = None
        self.written = None
        self.closed = False
        self.lifecycle = threading.RLock()
        atexit.register(self.close)

    def start(self):
        try:
            reply = self.transport.capture('edit capabilities')
            data = reply.get('data', {})
            value = data.get('Result') or data.get('ResultString') if isinstance(data, dict) else None
            try:
                info = json.loads(value) if isinstance(value, str) else value
            except ValueError:
                info = None
            if not isinstance(info, dict) or info.get('tavernBridge') != 1:
                raise RuntimeError('The owner must copy PrefabEditorCore.dll from the Server-Mod-Only package into the SERVER game Mods folder, then restart the game server.')
            slots = threading.BoundedSemaphore(8)
            self.state.mkdir(parents=True, exist_ok=True)
            env = dict(os.environ, PREFAB_STATE=str(self.state))
            with self.lifecycle:
                if self.closed:
                    raise RuntimeError('Editor startup canceled')
                self.process = subprocess.Popen([str(ROOT / 'runtime' / 'node.exe'), str(ROOT / 'bridge.js')],
                    cwd=str(ROOT), env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), text=True, encoding='utf-8')
            # A reader with a deadline prevents a failed child from hanging the UI.
            ready, result = threading.Event(), {}
            write_lock = threading.Lock()
            def answer(message):
                try:
                    command = message.get('command')
                    if not isinstance(command, str) or not command.strip() or len(command) > 512000 or '\n' in command or '\r' in command:
                        raise ValueError('Invalid command')
                    reply = {'id': message['id'], 'result': self.transport.capture(command)}
                except Exception as error:
                    reply = {'id': message.get('id'), 'error': str(error)}
                finally:
                    slots.release()
                try:
                    with write_lock:
                        self.process.stdin.write(json.dumps(reply) + '\n')
                        self.process.stdin.flush()
                except (OSError, ValueError):
                    pass
            def read_messages():
                try:
                    for line in self.process.stdout:
                        message = json.loads(line)
                        if message.get('type') == 'ready':
                            result['info'] = message
                            ready.set()
                        else:
                            slots.acquire()
                            threading.Thread(target=answer, args=(message,), daemon=True).start()
                finally:
                    ready.set()
            threading.Thread(target=read_messages, daemon=True).start()
            # Drain stderr so a child error cannot fill its pipe and hang shutdown.
            threading.Thread(target=lambda: self.process.stderr.read(), daemon=True).start()
            if not ready.wait(20) or not result.get('info'):
                raise RuntimeError('Local editor helper could not start. Stop any standalone editor/workbench and try again.')
            info = result['info']
            self.url = info['panelUrl']
            with self.lifecycle:
                if self.closed:
                    raise RuntimeError('Editor startup canceled')
                self.connection.parent.mkdir(parents=True, exist_ok=True)
                self.previous = self.connection.read_bytes() if self.connection.exists() else None
                self.written = json.dumps({'panelUrl': self.url, 'managedBy': 'TavernLauncher'}).encode()
                self.connection.write_bytes(self.written)
            return self.url
        except Exception:
            self.close()
            raise

    def close(self):
        with self.lifecycle:
            if self.closed:
                return
            self.closed = True
        atexit.unregister(self.close)
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.transport.close()
        if self.written and self.connection.exists() and self.connection.read_bytes() == self.written:
            if self.previous is None:
                self.connection.unlink()
            else:
                self.connection.write_bytes(self.previous)
