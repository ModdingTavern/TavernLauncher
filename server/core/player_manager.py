"""Player database / blacklist / whitelist management window."""
import os
import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN, MONO,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar, _fix_combobox_popdown_colors,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.flashing import start_flashing_tab

from server.core.data_store import (
    _load_users, _save_users, _users_lock, _load_bl, _save_bl, _load_wl, _save_wl,
    _is_blacklisted, _is_whitelisted, kick_player, PLAYERS_SAVE,
    _load_whitelist_requests, _approve_whitelist_request, _deny_whitelist_request,
    _load_whitelist_comments, _set_whitelist_comment,
)

class PlayerManagerWindow(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Player Manager")
        self.configure(bg=BG)
        self.geometry("700x660")
        self.resizable(False, False)
        _set_window_icon(self)
        # Guarded rather than called unconditionally -- ttk.Style() is a
        # single global object shared across the whole app, and
        # unconditionally re-invoking theme_use() every time any window
        # opens (even redundantly re-setting the SAME theme) can reset
        # custom style configurations already applied elsewhere (e.g. a
        # combobox styled by an already-open window), which is almost
        # certainly why collapsed comboboxes intermittently reverted to
        # plain white once more than one window was involved.
        if ttk.Style().theme_use() != "clam":
            ttk.Style().theme_use("clam")
        self._build()
        self._refresh_players()
        self._refresh_bllist()
        self._refresh_wllist()
        _finish_dark_window(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚑  Player Manager", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        nb = ttk.Notebook(self)
        style = ttk.Style()
        style.configure("PM.TNotebook", background=BG, borderwidth=0)
        style.configure("PM.TNotebook.Tab", background=SURF2, foreground=PARCH,
                        padding=(12,5), font=("Georgia",9))
        style.map("PM.TNotebook.Tab",
                  background=[("selected",AMBERDIM)],
                  foreground=[("selected","#ffd080")])
        nb.configure(style="PM.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        p_tab  = tk.Frame(nb, bg=BG)
        bl_tab = tk.Frame(nb, bg=BG)
        wl_tab = tk.Frame(nb, bg=BG)
        apps_tab = tk.Frame(nb, bg=BG)
        nb.add(p_tab,  text="  Players  ")
        nb.add(bl_tab, text="  Blacklist  ")
        nb.add(wl_tab, text="  Whitelist  ")
        nb.add(apps_tab, text="  Whitelist Applications  ")
        self._apps_tab_index = nb.index(apps_tab)
        self._nb = nb
        self._build_players(p_tab)
        self._build_list_tab(bl_tab, "bl", ["username","ip"],
                             "Blocked players are rejected at login.")
        self._build_whitelist_tab(wl_tab)
        self._build_applications_tab(apps_tab)
        start_flashing_tab(nb, self._apps_tab_index,
                            lambda: len(_load_whitelist_requests()) > 0,
                            "  Whitelist Applications  ", "  🔴 Whitelist Applications  ")

    # ── Players tab ────────────────────────────────────────────────────────────

    def _build_players(self, parent):
        self.p_tree = _mk_tree(parent, ("username","user_id"), [240,120], height=10)
        self.p_detail = tk.StringVar(value="Select a player.")
        df = tk.Frame(parent, bg=SURF, highlightbackground=BORDER,
                      highlightthickness=1, height=60)
        df.pack(fill="x", padx=8, pady=(0,4)); df.pack_propagate(False)
        tk.Label(df, textvariable=self.p_detail, bg=SURF, fg=PARCH,
                 font=MONO, justify="left", anchor="nw", wraplength=640
                 ).pack(fill="both", expand=True, padx=8, pady=8)
        self.p_tree.bind("<<TreeviewSelect>>", self._on_player_select)
        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,6))
        _btn(br, "⟳ Refresh",       self._refresh_players,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "✏ Change User ID", self._change_uid,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "♻ Reset User Token", self._reset_token,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "♻ Reset All Tokens", self._reset_all_tokens, "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "🎭 Edit Roles",     self._edit_roles,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "👢 Kick",          self._kick_player, "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "🚫 Kick & Ban",    self._kick_ban,    "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "📁 Save Folder",   self._open_saves,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="right")

    def _refresh_players(self):
        for r in self.p_tree.get_children(): self.p_tree.delete(r)
        for uname, entry in sorted(_load_users().items()):
            self.p_tree.insert("","end", iid=uname,
                               values=(uname, entry.get("user_id","?")))
        self.p_detail.set("Select a player.")

    def _on_player_select(self, _=None):
        sel = self.p_tree.selection()
        if not sel: return
        entry = _load_users().get(sel[0],{})
        roles = entry.get("roles", [])
        roles_text = ", ".join(roles) if roles else "—"
        self.p_detail.set(f"Username: {sel[0]}    User ID: {entry.get('user_id','?')}\n"
                          f"Roles: {roles_text}")

    def _selected_username(self):
        sel = self.p_tree.selection()
        if not sel:
            messagebox.showinfo("No selection","Select a player first.", parent=self)
            return None
        return sel[0]

    def _kick_player(self):
        uname = self._selected_username()
        if not uname: return
        if not messagebox.askyesno("Kick Player",
                f"Kick '{uname}' from the server?\nThey can rejoin after.", parent=self): return
        ok, msg = kick_player(uname, ban=False)
        messagebox.showinfo("Done" if ok else "Error", msg or "Sent kick command.", parent=self)

    def _kick_ban(self):
        uname = self._selected_username()
        if not uname: return
        if not messagebox.askyesno("Kick & Ban",
                f"Kick and ban '{uname}'?\nThis will also add them to the blacklist.", parent=self): return
        # Add to blacklist
        bl = _load_bl()
        if uname.lower() not in [u.lower() for u in bl["usernames"]]:
            bl["usernames"].append(uname)
            _save_bl(bl)
        # Kick live session
        ok, msg = kick_player(uname, ban=True)
        detail = msg or "Sent ban command."
        messagebox.showinfo("Banned", f"'{uname}' added to blacklist.\n{detail}", parent=self)

    def _change_uid(self):
        uname = self._selected_username()
        if not uname: return
        current = _load_users().get(uname,{}).get("user_id","")
        prompt = tk.Toplevel(self)
        _start_hidden(prompt)
        prompt.title("Change User ID"); prompt.configure(bg=BG)
        prompt.resizable(False,False); prompt.geometry("380x230")
        _set_window_icon(prompt)
        tk.Label(prompt, text=f"New User ID for '{uname}'",
                 bg=BG, fg=PARCH, font=("Georgia",11,"bold")).pack(pady=(16,4))
        tk.Label(prompt, text="Maps this username to a different save file.",
                 bg=BG, fg=MUTED, font=("Segoe UI",9)).pack()
        var = tk.StringVar(value=str(current))
        ef = tk.Frame(prompt, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        ef.pack(padx=30, pady=10, fill="x")
        tk.Entry(ef, textvariable=var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",11),
                 bd=6, justify="center").pack(fill="x")
        def confirm():
            try: new_id = int(var.get().strip())
            except ValueError: messagebox.showerror("Invalid","Must be a number.", parent=self); return
            with _users_lock:
                u = _load_users()
                if uname in u: u[uname]["user_id"] = new_id; _save_users(u)
            prompt.destroy(); self._refresh_players()
            messagebox.showinfo("Done", f"'{uname}' → ID {new_id}.", parent=self)
        _btn(prompt, "Save", confirm, "primary",
             font=("Georgia",10,"bold"), pady=8).pack(fill="x", padx=30, pady=(0,14))
        _finish_dark_window(prompt)

    def _reset_token(self):
        uname = self._selected_username()
        if not uname: return
        if not messagebox.askyesno("Reset User Token",
                f"Reset the token for '{uname}'?\n\n"
                "Their token will be cleared. The next time anyone connects using "
                "this username, whatever token their launcher sends will be "
                "automatically accepted and saved as the new token — this is how "
                "a player recovers from a lost token file.", parent=self):
            return
        with _users_lock:
            u = _load_users()
            if uname in u:
                u[uname]["token"] = ""
                _save_users(u)
        self._refresh_players()
        messagebox.showinfo("Token Reset",
            f"'{uname}'s token has been cleared.\n"
            "The next login for this username will be accepted automatically.", parent=self)

    def _reset_all_tokens(self):
        with _users_lock:
            u = _load_users()
        count = len(u)
        if count == 0:
            messagebox.showinfo("No players", "There are no known users to reset.", parent=self)
            return
        if not messagebox.askyesno("Reset All Tokens",
                f"Reset the token for ALL {count} known user(s)?\n\n"
                "Every username's token will be cleared. The next time anyone "
                "connects with any of these usernames, whatever token their "
                "launcher sends will be automatically accepted and saved as the "
                "new token — useful right after resetting the server, so "
                "everyone can reconnect cleanly.\n\n"
                "This cannot be undone.", parent=self):
            return
        with _users_lock:
            u = _load_users()
            for entry in u.values():
                entry["token"] = ""
            _save_users(u)
        self._refresh_players()
        messagebox.showinfo("All Tokens Reset",
            f"Cleared tokens for {count} user(s).\n"
            "The next login for each username will be accepted automatically.", parent=self)

    def _edit_roles(self):
        uname = self._selected_username()
        if not uname: return
        users = _load_users()
        entry = users.get(uname, {})
        roles = list(entry.get("roles", []))

        win = tk.Toplevel(self)
        _start_hidden(win)
        win.title(f"Roles — {uname}")
        win.configure(bg=BG)
        win.resizable(False, False)
        _set_window_icon(win)

        tk.Label(win, text=f"Roles for '{uname}'", bg=BG, fg=AMBER,
                 font=("Georgia",11,"bold")).pack(anchor="w", padx=16, pady=(14,2))
        tk.Label(win, text="These are plain text tags TavernLib can read and act on — "
                            "e.g. assigning in-game admin/moderator status based on what's "
                            "listed here. This launcher just stores the list.",
                 bg=BG, fg=MUTED, font=("Segoe UI",8), wraplength=300,
                 justify="left").pack(anchor="w", padx=16, pady=(0,8))

        list_frame = tk.Frame(win, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        list_frame.pack(fill="both", expand=True, padx=16, pady=(0,8))
        lb = tk.Listbox(list_frame, bg=SURF, fg=PARCH, selectbackground=AMBERDIM,
                        selectforeground="#ffd080", relief="flat", height=6,
                        font=("Consolas",10), highlightthickness=0, bd=0)
        lb.pack(fill="both", expand=True, padx=2, pady=2)
        for r in roles:
            lb.insert("end", r)

        add_row = tk.Frame(win, bg=BG)
        add_row.pack(fill="x", padx=16, pady=(0,8))
        v_new_role = tk.StringVar()
        entry_widget = tk.Entry(add_row, textvariable=v_new_role, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=("Consolas",10), bd=6)
        entry_widget.pack(side="left", fill="x", expand=True)

        def _add_role(event=None):
            val = v_new_role.get().strip()
            if not val: return
            if val in lb.get(0, "end"):
                messagebox.showinfo("Already added", f"'{val}' is already in the list.", parent=win)
                return
            lb.insert("end", val)
            v_new_role.set("")

        entry_widget.bind("<Return>", _add_role)
        _btn(add_row, "+ Add", _add_role, font=("Segoe UI",9),
             pady=6, padx=10).pack(side="left", padx=(6,0))

        def _remove_role():
            sel = lb.curselection()
            if not sel: return
            lb.delete(sel[0])

        _btn(win, "− Remove Selected", _remove_role, "danger",
             font=("Segoe UI",9), pady=6, padx=10).pack(anchor="w", padx=16, pady=(0,4))

        def _save_roles():
            new_roles = list(lb.get(0, "end"))
            with _users_lock:
                u = _load_users()
                if uname in u:
                    u[uname]["roles"] = new_roles
                    _save_users(u)
            win.destroy()
            self._refresh_players()
            if self.p_tree.exists(uname):
                self.p_tree.selection_set(uname)
            self._on_player_select()

        tk.Frame(win, bg=BORDER, height=1).pack(fill="x", padx=16, pady=(8,6))
        _btn(win, "💾 Save Roles", _save_roles, "primary",
             font=("Georgia",10,"bold"), pady=10).pack(fill="x", padx=16, pady=(0,14))

        win.update_idletasks()
        win.geometry(f"340x{win.winfo_reqheight()}")
        _finish_dark_window(win)
        win.transient(self)
        win.grab_set()

    def _open_saves(self):
        try: os.makedirs(PLAYERS_SAVE, exist_ok=True); os.startfile(PLAYERS_SAVE)
        except Exception as e: messagebox.showerror("Error", str(e), parent=self)

    # ── Generic list tab ───────────────────────────────────────────────────────

    def _build_whitelist_tab(self, parent):
        _section_label(parent, "ALLOWED — USERNAME / IP")
        tree = _mk_tree(parent, ("type","value","comment"), [90, 220, 200], height=10)
        self._wl_tree = tree
        _hint(parent, "When whitelist is enabled, only these entries may join. Comments are "
                      "your own notes only -- e.g. approving an application auto-fills the "
                      "applicant's username here, so a lone IP entry doesn't turn into a mystery later.")
        ar = tk.Frame(parent, bg=BG)
        ar.pack(fill="x", padx=8, pady=(0,4))
        type_var = tk.StringVar(value="username")
        style = ttk.Style()
        style.configure("PM.TCombobox", fieldbackground=SURF, background=SURF2,
                        foreground=PARCH, arrowcolor=AMBERDIM)
        cb = ttk.Combobox(ar, textvariable=type_var, values=["username","ip"],
                          state="readonly", width=12, style="PM.TCombobox")
        cb.pack(side="left", padx=(0,6))
        _fix_combobox_popdown_colors(cb, SURF, PARCH, AMBERDIM, "#ffd080")
        val_var = tk.StringVar()
        vf = tk.Frame(ar, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        vf.pack(side="left", fill="x", expand=True, padx=(0,6))
        tk.Entry(vf, textvariable=val_var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=MONO, bd=5).pack(fill="x")

        def add():
            kind = type_var.get(); value = val_var.get().strip()
            if not value: return
            wl = _load_wl()
            if kind=="username" and value.lower() not in [u.lower() for u in wl["usernames"]]:
                wl["usernames"].append(value)
            elif kind=="ip" and value not in wl["ips"]:
                wl["ips"].append(value)
            _save_wl(wl)
            val_var.set("")
            self._refresh_wllist()

        def remove():
            sel = tree.selection()
            if not sel: return
            kind, value, _comment = tree.item(sel[0],"values")
            wl = _load_wl()
            if kind=="username": wl["usernames"]=[u for u in wl["usernames"] if u.lower()!=str(value).lower()]
            elif kind=="ip": wl["ips"]=[i for i in wl["ips"] if i!=value]
            _save_wl(wl)
            _set_whitelist_comment(value, "")
            self._refresh_wllist()

        def edit_comment():
            sel = tree.selection()
            if not sel: return
            kind, value, comment = tree.item(sel[0],"values")
            new_comment = simpledialog.askstring("Comment", f"Comment for {value}:",
                                                  initialvalue=comment, parent=self)
            if new_comment is None: return
            _set_whitelist_comment(value, new_comment.strip())
            self._refresh_wllist()

        _btn(ar, "+ Add", add, font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,6))
        _btn(br, "✕ Remove", remove, "danger", font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "✎ Edit Comment", edit_comment, font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "⟳ Refresh", self._refresh_wllist,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")

    def _build_list_tab(self, parent, key, kinds, hint_text):
        _section_label(parent, ("BLOCKED" if key=="bl" else "ALLOWED") +
                       " — " + " / ".join(k.upper() for k in kinds))
        tree = _mk_tree(parent, ("type","value"), [110,320], height=10)
        setattr(self, f"_{key}_tree", tree)
        _hint(parent, hint_text)
        ar = tk.Frame(parent, bg=BG)
        ar.pack(fill="x", padx=8, pady=(0,4))
        type_var = tk.StringVar(value=kinds[0])
        style = ttk.Style()
        style.configure("PM.TCombobox", fieldbackground=SURF, background=SURF2,
                        foreground=PARCH, arrowcolor=AMBERDIM)
        cb = ttk.Combobox(ar, textvariable=type_var, values=kinds,
                          state="readonly", width=12, style="PM.TCombobox")
        cb.pack(side="left", padx=(0,6))
        _fix_combobox_popdown_colors(cb, SURF, PARCH, AMBERDIM, "#ffd080")
        val_var = tk.StringVar()
        vf = tk.Frame(ar, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        vf.pack(side="left", fill="x", expand=True, padx=(0,6))
        tk.Entry(vf, textvariable=val_var, bg=SURF, fg=PARCH,
                 insertbackground=AMBER, relief="flat", font=MONO, bd=5).pack(fill="x")
        def add():
            kind = type_var.get(); value = val_var.get().strip()
            if not value: return
            if key=="bl":
                bl = _load_bl()
                if kind=="username" and value.lower() not in [u.lower() for u in bl["usernames"]]:
                    bl["usernames"].append(value)
                elif kind=="ip" and value not in bl["ips"]:
                    bl["ips"].append(value)
                _save_bl(bl)
            else:
                wl = _load_wl()
                if kind=="username" and value.lower() not in [u.lower() for u in wl["usernames"]]:
                    wl["usernames"].append(value)
                elif kind=="ip" and value not in wl["ips"]:
                    wl["ips"].append(value)
                _save_wl(wl)
            val_var.set("")
            getattr(self, f"_refresh_{key}list")()
        def remove():
            sel = tree.selection()
            if not sel: return
            kind, value = tree.item(sel[0],"values")
            if key=="bl":
                bl = _load_bl()
                if kind=="username": bl["usernames"]=[u for u in bl["usernames"] if u.lower()!=str(value).lower()]
                elif kind=="ip": bl["ips"]=[i for i in bl["ips"] if i!=value]
                _save_bl(bl)
            else:
                wl = _load_wl()
                if kind=="username": wl["usernames"]=[u for u in wl["usernames"] if u.lower()!=str(value).lower()]
                elif kind=="ip": wl["ips"]=[i for i in wl["ips"] if i!=value]
                _save_wl(wl)
            getattr(self, f"_refresh_{key}list")()
        _btn(ar, "+ Add",    add,    font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,6))
        _btn(br, "✕ Remove", remove, "danger", font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "⟳ Refresh", getattr(self, f"_refresh_{key}list"),
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)

    def _build_applications_tab(self, parent):
        _section_label(parent, "PENDING WHITELIST APPLICATIONS")
        tree = _mk_tree(parent, ("username","ip","applied"), [180, 160, 200], height=12)
        self._apps_tree = tree
        _hint(parent, "Applied from in-game join attempts against your whitelisted server. "
                       "Approving adds both the username and IP to your Whitelist tab.")
        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,6))
        _btn(br, "✓ Approve", self._approve_selected_application, "primary",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        _btn(br, "✕ Deny", self._deny_selected_application, "danger",
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left", padx=6)
        _btn(br, "⟳ Refresh", self._refresh_applications,
             font=("Segoe UI",9), pady=5, padx=10).pack(side="left")
        self._refresh_applications()

    def _refresh_applications(self):
        for r in self._apps_tree.get_children():
            self._apps_tree.delete(r)
        for req in _load_whitelist_requests():
            applied_at = req.get("applied_at", "")
            try:
                dt = datetime.datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
                applied_display = dt.astimezone().strftime("%Y-%m-%d %H:%M")
            except Exception:
                applied_display = applied_at
            self._apps_tree.insert("", "end",
                values=(req.get("username",""), req.get("ip",""), applied_display))

    def _selected_application_index(self):
        sel = self._apps_tree.selection()
        if not sel:
            return None
        return self._apps_tree.index(sel[0])

    def _approve_selected_application(self):
        idx = self._selected_application_index()
        if idx is None:
            return
        _approve_whitelist_request(idx)
        self._refresh_applications()
        self._refresh_wllist()

    def _deny_selected_application(self):
        idx = self._selected_application_index()
        if idx is None:
            return
        _deny_whitelist_request(idx)
        self._refresh_applications()

    def _refresh_bllist(self):
        for r in self._bl_tree.get_children(): self._bl_tree.delete(r)
        bl = _load_bl()
        for u   in bl.get("usernames",[]): self._bl_tree.insert("","end",values=("username",u))
        for ip  in bl.get("ips",      []): self._bl_tree.insert("","end",values=("ip",ip))

    def _refresh_wllist(self):
        for r in self._wl_tree.get_children(): self._wl_tree.delete(r)
        wl = _load_wl()
        comments = _load_whitelist_comments()
        for u  in wl.get("usernames",[]): self._wl_tree.insert("","end",values=("username",u,comments.get(u,"")))
        for ip in wl.get("ips",      []): self._wl_tree.insert("","end",values=("ip",ip,comments.get(ip,"")))

    def _refresh_blacklist(self): self._refresh_bllist()
    def _refresh_whitelist(self): self._refresh_wllist()

