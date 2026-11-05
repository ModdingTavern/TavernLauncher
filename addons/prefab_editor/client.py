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
from .runtime import Bridge, connection_diagnostics, install, shared_install, SessionTransport
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
    tk.Label(parent, textvariable=window._server_status, bg=BG, fg=PARCH, justify='left', wraplength=680).pack(anchor='w', padx=12, pady=8)
    tk.Entry(parent, textvariable=game, width=80).pack(fill='x', padx=12, pady=8)
    _btn(parent, 'Choose game folder', lambda: choose(), 'primary').pack(anchor='w', padx=12)
    tk.Label(parent, textvariable=status, bg=BG, fg=PARCH, justify='left', wraplength=680).pack(anchor='w', padx=12, pady=12)
    busy = [False]
    tracked_bridge = [None]
    details = tk.StringVar(value='')
    tk.Label(parent, textvariable=details, bg=BG, fg=MUTED, justify='left', wraplength=680).pack(anchor='w', padx=12, pady=4)

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

    def connection_ready(bridge, path):
        target = Path(path).resolve() / 'UserData' / 'PrefabEditorConnection.json'
        details.set('Local connection file: ' + str(target) + '\nLocal editor: ' + bridge.url)
        return 'CONNECTED. If the game is already open, close and relaunch the player game. Keep Prefabulator open.'

    def start_editor():
        path = game.get().strip()
        if not (Path(path) / 'Mods' / 'PrefabEditor.dll').is_file():
            status.set('Install the player mod first using the button above.')
            return
        if not window._connected:
            status.set('Close Prefabulator and reopen it to reconnect to your server.')
            return
        connection_host = window.v_host.get().strip() or '127.0.0.1'
        connection_token = window.v_token.get().strip()
        game_host = window._game_host or connection_host
        def connect_editor():
            global _active
            with _session_lock:
                if _active and not _active.closed:
                    if not _same_server(getattr(_active, 'host', ''), connection_host) or not _same_server(getattr(_active, 'game_host', _active.host), game_host):
                        raise RuntimeError('Disconnect the existing editor before changing servers.')
                    _active.ensure_connection(path)
                    tracked_bridge[0] = _active
                    return _active
                ensure_runtime(shared=_preferences.installation(path) or shared_install())
                bridge = Bridge(window._ws_client, path, Path(_tavern_data_dir()) / 'prefab_editor',
                                host=connection_host, token=connection_token,
                                access_transport=management_transport)
                bridge.host = connection_host
                bridge.game_host = game_host
                _active = bridge
                tracked_bridge[0] = bridge
                try:
                    bridge.start()
                except Exception as error:
                    bridge.close_reason = 'Editor connection failed: ' + str(error)
                    bridge.close()
                    raise
                return bridge
        background(connect_editor, lambda bridge: connection_ready(bridge, path))

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
    if window._launcher is not None:
        _btn(parent, 'Change server / reconnect', window._reopen_connection, 'primary').pack(anchor='w', padx=12, pady=6)
    connection_actions = tk.Frame(parent, bg=BG)
    connection_actions.pack(anchor='w', padx=12, pady=6)
    _btn(connection_actions, 'Retry editor connection', start_editor, 'primary').pack(side='left')
    _btn(connection_actions, 'Disconnect editor', stop_editor).pack(side='left', padx=6)
    _btn(connection_actions, 'Connection diagnostics', lambda: window._show_connection_diagnostics(game.get().strip())).pack(side='left')
    def forget_token():
        try:
            _preferences.save(_preferences.read().get('host', ''), game_host=_preferences.read().get('gameHost'))
            status.set('Saved token removed. Enter it in Prefabulator next session. Your address is still saved.')
        except OSError:
            status.set('Could not remove saved token. Check your user settings folder permissions.')
    _btn(parent, 'Forget saved access token', forget_token).pack(anchor='w', padx=12, pady=6)
    # Access management is intercepted on WebSocket, not the native HTTP console.
    # Personal sessions already have a transport owned by their editor bridge.
    management_transport = (None if window.v_token.get().strip().startswith('pfa1.')
                            else SessionTransport(window._ws_client))
    access_window = [None]

    def show_access():
        existing = access_window[0]
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        access_window[0] = AccessWindow(window, management_transport,
                                       window._game_host or window.v_host.get().strip() or '127.0.0.1')

    owner_button = _btn(parent, 'Manage Admin Access (owner)', show_access)
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
        bridge = tracked_bridge[0]
        if bridge is not None and not busy[0]:
            if bridge.closed:
                details.set('')
                status.set(bridge.close_reason or 'Connection stopped. Click Retry editor connection, then relaunch the player game.')
                tracked_bridge[0] = None
            elif not bridge.transport.client._connected or (bridge.process and bridge.process.poll() is not None):
                bridge.close_reason = 'Connection stopped. Reconnect Prefabulator, then relaunch the player game.'
                background(bridge.close, lambda _: bridge.close_reason)
            else:
                try:
                    bridge.ensure_connection()
                except (OSError, RuntimeError) as error:
                    status.set('Connection file unavailable: ' + str(error))
        if window.winfo_exists():
            window.after(1500, monitor)
    window.after(1500, monitor)


class PrefabulatorWindow(TavernKeeperWindow):
    """Reuse only Tavern's connection form/auth; never build its editing tabs."""
    def __init__(self, parent):
        self._launcher = parent if hasattr(parent, 'v_ip') else None
        self._launcher_trace = None
        self._game_host = None
        self._connecting_route = None
        self._server_status = tk.StringVar(master=parent, value='')
        super().__init__(parent)
        if self._launcher is not None:
            self._launcher_trace = self._launcher.v_ip.trace_add('write', self._launcher_changed)
            self.bind('<Destroy>', self._remove_launcher_trace, add='+')

    def _launcher_host(self):
        if self._launcher is not None:
            return self._launcher.v_ip.get().strip() or '127.0.0.1'
        return None

    def _show_connection_diagnostics(self, game_folder=None):
        existing = getattr(self, '_diagnostics_window', None)
        if existing is not None and existing.winfo_exists():
            existing.lift()
            return
        if game_folder is None:
            game_exe = load_cfg().get('game_exe')
            game_folder = str(Path(game_exe).parent) if game_exe else ''
        process = getattr(_active, 'process', None)
        helper_pid = process.pid if process and process.poll() is None else None

        dialog = tk.Toplevel(self)
        self._diagnostics_window = dialog
        dialog.title('Prefabulator connection diagnostics')
        dialog.configure(bg=BG)
        dialog.geometry('700x465')
        dialog.minsize(460, 320)
        tk.Label(dialog, text='Connection diagnostics', bg=BG, fg=PARCH,
                 font=('Segoe UI', 14, 'bold')).pack(anchor='w', padx=14, pady=12)
        frame = tk.Frame(dialog, bg=BG)
        frame.pack(fill='both', expand=True, padx=14)
        scrollbar = tk.Scrollbar(frame)
        scrollbar.pack(side='right', fill='y')
        body = tk.Text(frame, wrap='word', bg='#20252d', fg=PARCH, padx=10, pady=8,
                       font=('Segoe UI', 10), yscrollcommand=scrollbar.set)
        body.pack(side='left', fill='both', expand=True)
        scrollbar.configure(command=body.yview)
        body.insert('1.0', 'Checking the selected game folder, editor helpers and local ports...')
        body.configure(state='disabled')
        actions = tk.Frame(dialog, bg=BG)
        actions.pack(fill='x', padx=14, pady=10)
        report = []
        job = [None]

        def copy_report():
            dialog.clipboard_clear()
            dialog.clipboard_append(report[0])

        copy_button = _btn(actions, 'Copy report', copy_report)
        copy_button.configure(state='disabled')
        copy_button.pack(side='left')
        _btn(actions, 'Close', dialog.destroy).pack(side='right')

        def scan():
            try:
                report.append(connection_diagnostics(game_folder, helper_pid))
            except Exception:
                report.append('Could not complete the local diagnostics. Close this window and try again.')

        def show_report():
            job[0] = None
            if not report:
                job[0] = dialog.after(100, show_report)
                return
            body.configure(state='normal')
            body.delete('1.0', 'end')
            body.insert('1.0', report[0])
            body.configure(state='disabled')
            copy_button.configure(state='normal')

        def stop_polling(event):
            if event.widget is dialog and job[0] is not None:
                dialog.after_cancel(job[0])

        dialog.bind('<Destroy>', stop_polling, add='+')
        threading.Thread(target=scan, daemon=True).start()
        job[0] = dialog.after(100, show_report)

    def _update_server_status(self):
        host = self.v_host.get().strip() or '127.0.0.1'
        selected = self._launcher_host()
        game_host = self._game_host or host
        if self._connected and selected and not _same_server(game_host, selected):
            self._server_status.set('Connected game server: ' + game_host + '\nLauncher selected: ' + selected +
                                    '\nServer changed. Click Change server / reconnect before joining.')
        elif self._connected:
            self._server_status.set('Game server: ' + game_host + '\nConsole connection: ' + host + '\nReady to join this server from Tavern Launcher.')
        elif selected:
            self._server_status.set('Game server selected in Tavern Launcher: ' + selected + '\nConsole connection: ' + host)
        else:
            self._server_status.set('Select your game server, then connect to its console.')

    def _launcher_changed(self, *_):
        host = self._launcher_host()
        if not self._connected and not self._connecting_route and not _same_server(self._game_host or '', host):
            self._game_host = host
            self.v_local_console.set(False)
            self.v_host.set(host)  # A different game server never inherits a local-console pairing or credential.
        self._update_server_status()

    def _local_console_changed(self):
        if self._connecting_route:
            self.v_local_console.set(self._connecting_route[3])
            return
        self._game_host = self._launcher_host() or self._game_host or '127.0.0.1'
        self.v_host.set('127.0.0.1' if self.v_local_console.get() else self._game_host)
        self._update_server_status()

    def _remove_launcher_trace(self, event):
        if event.widget is self and self._launcher_trace is not None:
            self._launcher.v_ip.trace_remove('write', self._launcher_trace)
            self._launcher_trace = None

    def _reopen_connection(self):
        if self._launcher is None or getattr(self, '_reconnecting', False):
            return
        self._reconnecting = True
        def reopen():
            if self.winfo_exists():
                self._on_close()
                open_prefabulator(self._launcher)
        def stop():
            with _session_lock:
                if _active and _active.transport.client is self._ws_client:
                    _active.close()
            self.after(0, reopen)
        threading.Thread(target=stop, daemon=True).start()

    def _build_connect_form(self):
        super()._build_connect_form()
        self.title('Prefabulator')
        def relabel(widget):
            if isinstance(widget, tk.Label) and 'TavernKeeper' in str(widget.cget('text')):
                widget.configure(text='Prefabulator')
            if isinstance(widget, tk.Label) and str(widget.cget('text')) == 'SERVER IP' and self._launcher is not None:
                widget.configure(text='CONSOLE ADDRESS (set by the option below)')
            if isinstance(widget, tk.Label) and str(widget.cget('text')).startswith("Connects to a server's console"):
                widget.configure(text='Choose your game server in the main launcher. If you also host it on this computer, tick the local console option below before entering your token.')
            if isinstance(widget, tk.Entry) and str(widget.cget('textvariable')) == str(self.v_host) and self._launcher is not None:
                widget.configure(state='readonly', readonlybackground=BG, fg=PARCH)
            if isinstance(widget, tk.Label) and str(widget.cget('text')) == 'CONSOLE TOKEN':
                widget.configure(text='MODERATOR CODE or owner console token')
            for child in widget.winfo_children():
                relabel(child)
        relabel(self)
        saved = _preferences.read()
        selected = self._launcher_host() or saved.get('gameHost') or saved.get('host', '')
        self._game_host = selected or '127.0.0.1'
        same_saved_game = _same_server(saved.get('gameHost', saved.get('host', '')), self._game_host)
        use_local = same_saved_game and saved.get('gameHost') and saved.get('host') == '127.0.0.1'
        self.v_local_console = tk.BooleanVar(value=bool(use_local))
        host = '127.0.0.1' if use_local else selected
        self.v_host.set(host)
        same_saved_server = same_saved_game and _same_server(saved.get('host', ''), host)
        if self._launcher is not None:
            tk.Checkbutton(self, text='I run this server on THIS computer - connect its console through localhost',
                           variable=self.v_local_console, command=self._local_console_changed,
                           bg=BG, fg=PARCH, selectcolor=BG, wraplength=420).pack(fill='x', padx=20, pady=8)
        self.v_remember = tk.BooleanVar(value=bool(saved.get('protectedToken')))
        try:
            self.v_token.set(_preferences.token(saved) if same_saved_server else '')
        except Exception:
            self._connect_status.set('Saved token unavailable. Enter it again.')
        tk.Label(self, textvariable=self._server_status, bg=BG, fg=PARCH, wraplength=420, justify='left').pack(fill='x', padx=20, pady=8)
        self._update_server_status()
        tk.Checkbutton(self, text='Save my access token and auto-connect when I launch this server',
                       variable=self.v_remember, command=self._remember_changed,
                       bg=BG, fg=PARCH, selectcolor=BG, wraplength=390).pack(fill='x', padx=20)
        tk.Label(self, text='Moderator: paste your code and click Connect. Its server will also be selected in the main launcher.\nSaved tokens are encrypted for this Windows account.',
                 bg=BG, fg=MUTED, wraplength=390, justify='left').pack(padx=20, pady=8)
        _btn(self, 'Connection diagnostics', self._show_connection_diagnostics).pack(anchor='w', padx=20, pady=(0, 8))
        self.v_host.trace_add('write', self._host_changed)
        self.update_idletasks()
        self.geometry('460x' + str(self.winfo_reqheight()))

    def _host_changed(self, *_):
        # Never carry a saved credential over to a different address.
        self.v_token.set('')
        self._remember_changed()
        self._update_server_status()

    def _remember_changed(self):
        try:
            host, token = self.v_host.get(), self.v_token.get().strip()
            game_host = self._game_host if self.v_local_console.get() else None
            if token.startswith(PREFIX):
                host, token = read_code(token)
                game_host = None  # Invitation credentials belong only to their embedded server.
            _preferences.save(host, token, self.v_remember.get(), game_host=game_host)
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
            self.v_local_console.set(False)  # A code chooses its own console; never silently redirect it to localhost.
            self._game_host = host
            if self._launcher is not None:
                self._launcher.v_ip.set(host)  # A code selects its own server; never send it to another one.
            self.v_host.set(host)  # Changing the address clears the old token.
            self.v_token.set(token)
        self._game_host = self._launcher_host() or self._game_host or self.v_host.get()
        self._remember_changed()
        if not self.v_token.get().strip():
            self._connect_status.set('Enter your moderator code or owner console token.')
            return
        self._connecting_route = (self._game_host, self.v_host.get().strip() or '127.0.0.1', self.v_token.get().strip(), self.v_local_console.get())
        super()._attempt_connect()

    def _connect_failed(self, message):
        self._connecting_route = None
        super()._connect_failed(message)
        self._launcher_changed()

    def _connect_succeeded(self):
        if self._connecting_route:
            self._game_host, host, token, local = self._connecting_route
            self._connecting_route = None
            self.v_local_console.set(local)
            self.v_host.set(host)
            self.v_token.set(token)
            self._remember_changed()
        for child in list(self.winfo_children()):
            child.destroy()
        self.geometry('720x620')
        self.minsize(600, 500)
        self._update_server_status()
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
            if not _same_server(getattr(_active, 'game_host', getattr(_active, 'host', '')), host):
                _active.close_reason = ('Editor disconnected: Prefabulator is connected to ' + getattr(_active, 'game_host', getattr(_active, 'host', '')) +
                                        ', but the launcher selected ' + host + '. Open Prefabulator and click Change server / reconnect before joining.')
                log_fn(_active.close_reason)
                _active.close()
            elif _active.transport.client._connected and _active.process and _active.process.poll() is None:
                _active.ensure_connection(game)
                return
            else:
                _active.close()
        if not saved.get('protectedToken') or not _same_server(saved.get('gameHost', saved.get('host', '')), host):
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
            bridge.game_host = saved.get('gameHost', saved['host'])
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
