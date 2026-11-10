"""
The Addons window -- lets a non-technical user enable/disable whatever
addons are sitting in the addons/ folder next to this .exe, without
needing Python, PyInstaller, or the source repo at all. Shared between
both apps: each just passes in its own addon_loader module (client's or
server's) and a label for the window title, since the two loaders are
otherwise identical in shape but deliberately kept as separate files/
preference files (see either addon_loader.py's own comment on why).
"""
import tkinter as tk
from tkinter import ttk

from tavern_shared.theme import (
    BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED, GREEN, RED, CYAN,
    _btn, _section_label,
)
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window, _set_window_icon
from tavern_shared.addon_manifest import load_addon_manifest, is_dependency_installed
from tavern_shared.screen_fit import ScrollArea, fit_window

# How each startup result shows under an addon's name.
_STATE_COLOURS = {"loaded": GREEN, "failed": RED, "built_in": AMBER, "nothing": MUTED}


class AddonManagerWindow(tk.Toplevel):
    def __init__(self, parent, addon_loader, app_label, get_game_dir=None):
        super().__init__(parent)
        _start_hidden(self)
        self._addon_loader = addon_loader
        self._app_label = app_label
        self._get_game_dir = get_game_dir or (lambda: None)
        self.title(f"Addons ({app_label})")
        self.configure(bg=BG)
        self.resizable(True, True)
        _set_window_icon(self)
        self._vars = {}  # name -> BooleanVar
        self._build()
        _finish_dark_window(self)
        self.update_idletasks()
        # The list scrolls, so open tall enough for all of it when the
        # screen has room, and never past the screen when it doesn't.
        list_extra = self._list.body.winfo_reqheight() - self._list.shell.winfo_reqheight()
        fit_w = max(480, self.winfo_reqwidth())
        fit_h = max(420, self.winfo_reqheight() + max(0, list_extra) + 4)
        fit_window(self, fit_w, fit_h, fit_w, 420)

    def _build(self):
        h = tk.Frame(self, bg=SURF, height=44)
        h.pack(fill="x"); h.pack_propagate(False)
        tk.Label(h, text=f"🧩  Addons — {self._app_label}", bg=SURF, fg=AMBER,
                 font=("Georgia",12,"bold")).pack(side="left", padx=16, pady=8)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        tk.Label(self,
            text="Enable or disable optional TavernLauncher features. These are stored "
                 "in the /addons folder in the same directory as this launcher. "
                 "Be careful installing them from locations other than the  "
                 "official TavernLauncher repo!",
            bg=BG, fg=MUTED, font=("Segoe UI",9), wraplength=440, justify="left"
        ).pack(anchor="w", padx=20, pady=(10,6))

        _section_label(self, "AVAILABLE ADDONS")

        game_dir = self._get_game_dir()
        if game_dir is None:
            tk.Label(self,
                text="Set your game executable path above to check whether required "
                     "mods/plugins are installed -- shown as red below until then.",
                bg=BG, fg=MUTED, font=("Segoe UI",8), wraplength=440, justify="left"
            ).pack(anchor="w", padx=20, pady=(0,4))

        frame = tk.Frame(self, bg=SURF, highlightbackground=BORDER, highlightthickness=1)
        frame.pack(fill="both", expand=True, padx=16, pady=(0,8))
        self._list = ScrollArea(frame, SURF)
        self._list.shell.pack(fill="both", expand=True)
        body = self._list.body

        available = self._addon_loader.discover_addons()
        enabled = self._addon_loader.load_enabled_addon_names()
        addons_dir = self._addon_loader.addons_dir()
        results = getattr(self._addon_loader, "LOAD_RESULTS", {})

        if not available:
            tk.Label(body, text="No addons found in the addons/ folder next to this program.",
                     bg=SURF, fg=MUTED, font=("Segoe UI",9), wraplength=420,
                     justify="left").pack(anchor="w", padx=12, pady=16)
        else:
            for folder_name in available:
                info = load_addon_manifest(addons_dir, folder_name)
                row = tk.Frame(body, bg=SURF)
                row.pack(fill="x", padx=10, pady=6)
                var = tk.BooleanVar(value=folder_name in enabled)
                self._vars[folder_name] = var
                cb = tk.Checkbutton(row, variable=var, bg=SURF,
                                     activebackground=SURF, selectcolor=AMBERDIM,
                                     relief="flat", highlightthickness=0, bd=0)
                cb.pack(side="left", anchor="n", pady=(2,0))
                text_col = tk.Frame(row, bg=SURF)
                text_col.pack(side="left", fill="x", expand=True)
                tk.Label(text_col, text=f"{info['name']}  v{info['version']}", bg=SURF, fg=PARCH,
                         font=("Segoe UI",10,"bold"), anchor="w", justify="left"
                ).pack(anchor="w")
                tk.Label(text_col, text=f"by {info['author']}", bg=SURF, fg=MUTED,
                         font=("Segoe UI",8), anchor="w", justify="left"
                ).pack(anchor="w")

                requirements = (
                    [(r, "Mods") for r in info["required_mods"]] +
                    [(r, "Plugins") for r in info["required_plugins"]]
                )
                if requirements:
                    req_row = tk.Frame(text_col, bg=SURF)
                    req_row.pack(anchor="w", pady=(3,0))
                    for req, subfolder in requirements:
                        found = is_dependency_installed(game_dir, req["filename"], subfolder)
                        tk.Label(req_row, text=f"● {req['title']}",
                                 bg=SURF, fg=(GREEN if found else RED),
                                 font=("Segoe UI",8)).pack(side="left", padx=(0,8))

                self._add_result(text_col, folder_name, results.get(folder_name), folder_name in enabled)

        self._status = tk.StringVar(value="")
        tk.Label(self, textvariable=self._status, bg=BG, fg=CYAN,
                 font=("Segoe UI",9), wraplength=440, justify="left"
        ).pack(anchor="w", padx=20, pady=(0,4))

        _btn(self, "💾 Save (restart required to apply)", self._on_save, "primary",
             font=("Georgia",10,"bold"), pady=10).pack(fill="x", padx=16, pady=(0,16))

    def _add_result(self, parent, name, result, enabled):
        """What happened to this addon when the launcher started."""
        if result is None:
            if enabled:
                tk.Label(parent, text="Enabled since this start: restart to load it.", bg=SURF, fg=MUTED,
                         font=("Segoe UI",8), anchor="w").pack(anchor="w", pady=(3,0))
            return
        tk.Label(parent, text=result["message"], bg=SURF, fg=_STATE_COLOURS.get(result["state"], MUTED),
                 font=("Segoe UI",8), anchor="w", justify="left", wraplength=360).pack(anchor="w", pady=(3,0))
        if not result.get("detail"):
            return
        box = tk.Text(parent, bg=BG, fg=PARCH, font=("Consolas",8), relief="flat", height=8,
                      width=1, wrap="word", bd=4)
        box.insert("1.0", result["detail"])
        box.config(state="disabled")

        def toggle():
            if box.winfo_manager():
                box.pack_forget()
                show.config(text="Show error")
            else:
                box.pack(anchor="w", fill="x", pady=(3,0), after=show)
                show.config(text="Hide error")
        show = _btn(parent, "Show error", toggle, font=("Segoe UI",7), pady=1, padx=6)
        show.pack(anchor="w", pady=(3,0))

    def _on_save(self):
        chosen = {name for name, var in self._vars.items() if var.get()}
        self._addon_loader.save_enabled_addon_names(chosen)
        self._status.set(
            f"Saved. Restart {self._app_label} for this to take effect — "
            "addons are only loaded once, at startup."
        )
