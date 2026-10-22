"""Saved/Recent servers panel."""
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import threading, time, json, urllib.request

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN,
    _btn, _field, _hint, _section_label, _mk_tree, _mk_scrollbar,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon

from client.core.config import load_cfg, save_cfg

class ServerListPanel(tk.Toplevel):
    def __init__(self, parent, on_select):
        super().__init__(parent)
        _start_hidden(self)
        self.title("Saved & Recent Servers")
        self.configure(bg=BG)
        self.geometry("520x460")
        self.resizable(False, False)
        _set_window_icon(self)
        self._on_select = on_select
        self._build()
        _finish_dark_window(self)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text="⚑  Your Servers", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        nb = ttk.Notebook(self)
        style = ttk.Style()
        style.configure("TavNB.TNotebook", background=BG, borderwidth=0)
        style.configure("TavNB.TNotebook.Tab", background=SURF2, foreground=PARCH,
                        padding=(12,5), font=("Georgia",9))
        style.map("TavNB.TNotebook.Tab",
                  background=[("selected",AMBERDIM)],
                  foreground=[("selected","#ffd080")])
        nb.configure(style="TavNB.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=10)

        fav_tab    = tk.Frame(nb, bg=BG)
        recent_tab = tk.Frame(nb, bg=BG)
        nb.add(fav_tab,    text="  Favourites  ")
        nb.add(recent_tab, text="  Recent  ")

        self._build_fav_tab(fav_tab)
        self._build_recent_tab(recent_tab)

    def _build_fav_tab(self, parent):
        lf = tk.Frame(parent, bg=BG)
        lf.pack(fill="both", expand=True, padx=8, pady=(8,4))
        self.fav_tree = _mk_tree(lf, ("label","ip"), [240,200], height=9)
        cfg = load_cfg()
        for s in cfg.get("saved_servers", []):
            self.fav_tree.insert("","end", values=(s.get("name",s.get("ip","")), s.get("ip","")))

        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,8))

        def connect():
            sel = self.fav_tree.selection()
            if not sel: return
            vals = self.fav_tree.item(sel[0],"values")
            ip = vals[1]
            entry = next((s for s in load_cfg().get("saved_servers",[])
                          if s.get("ip") == ip), {})
            self._on_select(ip, vals[0], entry.get("port","1757")); self.destroy()

        def remove():
            sel = self.fav_tree.selection()
            if not sel: return
            vals = self.fav_tree.item(sel[0],"values")
            cfg = load_cfg()
            cfg["saved_servers"] = [s for s in cfg.get("saved_servers",[])
                                    if s.get("ip") != vals[1]]
            save_cfg(cfg); self.fav_tree.delete(sel[0])

        def add_manual():
            ip = simpledialog.askstring("Add Server",
                "Server IP:", parent=self)
            if not ip: return
            ip = ip.strip()
            label = simpledialog.askstring("Add Server",
                "Label for this server:", parent=self) or ip
            port = simpledialog.askstring("Add Server",
                "Port (leave blank for 1757):", parent=self) or "1757"
            cfg = load_cfg()
            saved = cfg.get("saved_servers", [])
            saved.append({"name": label, "ip": ip, "port": port})
            cfg["saved_servers"] = saved
            save_cfg(cfg)
            self.fav_tree.insert("","end", values=(label, ip))

        _btn(br, "Connect",   connect,    "primary", font=("Georgia",10,"bold"),
             pady=6, padx=14).pack(side="left")
        _btn(br, "+ Add IP",  add_manual, style="normal",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)
        _btn(br, "✕ Remove",  remove,     "danger",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left")

    def _build_recent_tab(self, parent):
        lf = tk.Frame(parent, bg=BG)
        lf.pack(fill="both", expand=True, padx=8, pady=(8,4))
        self.rec_tree = _mk_tree(lf, ("name","ip"), [240,200], height=9)
        cfg = load_cfg()
        for s in cfg.get("recent_servers", []):
            self.rec_tree.insert("","end", values=(s.get("name",s.get("ip","")), s.get("ip","")))

        br = tk.Frame(parent, bg=BG)
        br.pack(fill="x", padx=8, pady=(0,8))

        def connect():
            sel = self.rec_tree.selection()
            if not sel: return
            vals = self.rec_tree.item(sel[0],"values")
            ip = vals[1]
            entry = next((s for s in load_cfg().get("recent_servers",[])
                          if s.get("ip") == ip), {})
            self._on_select(ip, vals[0], entry.get("port","1757")); self.destroy()

        def save_fav():
            sel = self.rec_tree.selection()
            if not sel: return
            vals = self.rec_tree.item(sel[0],"values")
            ip, name = vals[1], vals[0]
            # If name is just the IP, ask for a proper label
            if name == ip or not name:
                name = simpledialog.askstring("Save Favourite",
                    f"Label for {ip}:", parent=self) or ip
            port = next((s.get("port","1757") for s in load_cfg().get("recent_servers",[])
                         if s.get("ip") == ip), "1757")
            cfg = load_cfg()
            saved = cfg.get("saved_servers", [])
            if not any(s["ip"] == ip for s in saved):
                saved.append({"name": name, "ip": ip, "port": port})
                cfg["saved_servers"] = saved
                save_cfg(cfg)
                messagebox.showinfo("Saved", f"'{name}' added to favourites.", parent=self)

        _btn(br, "Connect",        connect,  "primary",
             font=("Georgia",10,"bold"), pady=6, padx=14).pack(side="left")
        _btn(br, "★ Save as Fav",  save_fav, style="normal",
             font=("Segoe UI",9), pady=6, padx=10).pack(side="left", padx=6)

