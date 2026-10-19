"""Owner-only personal admin access management over the authenticated session."""
import base64
import json
import threading
import tkinter as tk
from tkinter import messagebox
from tavern_shared.theme import BG, PARCH, MUTED, _btn

TABS = [('select', 'Select'), ('arrange', 'Arrange'), ('build', 'Build'), ('world', 'World'),
        ('admin', 'Admin'), ('boards', 'Info boards'), ('objectLoader', 'Object Loader'),
        ('teleporter', 'Teleporter'), ('trading', 'Trading'), ('settings', 'Server Settings')]


def request(transport, action, **fields):
    payload = base64.b64encode(json.dumps(dict(fields, action=action)).encode()).decode()
    reply = transport.capture('edit access ' + payload)
    data = reply.get('data', {})
    if data.get('Exception'):
        raise RuntimeError(str(data['Exception']))
    result = data.get('Result') or data.get('ResultString')
    try:
        result = json.loads(result) if isinstance(result, str) else result
    except (ValueError, TypeError):
        result = None
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise RuntimeError('Access management needs the updated server mod. Ask the owner to update it and restart.')
    return result


class AccessWindow(tk.Toplevel):
    def __init__(self, parent, transport):
        super().__init__(parent)
        self.title('Manage Admin Access - owner only')
        self.configure(bg=BG)
        self.geometry('700x670')
        self.transport = transport
        self.records = []
        self.selected_id = None
        self.busy = False
        self.status = tk.StringVar(value='Checking owner access...')
        self.name = tk.StringVar()
        tk.Label(self, text='Give each admin a personal token and choose their tabs.', bg=BG, fg=PARCH).pack(pady=8)
        self.listbox = tk.Listbox(self, height=7, exportselection=False)
        self.listbox.pack(fill='x', padx=12)
        self.listbox.bind('<<ListboxSelect>>', self.select)
        tk.Label(self, text='Admin name', bg=BG, fg=PARCH).pack(anchor='w', padx=12)
        tk.Entry(self, textvariable=self.name).pack(fill='x', padx=12)
        self.tabs = {key: tk.BooleanVar(value=False) for key, _ in TABS}
        all_row = tk.Frame(self, bg=BG); all_row.pack(fill='x', padx=12, pady=6)
        _btn(all_row, 'All tabs', lambda: self.set_tabs(True)).pack(side='left')
        _btn(all_row, 'Clear tabs', lambda: self.set_tabs(False)).pack(side='left', padx=6)
        checks = tk.Frame(self, bg=BG); checks.pack(fill='x', padx=12)
        for index, (key, label) in enumerate(TABS):
            tk.Checkbutton(checks, text=label, variable=self.tabs[key], bg=BG, fg=PARCH,
                           selectcolor=BG).grid(row=index//2, column=index%2, sticky='w')
        tk.Label(self, text='All tabs grants gameplay tools. Only the owner can manage admin access.\nUndo/redo requires Select, Arrange and Build because their history is shared.',
                 bg=BG, fg=MUTED, justify='left', wraplength=650).pack(anchor='w', padx=12, pady=8)
        row = tk.Frame(self, bg=BG); row.pack(fill='x', padx=12)
        _btn(row, 'New admin', self.new).pack(side='left')
        _btn(row, 'Create token / Save permissions', self.save, 'primary').pack(side='left', padx=6)
        row = tk.Frame(self, bg=BG); row.pack(fill='x', padx=12, pady=8)
        _btn(row, 'Revoke selected admin', self.revoke).pack(side='left')
        _btn(row, 'Replace selected token', self.rotate).pack(side='left', padx=6)
        _btn(row, 'Refresh', self.refresh).pack(side='left')
        tk.Label(self, textvariable=self.status, bg=BG, fg=PARCH, wraplength=650, justify='left').pack(fill='x', padx=12, pady=10)
        self.run(lambda: request(transport, 'self'), self.authorized)

    def run(self, action, done):
        if self.busy:
            return
        self.busy = True
        self.status.set('Please wait...')
        def worker():
            try:
                result = action()
                self.after(0, lambda: finish(result, None))
            except Exception as error:
                self.after(0, lambda e=str(error): finish(None, e))
        def finish(result, error):
            self.busy = False
            if error:
                self.status.set(error)
            else:
                done(result)
        threading.Thread(target=worker, daemon=True).start()

    def authorized(self, result):
        if result.get('owner') is not True:
            messagebox.showerror('Owner only', 'Only the server owner can manage admin access.', parent=self)
            self.destroy()
            return
        self.refresh()

    def set_tabs(self, value):
        for var in self.tabs.values():
            var.set(value)

    def new(self):
        self.selected_id = None
        self.listbox.selection_clear(0, 'end')
        self.name.set('')
        self.set_tabs(False)
        self.status.set('Enter a name, choose tabs, then Create token. No tabs are enabled by default.')

    def select(self, event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        record = self.records[selection[0]]
        self.selected_id = record['id']
        self.name.set(record['name'])
        for key, var in self.tabs.items():
            var.set(key in record['tabs'])
        self.status.set('Revoked - replace the token to grant access again.' if record['revoked'] else 'Change tabs and Save permissions, or revoke this admin.')

    def refresh(self):
        def display(result):
            self.records = result['admins']
            self.listbox.delete(0, 'end')
            for record in self.records:
                self.listbox.insert('end', record['name'] + (' [REVOKED]' if record['revoked'] else ''))
            self.new()
            self.status.set('Choose an admin to edit, or click New admin.')
        self.run(lambda: request(self.transport, 'list'), display)

    def save(self):
        name = self.name.get().strip()
        if not name:
            self.status.set('Enter the admin name first.')
            return
        fields = dict(id=self.selected_id, name=name, tabs=[k for k, v in self.tabs.items() if v.get()])
        action = 'update' if self.selected_id else 'create'
        self.run(lambda: request(self.transport, action, **fields), self.changed)

    def revoke(self):
        identifier = self.selected_id
        if not identifier:
            self.status.set('Select an admin first.')
            return
        if messagebox.askyesno('Revoke admin', 'Disconnect this admin and revoke their token?', parent=self):
            self.run(lambda: request(self.transport, 'revoke', id=identifier), self.changed)

    def rotate(self):
        identifier = self.selected_id
        if not identifier:
            self.status.set('Select an admin first.')
            return
        if messagebox.askyesno('Replace token', 'Invalidate the old token, disconnect its sessions and create a new token for this admin?', parent=self):
            self.run(lambda: request(self.transport, 'rotate', id=identifier), self.changed)

    def changed(self, result):
        token = result.get('token')
        if token:
            popup = tk.Toplevel(self); popup.title('Personal admin token - shown once')
            tk.Label(popup, text='Send this token privately to this admin. It cannot be shown again.\nThey enter it in Prefabulator in place of the owner console token.').pack(padx=12, pady=12)
            entry = tk.Entry(popup, width=95); entry.insert(0, token); entry.configure(state='readonly'); entry.pack(padx=12)
            def copy():
                popup.clipboard_clear(); popup.clipboard_append(token)
            tk.Button(popup, text='Copy token', command=copy).pack(pady=12)
        self.refresh()
