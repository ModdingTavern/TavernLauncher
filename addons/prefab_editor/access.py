"""Owner-only personal admin access management over the authenticated session."""
import base64
import json
import threading
import tkinter as tk
from tkinter import messagebox
from .invite import make_code
from tavern_shared.theme import BG, SURF, SURF2, AMBER, PARCH, MUTED, _btn

TAB_GROUPS = (
    ('Editing and world', (('select', 'Select'), ('arrange', 'Arrange'), ('build', 'Build'),
                           ('world', 'World'), ('objectLoader', 'Object Loader'),
                           ('teleporter', 'Teleporter'), ('trading', 'Trading'))),
    ('Server tools', (('admin', 'Admin'), ('boards', 'Info boards'), ('settings', 'Server Settings'))),
)
TABS = [tab for _, group in TAB_GROUPS for tab in group] + [('console', 'Console')]


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
    def __init__(self, parent, transport, host=None):
        super().__init__(parent)
        self.title('Moderator access')
        self.configure(bg=BG)
        self.geometry('820x590')
        self.transport = transport
        self.host = host
        self.records = []
        self.selected_id = None
        self.busy = False
        self.owner = False
        self._poll_id = None
        self.status = tk.StringVar(self)
        self.name = tk.StringVar(self)
        self.mode = tk.StringVar(self)
        self.protocol('WM_DELETE_WINDOW', self.close)

        tk.Label(self, text='Moderator access', bg=BG, fg=PARCH,
                 font=('Segoe UI', 15, 'bold')).pack(anchor='w', padx=16, pady=(12, 2))
        tk.Label(self, text='Choose the tabs each moderator can use and give them their own private access code.',
                 bg=BG, fg=MUTED, justify='left', wraplength=740).pack(anchor='w', padx=16, pady=(0, 12))
        content = tk.Frame(self, bg=BG)
        content.pack(fill='both', expand=True, padx=16)
        profiles = tk.Frame(content, bg=BG)
        profiles.pack(side='left', fill='y', padx=(0, 18))
        tk.Label(profiles, text='Moderators', bg=BG, fg=PARCH,
                 font=('Segoe UI', 10, 'bold')).pack(anchor='w', pady=(0, 5))
        listing = tk.Frame(profiles, bg=SURF)
        listing.pack(fill='both', expand=True)
        scroll = tk.Scrollbar(listing, orient='vertical')
        scroll.pack(side='right', fill='y')
        self.listbox = tk.Listbox(listing, width=23, height=10, exportselection=False, bg=SURF, fg=PARCH,
                                  selectbackground=SURF2, selectforeground=AMBER,
                                  highlightthickness=0, borderwidth=0, yscrollcommand=scroll.set)
        self.listbox.pack(fill='both', expand=True)
        scroll.configure(command=self.listbox.yview)
        self.listbox.bind('<<ListboxSelect>>', self.select)
        self.new_button = _btn(profiles, 'New moderator', self.new, pady=4)
        self.new_button.pack(fill='x', pady=(8, 4))
        self.refresh_button = _btn(profiles, 'Refresh list', self.refresh, pady=4)
        self.refresh_button.pack(fill='x')

        form = tk.Frame(content, bg=BG)
        form.pack(side='left', fill='both', expand=True)
        tk.Label(form, textvariable=self.mode, bg=BG, fg=AMBER,
                 font=('Segoe UI', 11, 'bold')).pack(anchor='w')
        tk.Label(form, text='Moderator name', bg=BG, fg=PARCH).pack(anchor='w', pady=(6, 2))
        self.name_entry = tk.Entry(form, textvariable=self.name, bg=SURF, fg=PARCH, insertbackground=PARCH,
                                   disabledbackground=SURF, disabledforeground=MUTED, relief='flat')
        self.name_entry.pack(fill='x', ipady=5)
        self.tabs = {key: tk.BooleanVar(self, value=False) for key, _ in TABS}
        self.form_controls = [self.name_entry]
        checks = tk.Frame(form, bg=BG)
        checks.pack(fill='x', pady=(8, 0))
        for label, group in TAB_GROUPS:
            section = tk.LabelFrame(checks, text=label, bg=BG, fg=MUTED, padx=6, pady=3)
            section.pack(side='left', fill='both', expand=True, padx=(0, 6))
            for key, tab_label in group:
                self.add_checkbox(section, key, tab_label)
        all_row = tk.Frame(form, bg=BG)
        all_row.pack(fill='x', pady=(6, 2))
        all_tools = _btn(all_row, 'Select all tools', lambda: self.set_tabs(True), padx=6, pady=3)
        all_tools.pack(side='left')
        clear_tools = _btn(all_row, 'Clear permissions', lambda: self.set_tabs(False), padx=6, pady=3)
        clear_tools.pack(side='left', padx=6)
        self.form_controls.extend((all_tools, clear_tools))
        tk.Label(form, text='Undo and redo require Select, Arrange and Build.', bg=BG, fg=MUTED,
                 justify='left').pack(anchor='w')
        self.add_checkbox(form, 'console', 'Console commands')
        tk.Label(form, text='Enable Console separately to allow any server command, regardless of the other tabs. '
                            'Only the owner can manage moderator access.', bg=BG, fg=MUTED,
                 justify='left', wraplength=470).pack(anchor='w')
        row = tk.Frame(form, bg=BG)
        row.pack(fill='x', pady=(10, 4))
        self.save_button = _btn(row, 'Create access code', self.save, 'primary', padx=8, pady=5)
        self.save_button.pack(side='left')
        self.rotate_button = _btn(row, 'Replace code', self.rotate, padx=8, pady=5)
        self.rotate_button.pack(side='left', padx=6)
        self.revoke_button = _btn(row, 'Revoke access', self.revoke, 'danger', padx=8, pady=5)
        self.revoke_button.pack(side='left')
        tk.Label(self, textvariable=self.status, bg=BG, fg=PARCH, wraplength=740, justify='left', anchor='w',
                 height=2).pack(fill='x', padx=16, pady=(6, 8))
        self.update_idletasks()
        self.minsize(max(770, self.winfo_reqwidth()), self.winfo_reqheight())
        self.refresh()

    def add_checkbox(self, parent, key, label):
        checkbox = tk.Checkbutton(parent, text=label, variable=self.tabs[key], bg=BG, fg=PARCH,
                                  activebackground=BG, activeforeground=PARCH, selectcolor=SURF)
        checkbox.pack(anchor='w')
        self.form_controls.append(checkbox)

    def selected(self):
        return next((record for record in self.records if record['id'] == self.selected_id), None)

    def sync_controls(self):
        record = self.selected()
        revoked = record is not None and record['revoked']
        ready = self.owner and not self.busy
        editable = ready and not revoked
        self.mode.set('Revoked moderator' if revoked else 'Edit moderator' if record else 'New moderator')
        self.save_button.configure(text='Save permissions' if record else 'Create access code',
                                   state='normal' if editable else 'disabled')
        for widget in self.form_controls:
            widget.configure(state='normal' if editable else 'disabled')
        self.listbox.configure(state='normal' if ready else 'disabled')
        self.new_button.configure(state='normal' if ready else 'disabled')
        self.refresh_button.configure(state='disabled' if self.busy else 'normal')
        self.rotate_button.configure(state='normal' if ready and record else 'disabled')
        self.revoke_button.configure(state='normal' if ready and record and not revoked else 'disabled')

    def run(self, action, done, waiting):
        if self.busy:
            return
        self.busy = True
        self.status.set(waiting)
        self.sync_controls()
        completed = []

        def worker():
            try:
                completed.append((action(), None))
            except Exception as error:
                completed.append((None, str(error)))

        def poll():
            self._poll_id = None
            if not completed:
                self._poll_id = self.after(50, poll)
                return
            result, error = completed.pop()
            self.busy = False
            self.sync_controls()
            if error is not None:
                self.status.set(error)
            else:
                done(result)

        # Poll on the Tk thread so a late server response never calls into a closed window.
        threading.Thread(target=worker, daemon=True).start()
        self._poll_id = self.after(50, poll)

    def close(self):
        if self.busy:
            self.status.set('Wait for the server response before closing this window.')
            return
        self.destroy()

    def destroy(self):
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        super().destroy()

    def authorized(self, result):
        if result.get('owner') is not True:
            messagebox.showerror('Owner only', 'Only the server owner can manage admin access.', parent=self)
            self.destroy()
            return
        self.owner = True
        self.refresh()

    def set_tabs(self, value):
        for key, var in self.tabs.items():
            if key != 'console' or not value:
                var.set(value)

    def new(self):
        self.listbox.selection_clear(0, 'end')
        self.load_record(None)
        self.status.set('Enter a name, choose permissions and create an access code.')
        self.name_entry.focus_set()

    def load_record(self, record):
        self.selected_id = record['id'] if record else None
        self.name.set(record['name'] if record else '')
        permissions = record['tabs'] if record else ()
        for key, var in self.tabs.items():
            var.set(key in permissions)
        self.sync_controls()

    def select(self, event=None):
        selection = self.listbox.curselection()
        if self.busy or not selection or selection[0] >= len(self.records):
            return
        record = self.records[selection[0]]
        self.load_record(record)
        self.status.set('Replace the code to restore access.' if record['revoked'] else
                        'Change this moderator\'s tools and click Save permissions.')

    def display(self, records, identifier):
        self.records = records
        self.listbox.delete(0, 'end')
        selected = None
        for index, record in enumerate(records):
            self.listbox.insert('end', record['name'] + (' [Revoked]' if record['revoked'] else ''))
            if record['id'] == identifier:
                self.listbox.selection_set(index)
                self.listbox.see(index)
                selected = record
        self.load_record(selected)

    def refresh(self):
        if not self.owner:
            self.run(lambda: request(self.transport, 'self'), self.authorized, 'Checking owner access...')
            return
        identifier = self.selected_id

        def loaded(result):
            records = result.get('admins')
            if not isinstance(records, list):
                self.status.set('The server did not return a moderator list.')
                return
            self.display(records, identifier)
            self.status.set('Choose a moderator to edit, or create a new profile.' if records else
                            'Enter a name and choose permissions to create your first access code.')

        self.run(lambda: request(self.transport, 'list'), loaded, 'Loading moderator profiles...')

    def save(self):
        record = self.selected()
        if not self.owner or self.busy or (record and record['revoked']):
            return
        name = self.name.get().strip()
        if not name:
            self.status.set('Enter the moderator name first.')
            self.name_entry.focus_set()
            return
        fields = dict(id=self.selected_id, name=name, tabs=[k for k, v in self.tabs.items() if v.get()])
        action = 'update' if self.selected_id else 'create'
        self.run(lambda: request(self.transport, action, **fields),
                 lambda result: self.changed(result, action, fields),
                 'Saving permissions...' if record else 'Creating an access code...')

    def revoke(self):
        record = self.selected()
        if not self.owner or self.busy or not record or record['revoked']:
            return
        if messagebox.askyesno('Revoke access', 'Revoke access for {} and disconnect their sessions?'.format(record['name']), parent=self):
            self.run(lambda: request(self.transport, 'revoke', id=record['id']),
                     lambda result: self.changed(result, 'revoke', record), 'Revoking access...')

    def rotate(self):
        record = self.selected()
        if not self.owner or self.busy or not record:
            return
        if messagebox.askyesno('Replace code', 'Replace the code for {}? The old code will stop working and its sessions will disconnect.'.format(record['name']), parent=self):
            self.run(lambda: request(self.transport, 'rotate', id=record['id']),
                     lambda result: self.changed(result, 'rotate', record), 'Replacing the access code...')

    def changed(self, result, action, record):
        identifier = result.get('id') or record.get('id')
        if identifier:
            saved = dict(record, id=identifier, revoked=action == 'revoke')
            records = [saved if item['id'] == identifier else item for item in self.records]
            if not any(item['id'] == identifier for item in self.records):
                records.append(saved)
            self.display(records, identifier)
        messages = {'create': 'Access code created.', 'update': 'Permissions saved.',
                    'rotate': 'Access code replaced.', 'revoke': 'Access revoked.'}
        self.status.set(messages[action] + ' ' + record['name'])
        token = result.get('token')
        if token:
            self.show_code(record['name'], token)

    def show_code(self, name, token):
        credential = token
        instructions = 'Enter the server address and paste this token into Prefabulator, then click Connect.'
        if self.host:
            try:
                credential = make_code(self.host, token)
                instructions = 'Paste the code into Prefabulator and click Connect. It includes the server address.'
            except ValueError:
                pass  # The newly issued personal token still works with a manually entered address.
        popup = tk.Toplevel(self)
        popup.title('Private access code')
        popup.configure(bg=BG)
        popup.transient(self)
        popup.resizable(False, False)
        tk.Label(popup, text='Access for ' + name, bg=BG, fg=PARCH,
                 font=('Segoe UI', 11, 'bold'), wraplength=360).pack(anchor='w', padx=14, pady=(12, 4))
        tk.Label(popup, text='Copy this code now and send it privately to this moderator. '
                             'You can replace it later if they lose it.\n\n' + instructions,
                 bg=BG, fg=PARCH, justify='left', wraplength=360).pack(anchor='w', padx=14, pady=4)
        feedback = tk.StringVar(popup)

        def copy():
            self.clipboard_clear()
            self.clipboard_append(credential)
            feedback.set('Copied. Share it privately.')

        buttons = tk.Frame(popup, bg=BG)
        buttons.pack(fill='x', padx=14, pady=(8, 4))
        copy_button = _btn(buttons, 'Copy access code', copy, 'primary', padx=8, pady=5)
        copy_button.pack(side='left')
        _btn(buttons, 'Done', popup.destroy, padx=8, pady=5).pack(side='left', padx=6)
        tk.Label(popup, textvariable=feedback, bg=BG, fg=AMBER, anchor='w').pack(fill='x', padx=14, pady=(0, 8))
        popup.grab_set()
        copy_button.focus_set()
