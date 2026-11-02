"""Prefabulator connects the in-game editor using Tavern's console transport."""
import threading
import atexit
import socket
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox
from client.core.config import load_cfg
from client.core.tavernkeeper.window import TavernKeeperWindow
from client.core.addon_hooks import register_launcher_action, register_before_launch_hook
from .release import ensure_runtime
from tavern_shared.paths import _tavern_data_dir
from tavern_shared.theme import BG, PARCH, MUTED, _btn
from .runtime import Bridge, install, shared_install, SessionTransport
from .invite import PREFIX, read_code
from .settings import Settings
from .access import AccessWindow, request as access_request
from tavern_shared.ws_console_client import WsConsoleClient

_active = None
_session_lock = threading.RLock()
_preferences = Settings(Path(_tavern_data_dir()) / "prefab_editor")


def build(parent, window):
    global _active
    cfg = load_cfg()
    game = tk.StringVar(value=str(Path(cfg['game_exe']).parent) if cfg.get('game_exe') else '')
    shared = tk.BooleanVar(value=_preferences.installation(game.get()) or shared_install())
    status = tk.StringVar(value='Console connected. Starting the in-game editor connection...')
    tk.Label(parent, text='Prefabulator', bg=BG, fg=PARCH, font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=12, pady=12)
    tk.Label(parent, text='Prefabulator connects your in-game editor. All editing happens in the game.\nChoose the game folder below. Tick the shared-folder option ONLY if the server and player use that same game folder.\nClose the game before installing; for a shared folder stop BOTH server and game.\nThen reconnect, launch/join normally and press F1. Keep Prefabulator open.',
             bg=BG, fg=MUTED, justify='left', wraplength=680).pack(anchor='w', padx=12)
    tk.Entry(parent, textvariable=game, width=80).pack(fill='x', padx=12, pady=8)
    _btn(parent, 'Choose game folder', lambda: choose(), 'primary').pack(anchor='w', padx=12)
    tk.Label(parent, textvariable=status, bg=BG, fg=PARCH, justify='left', wraplength=680).pack(anchor='w', padx=12, pady=12)
    busy = [False]

    def choose():
        path = filedialog.askdirectory(parent=window, title='Choose the game folder containing A Township Tale_Data')
        if path:
            game.set(path)
            shared.set(_preferences.installation(path) or shared_install())

    def background(action, done):
        if busy[0]:
            return
        busy[0] = True
        status.set('Please wait...')
        def work():
            try:
                result = action()
                window.after(0, lambda: finish(None, result))
            except Exception as error:
                window.after(0, lambda e=str(error): finish(e, None))
        def finish(error, result):
            busy[0] = False
            status.set(error if error else done(result))
        threading.Thread(target=work, daemon=True).start()

    def install_player():
        path = game.get().strip()
        if not path:
            choose()
            path = game.get().strip()
        if path:
            use_shared = shared.get()
            def installed(_):
                if not use_shared:
                    window.after(0, start_editor)
                return ('Server and player mods installed in the shared Mods folder. Start the server, reconnect Prefabulator, then launch the game.'
                        if use_shared else 'Player mod installed. Connecting the editor...')
            def install_included():
                ensure_runtime(shared=use_shared)
                install(path, 'client', shared=use_shared)
                _preferences.save_installation(path, use_shared)
            background(install_included, installed)

    def start_editor():
        global _active
        if _active and not _active.closed:
            status.set('Prefab Editor is already running. Stop it before switching servers.')
            return
        path = game.get().strip()
        if not (Path(path) / 'Mods' / 'PrefabEditor.dll').is_file():
            status.set('Install the player mod first using the button above.')
            return
        if not window._connected:
            status.set('Close Prefabulator and reopen it to reconnect to your server.')
            return
        connection_host = window.v_host.get().strip() or '127.0.0.1'
        connection_token = window.v_token.get().strip()
        def connect_editor():
            global _active
            with _session_lock:
                if _active and not _active.closed:
                    raise RuntimeError('An editor connection is already running.')
                ensure_runtime(shared=_preferences.installation(path) or shared_install())
                bridge = Bridge(window._ws_client, path, Path(_tavern_data_dir()) / 'prefab_editor',
                                host=connection_host, token=connection_token,
                                access_transport=management_transport)
                bridge.host = connection_host
                _active = bridge
                try:
                    bridge.start()
                except Exception:
                    bridge.close()
                    raise
        background(connect_editor, lambda _: 'CONNECTED. Launch/join this server and press F1. All editing is in-game. Keep Prefabulator open.')

    def stop_editor():
        if _active and not _active.closed:
            background(_active.close, lambda _: 'Stopped. Restart the game after starting a different editor connection.')

    def update_install_label(*_):
        install_button.configure(text=('1. Update BOTH mods (server and game stopped)' if shared.get()
                                       else '1. Install / update player mod (game closed)'))
    tk.Checkbutton(parent, text='Server and player share this SAME game / Mods folder (installs both DLLs)',
                   variable=shared, command=update_install_label, bg=BG, fg=PARCH,
                   selectcolor=BG, wraplength=680, justify='left').pack(anchor='w', padx=12, pady=6)
    install_button = _btn(parent, '', install_player, 'primary')
    install_button.pack(anchor='w', padx=12, pady=6)
    shared.trace_add('write', update_install_label)
    update_install_label()
    _btn(parent, 'Retry editor connection', start_editor, 'primary').pack(anchor='w', padx=12, pady=6)
    _btn(parent, 'Disconnect editor', stop_editor).pack(anchor='w', padx=12, pady=6)
    def forget_token():
        try:
            _preferences.save(_preferences.read().get('host', ''))
            status.set('Saved token removed. Enter it in Prefabulator next session. Your address is still saved.')
        except OSError:
            status.set('Could not remove saved token. Check your user settings folder permissions.')
    _btn(parent, 'Forget saved access token', forget_token).pack(anchor='w', padx=12, pady=6)
    # Access management is intercepted on WebSocket, not the native HTTP console.
    # Personal sessions already have a transport owned by their editor bridge.
    management_transport = (None if window.v_token.get().strip().startswith('pfa1.')
                            else SessionTransport(window._ws_client))
    owner_button = _btn(parent, 'Manage Admin Access (owner)', lambda: AccessWindow(
        window, management_transport, window.v_host.get().strip() or '127.0.0.1'))
    def check_owner():
        if management_transport is None:
            return
        def check():
            try:
                result = access_request(management_transport, 'self')
                window.after(0, lambda: access_ready(result))
            except Exception as error:
                window.after(0, lambda e=str(error): status.set(e))
        threading.Thread(target=check, daemon=True).start()
    def access_ready(result):
        if result.get('owner') is True:
            owner_button.pack(anchor='w', padx=12, pady=6)
    window.after(0, start_editor)
    window.after(500, check_owner)
    window.bind('<Destroy>', lambda event: management_transport.close() if event.widget is window and management_transport else None, add='+')

    # Toplevel destruction also happens on disconnect/closing the launcher.
    def destroyed(event):
        if event.widget is window and _active and _active.transport.client is window._ws_client:
            threading.Thread(target=_active.close, daemon=True).start()
    window.bind('<Destroy>', destroyed, add='+')

    def monitor():
        if _active and not _active.closed and _active.transport.client is window._ws_client and not busy[0]:
            if not window._connected or not window._ws_client._connected or (_active.process and _active.process.poll() is not None):
                stop_editor()
                status.set('Connection stopped. Close/reopen Prefabulator to reconnect, then restart the game.')
        if window.winfo_exists():
            window.after(1500, monitor)
    window.after(1500, monitor)


class PrefabulatorWindow(TavernKeeperWindow):
    """Reuse only Tavern's connection form/auth; never build its editing tabs."""
    def _build_connect_form(self):
        super()._build_connect_form()
        self.title('Prefabulator')
        def relabel(widget):
            if isinstance(widget, tk.Label) and 'TavernKeeper' in str(widget.cget('text')):
                widget.configure(text='Prefabulator')
            if isinstance(widget, tk.Label) and str(widget.cget('text')) == 'CONSOLE TOKEN':
                widget.configure(text='MODERATOR CODE or owner console token')
            for child in widget.winfo_children():
                relabel(child)
        relabel(self)
        saved = _preferences.read()
        self.v_host.set(saved.get('host', ''))
        self.v_remember = tk.BooleanVar(value=bool(saved.get('protectedToken')))
        try:
            self.v_token.set(_preferences.token(saved))
        except Exception:
            self._connect_status.set('Saved token unavailable. Enter it again.')
        tk.Checkbutton(self, text='Save my access token and auto-connect when I launch this server',
                       variable=self.v_remember, command=self._remember_changed,
                       bg=BG, fg=PARCH, selectcolor=BG, wraplength=390).pack(fill='x', padx=20)
        tk.Label(self, text='Moderator: paste the code from your owner and click Connect; it fills in the server address.\nSaved tokens are encrypted for this Windows account.',
                 bg=BG, fg=MUTED, wraplength=390, justify='left').pack(padx=20, pady=8)
        self.v_host.trace_add('write', self._host_changed)
        self.update_idletasks()
        self.geometry('460x' + str(self.winfo_reqheight()))

    def _host_changed(self, *_):
        # Never carry a saved credential over to a different address.
        self.v_token.set('')
        self._remember_changed()

    def _remember_changed(self):
        try:
            host, token = self.v_host.get(), self.v_token.get().strip()
            if token.startswith(PREFIX):
                host, token = read_code(token)
            _preferences.save(host, token, self.v_remember.get())
        except Exception:
            self._connect_status.set('Could not save preferences. You can connect with saving unchecked.')

    def _attempt_connect(self):
        value = self.v_token.get().strip()
        if value.startswith(PREFIX):
            try:
                host, token = read_code(value)
            except ValueError as error:
                self._connect_status.set(str(error))
                return
            self.v_host.set(host)  # Changing the address clears the old token.
            self.v_token.set(token)
        self._remember_changed()
        super()._attempt_connect()

    def _connect_succeeded(self):
        for child in list(self.winfo_children()):
            child.destroy()
        self.geometry('720x620')
        self.minsize(600, 500)
        build(self, self)

    def _on_line(self, text):
        pass  # No console or editing interface in the launcher.

    def _on_disconnected(self, message):
        self._connected = False  # The connection monitor stops our helper.


def open_prefabulator(launcher):
    existing = getattr(launcher, '_prefabulator_window', None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        return
    launcher._prefabulator_window = PrefabulatorWindow(launcher)


def _same_server(a, b):
    if a.lower() == b.lower():
        return True
    try:
        return socket.gethostbyname(a) == socket.gethostbyname(b)
    except OSError:
        return False


def _auto_connect(host, game_exe, log_fn):
    """Runs in Tavern's launch worker before the game reads its editor URL."""
    global _active
    host = host.strip() or '127.0.0.1'
    game = Path(game_exe).parent
    saved = _preferences.read()
    with _session_lock:
        if _active and not _active.closed:
            if not _same_server(getattr(_active, 'host', ''), host):
                _active.close()
            elif _active.transport.client._connected and _active.process and _active.process.poll() is None:
                return
            else:
                _active.close()
        if not saved.get('protectedToken') or not _same_server(saved.get('host', ''), host):
            return
        if not (game / 'Mods' / 'PrefabEditor.dll').is_file():
            log_fn('[Prefabulator] Open Prefabulator and install the included player mod first.')
            return
        client = WsConsoleClient()
        bridge = None
        try:
            token = _preferences.token(saved)
            ok, _ = client.connect(saved['host'], token, on_line=lambda _: None,
                                   on_disc=lambda _: bridge.close() if bridge else None)
            if not ok:
                raise RuntimeError('Console connection failed')
            ensure_runtime(shared=_preferences.installation(game) or shared_install())
            bridge = Bridge(client, game, Path(_tavern_data_dir()) / 'prefab_editor',
                            host=saved['host'], token=token)
            bridge.host = saved['host']
            original_close = bridge.close
            def close_session():
                original_close()
                client.disconnect()
            bridge.close = close_session
            bridge.start()
            _active = bridge
            atexit.register(client.disconnect)
            log_fn('[Prefabulator] Connected. Press F1 in game. Keep Tavern Launcher open.')
        except Exception:
            if bridge:
                bridge.close()
            client.disconnect()
            log_fn('[Prefabulator] Auto-connect failed. Open Prefabulator to check your address/token and connect, then relaunch the game.')


register_launcher_action('prefabulator', 'Prefabulator', open_prefabulator)
register_before_launch_hook('prefabulator', _auto_connect)
