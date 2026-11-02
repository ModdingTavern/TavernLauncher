"""Loopback RPC into the existing TavernKeeper session; never stores its token."""
import atexit
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
import uuid
import urllib.request

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
            if message.get('type') == 'SystemMessage' and str(message.get('data', '')).startswith('Prefabulator access revoked'):
                self.client.disconnect()
                self.close()
                return
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


def shared_install():
    return json.loads((ROOT / 'author.json').read_text(encoding='utf-8')).get('installation') == 'shared'


def install(game, side, shared=None):
    game = Path(game)
    if not (game / 'A Township Tale_Data').is_dir():
        raise RuntimeError('Choose the game folder containing A Township Tale_Data, not Mods or the launcher folder.')
    if not (game / 'MelonLoader').is_dir():
        raise RuntimeError('Use Tavern Launcher to patch this game with MelonLoader first.')
    files = ['PrefabEditorCore.dll'] if side == 'server' else ['PrefabEditor.dll', 'PrefabEditorCatalog.json', 'PrefabEditorImages']
    if side != 'server' and (shared_install() if shared is None else shared):
        files.append('PrefabEditorCore.dll')
    for name in files:
        if not (ROOT / 'payload' / name).exists():
            raise RuntimeError('Included mod files are missing. Extract the entire Prefabulator ZIP again, including payload.')
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


class _NoConsoleRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Console redirects are not supported.')


class HttpSessionTransport:
    """One POST per command; bypass duplicate WebSocket dispatch on the server."""
    def __init__(self, client, host, token):
        if not token:
            raise RuntimeError('A console token is required.')
        host = host.strip() or '127.0.0.1'
        if any(c in host for c in '/?#@\\'):
            raise ValueError('Enter a server hostname or IP address.')
        self.client = client
        self.url = 'http://' + host + ':1761/console'
        self.token = token
        self.closed = False
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoConsoleRedirect())

    def capture(self, command, timeout=25):
        if self.closed or not self.client._connected:
            raise RuntimeError('Editor disconnected. Reconnect before sending commands.')
        with self.client._lock:
            self.client._cmd_id += 1
            cid = self.client._cmd_id
        request = urllib.request.Request(self.url,
            data=json.dumps({'id': cid, 'content': command}).encode('utf-8'),
            headers={'Authorization': 'Bearer ' + self.token,
                     'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=timeout) as response:
                reply = json.load(response)
            if reply.get('type') != 'CommandResult' or reply.get('commandId') != cid:
                raise ValueError('Unexpected console response')
            return reply
        except Exception as error:
            # Never retry or fall back to WebSocket: a failed response may
            # follow a successful mutation, and replaying it duplicates items.
            raise RuntimeError('HTTP console request failed; command outcome may be unknown. '
                               'Refresh before retrying. ' + str(error)) from error

    def close(self):
        self.closed = True
        self.token = ''


class Bridge:
    def __init__(self, client, game, state, host=None, token=None, access_transport=None):
        # Personal credentials are authenticated and authorized by the server's
        # WebSocket access handler; native HTTP only accepts the owner token.
        self.transport = (HttpSessionTransport(client, host, token)
                          if host is not None and not (token or '').startswith('pfa1.')
                          else SessionTransport(client))
        self.owns_access_transport = isinstance(self.transport, HttpSessionTransport) and access_transport is None
        self.access_transport = (access_transport or SessionTransport(client)
                                 if isinstance(self.transport, HttpSessionTransport) else self.transport)
        self.game, self.state = Path(game).resolve(), Path(state)
        self.process = None
        self.connection = self.game / 'UserData' / 'PrefabEditorConnection.json'
        self.previous = None
        self.written = None
        self.connection_records = {}
        self.closed = False
        self.close_reason = ''
        self.lifecycle = threading.RLock()
        atexit.register(self.close)

    def capture(self, command):
        # The server intercepts access queries on WebSocket for owners too.
        # Keep ordinary owner mutations on HTTP so they are never replayed.
        transport = self.access_transport if command.startswith('edit access ') else self.transport
        return transport.capture(command)

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
                    reply = {'id': message['id'], 'result': self.capture(command)}
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
                self.written = json.dumps({'panelUrl': self.url, 'managedBy': 'TavernLauncher',
                                           'sessionId': uuid.uuid4().hex}).encode()
                self.ensure_connection()
            return self.url
        except Exception:
            self.close()
            raise

    def ensure_connection(self, game=None):
        """Publish/repair the address for this live helper without restarting it."""
        with self.lifecycle:
            if (self.closed or not self.process or self.process.poll() is not None
                    or not self.transport.client._connected or not self.written):
                raise RuntimeError('Editor connection is stopped. Reconnect Prefabulator first.')
            target = ((Path(game).resolve() / 'UserData' / 'PrefabEditorConnection.json')
                      if game is not None else self.connection)
            current = target.read_bytes() if target.exists() else None
            owned = self.connection_records.get(target)
            if owned is not None and current is not None and current != self.written:
                raise RuntimeError('Another editor connection changed the game connection file. Close the other Prefabulator session and reconnect.')
            previous = owned[0] if owned is not None else current
            if current != self.written:
                target.parent.mkdir(parents=True, exist_ok=True)
                temp = target.with_name(target.name + '.' + uuid.uuid4().hex + '.tmp')
                try:
                    temp.write_bytes(self.written)
                    os.replace(temp, target)
                finally:
                    if temp.exists():
                        temp.unlink()
            if target.read_bytes() != self.written:
                raise RuntimeError('Could not verify the game connection file. Reconnect Prefabulator.')
            self.connection_records[target] = (previous, self.written)
            if target == self.connection:
                self.previous = previous
            return target

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
        if self.owns_access_transport:
            self.access_transport.close()
        for target, (previous, written) in list(self.connection_records.items()):
            try:
                if target.exists() and target.read_bytes() == written:
                    if previous is None:
                        target.unlink()
                    else:
                        target.write_bytes(previous)
            except OSError:
                pass  # Never remove a file owned by a newer launcher session.
