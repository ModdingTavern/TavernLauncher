"""Floating help tab + docked help panel. Both are separate windows that
track the main window's position - neither touches the main window's own
size or widget tree at all."""
import os
import tkinter as tk
import webbrowser

import markdown
from tkinterweb import HtmlFrame

from tavern_shared.theme import BG, SURF, SURF2, BORDER, AMBER, AMBERDIM, PARCH, MUTED
from tavern_shared.window_chrome import _start_hidden, _finish_dark_window

HELP_CONTENT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "help_content")

# (slug, sidebar title, markdown filename) -- add a page by adding a row
# here and dropping the .md file in help_content/. Nothing else changes.
PAGES = [
    ("index", "Introduction", "index.md"),
    ("base-requirements", "Base Requirements", "base-requirements.md"),
    ("joining-full", "Join Server (Full Guide)", "joining-full.md"),
    ("joining-tldr", "Join Server (TLDR)", "joining-tldr.md"),
    ("local-server-full", "Local Server (Full Guide)", "local-server-full.md"),
    ("local-server-tldr", "Local Server (TLDR)", "local-server-tldr.md"),
    ("public-server-full", "Public Server (Full Guide)", "public-server-full.md"),
    ("public-server-tldr", "Public Server (TLDR)", "public-server-tldr.md"),
    ("faq", "FAQ", "faq.md"),
    ("troubleshooting", "Troubleshooting", "troubleshooting.md"),
    ("technical-docs", "Technical Documentation", "technical-docs.md"),
]
PAGE_LOOKUP = {slug: (title, filename) for slug, title, filename in PAGES}

PAGE_LINK_PREFIX = "page:"

HTML_TEMPLATE = """<html><head><style>
body {{
    background-color: {bg};
    color: {parch};
    font-family: Georgia, 'Segoe UI', serif;
    font-size: 12px;
    padding: 18px 20px;
    line-height: 1.45;
}}
h1 {{ color: {amber}; border-bottom: 1px solid {border}; padding-bottom: 6px; margin-top: 0; font-size: 18px; }}
h2 {{ color: {amber}; margin-top: 20px; font-size: 14px; }}
h3 {{ color: {amber_dim}; font-size: 12px; }}
h4 {{ color: {amber_dim}; font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
a {{ color: {amber}; }}
code {{ background-color: {surf2}; color: {parch}; padding: 1px 4px; border-radius: 3px; font-family: Consolas, monospace; font-size: 11px; }}
pre {{ background-color: {surf2}; padding: 10px; border-radius: 4px; overflow-x: auto; }}
pre code {{ padding: 0; background: none; }}
blockquote {{ border-left: 3px solid {border}; margin-left: 0; padding-left: 12px; color: {muted}; }}
hr {{ border: none; border-top: 1px solid {border}; }}
li {{ margin-bottom: 3px; }}
table {{ border-collapse: collapse; }}
td, th {{ border: 1px solid {border}; padding: 5px 8px; font-size: 11px; }}
</style></head>
<body>
{content}
</body></html>"""


def _render_html(slug):
    title, filename = PAGE_LOOKUP[slug]
    path = os.path.join(HELP_CONTENT_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            md_text = f.read()
    except OSError:
        md_text = f"# {title}\n\n*This page hasn't been written yet.*"
    body_html = markdown.markdown(md_text, extensions=["fenced_code", "tables"])
    return HTML_TEMPLATE.format(
        bg=BG, surf2=SURF2, border=BORDER, amber=AMBER, amber_dim=AMBERDIM,
        parch=PARCH, muted=MUTED, content=body_html,
    )


class HelpDockWindow(tk.Toplevel):
    """Borderless window docked against the right edge of anchor, showing
    the rendered help content. Tracks anchor's position/size but never
    modifies anchor itself."""
    WIDTH = 620

    def __init__(self, anchor):
        super().__init__(anchor)
        self._anchor = anchor
        _start_hidden(self)
        self.overrideredirect(True)
        self.transient(anchor)
        self.configure(bg=BG, highlightbackground=BORDER, highlightthickness=1)
        self._nav_buttons = {}
        self._build()
        self._reposition()
        _finish_dark_window(self)
        self.show("index")

    def _build(self):
        header = tk.Frame(self, bg=SURF, height=32)
        header.pack(fill="x"); header.pack_propagate(False)
        tk.Label(header, text="📖  Help", bg=SURF, fg=AMBER,
                 font=("Georgia",10,"bold")).pack(side="left", padx=12, pady=5)
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True)

        nav = tk.Frame(body, bg=SURF, width=150)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        for slug, title, _filename in PAGES:
            btn = tk.Button(nav, text=title, bg=SURF, fg=PARCH,
                            activebackground=AMBERDIM, activeforeground="#ffd080",
                            relief="flat", bd=0, anchor="w", cursor="hand2",
                            font=("Segoe UI",8), wraplength=132, justify="left",
                            command=lambda s=slug: self.show(s))
            btn.pack(fill="x", padx=4, pady=1, ipady=2)
            self._nav_buttons[slug] = btn
        tk.Frame(body, bg=BORDER, width=1).pack(side="left", fill="y")

        self._html = HtmlFrame(body, messages_enabled=False,
                               on_link_click=self._on_link_click)
        self._html.pack(side="left", fill="both", expand=True)

    def show(self, slug):
        if slug not in PAGE_LOOKUP:
            return
        self._html.load_html(_render_html(slug))
        for s, btn in self._nav_buttons.items():
            btn.config(bg=AMBERDIM if s == slug else SURF,
                      fg="#ffd080" if s == slug else PARCH)

    def _on_link_click(self, url):
        if url.startswith(PAGE_LINK_PREFIX):
            self.show(url[len(PAGE_LINK_PREFIX):])
        elif url.startswith("http://") or url.startswith("https://"):
            webbrowser.open(url)

    def reposition(self):
        try:
            x = self._anchor.winfo_rootx() + self._anchor.winfo_width()
            y = self._anchor.winfo_rooty()
            h = self._anchor.winfo_height() // 2
            self.geometry(f"{self.WIDTH}x{h}+{x}+{y}")
            self.update_idletasks()
        except tk.TclError:
            pass

    _reposition = reposition  # called internally before first reveal


class HelpTab(tk.Toplevel):
    """Small floating tab pinned to the right edge of anchor. Click to
    toggle a HelpDockWindow open/closed. Never touches anchor's own size
    or widget tree."""

    def __init__(self, anchor):
        super().__init__(anchor)
        self._anchor = anchor
        self._dock = None
        _start_hidden(self)
        self.overrideredirect(True)
        self.transient(anchor)
        self.configure(bg=SURF2, highlightbackground=BORDER, highlightthickness=1)

        tk.Button(self, text="📖", bg=SURF2, fg=AMBER,
                 activebackground=AMBERDIM, activeforeground="#ffd080",
                 relief="flat", bd=0, cursor="hand2", font=("Segoe UI",13),
                 command=self._toggle).pack(ipadx=6, ipady=14)

        self._reposition()
        _finish_dark_window(self)

        anchor.bind("<Configure>", self._on_anchor_configure, add="+")
        anchor.bind("<Destroy>", self._on_anchor_destroy, add="+")

    def _on_anchor_configure(self, event=None):
        if event is not None and event.widget is not self._anchor:
            return
        self._reposition()
        if self._dock is not None:
            self._dock.reposition()

    def _on_anchor_destroy(self, event=None):
        if self._dock is not None:
            self._dock.destroy()
        self.destroy()

    def _reposition(self):
        try:
            base_x = self._anchor.winfo_rootx() + self._anchor.winfo_width()
            if self._dock is not None:
                base_x += HelpDockWindow.WIDTH
            y = self._anchor.winfo_rooty() + 70
            self.geometry(f"+{base_x}+{y}")
            self.update_idletasks()
            self.lift()
        except tk.TclError:
            pass

    def _toggle(self):
        if self._dock is not None:
            self._dock.destroy()
            self._dock = None
        else:
            self._dock = HelpDockWindow(self._anchor)
        self._reposition()
        self.lift()


def attach_help_tab(root):
    return HelpTab(root)
