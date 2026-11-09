import ctypes
import sys
import tkinter as tk
import tkinter.font as tkfont
from ctypes import wintypes

from tavern_shared.theme import _mk_scrollbar

MIN_OPEN_WIDTH = 540
FLOOR_WIDTH = 420
FLOOR_HEIGHT = 320
LOG_MIN_LINES = 4
SCROLL_STEP = 24
NEAR_EDGE = 120
OWN_WHEEL = {"Text", "Listbox", "TCombobox", "Treeview"}


class _MonitorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


def _work_area(window):
    if sys.platform == "win32":
        try:
            user32 = ctypes.WinDLL("user32")
            user32.GetParent.argtypes = [wintypes.HWND]
            user32.GetParent.restype = wintypes.HWND
            user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            user32.MonitorFromWindow.restype = ctypes.c_void_p
            user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
            user32.GetMonitorInfoW.restype = wintypes.BOOL
            hwnd = user32.GetParent(window.winfo_id())
            monitor = user32.MonitorFromWindow(hwnd, 2)
            info = _MonitorInfo()
            info.cbSize = ctypes.sizeof(_MonitorInfo)
            if monitor and user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                border = user32.GetSystemMetrics(32) + user32.GetSystemMetrics(92)
                caption = user32.GetSystemMetrics(4)
                work = info.rcWork
                return work.left, work.top, work.right, work.bottom, border * 2, caption + border * 2
        except Exception:
            pass
    return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight() - 60, 16, 40


class ScreenFit:
    def __init__(self, window, bg, min_open_width=MIN_OPEN_WIDTH):
        self.window = window
        self.min_open_width = min_open_width
        self.shell = tk.Frame(window, bg=bg)
        self.shell.pack(fill="both", expand=True)
        self.shell.grid_rowconfigure(0, weight=1)
        self.shell.grid_columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.shell, bg=bg, highlightthickness=0, bd=0, width=1, height=1,
                                xscrollincrement=SCROLL_STEP, yscrollincrement=SCROLL_STEP)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vbar = _mk_scrollbar(self.shell, self.canvas.yview)
        self.hbar = _mk_scrollbar(self.shell, self.canvas.xview, "horizontal")
        self.canvas.configure(yscrollcommand=self.vbar.set, xscrollcommand=self.hbar.set)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._item = self.canvas.create_window(0, 0, anchor="nw", window=self.body)
        self.footer = None
        self.stretch = None
        self._fitted = False
        self._pending = False
        self._last = None
        self._show_v = False
        self._show_h = False
        window.bind("<Configure>", self._schedule, add="+")
        window.bind("<MouseWheel>", self._on_wheel, add="+")

    def set_parts(self, footer, stretch):
        self.footer = footer
        self.stretch = stretch

    def fit_once(self):
        if self._fitted:
            return
        self._fitted = True
        try:
            self._open_size()
        except Exception:
            pass

    def _footer_height(self):
        info = self.footer.pack_info()
        pady = info.get("pady", 0)
        if isinstance(pady, (tuple, list)):
            pady = sum(int(p) for p in pady)
        return self.footer.winfo_reqheight() + int(pady)

    def _need_height(self):
        need = self.body.winfo_reqheight()
        if self.stretch is not None:
            line = tkfont.Font(font=self.stretch.cget("font")).metrics("linespace")
            need -= max(0, int(self.stretch.cget("height")) - LOG_MIN_LINES) * line
        return need

    def _open_size(self):
        window = self.window
        window.update_idletasks()
        footer_h = self._footer_height()
        natural_w = max(self.min_open_width, self.body.winfo_reqwidth(), self.footer.winfo_reqwidth() + 28)
        natural_h = self.body.winfo_reqheight() + footer_h
        left, top, right, bottom, chrome_w, chrome_h = _work_area(window)
        room_w = right - left - chrome_w
        room_h = bottom - top - chrome_h
        width = min(natural_w, room_w)
        height = min(natural_h, room_h)
        if self._need_height() > height - footer_h:
            width = min(width + self.vbar.winfo_reqwidth(), room_w)
        window.minsize(min(width, max(FLOOR_WIDTH, self.footer.winfo_reqwidth() + 28)),
                       min(height, FLOOR_HEIGHT))
        geometry = f"{width}x{height}"
        if natural_h + NEAR_EDGE > room_h or natural_w + NEAR_EDGE > room_w:
            geometry += f"+{left + (room_w - width) // 2}+{top + (room_h - height) // 2}"
        window.geometry(geometry)
        self._layout(width, height - footer_h)
        window.after(250, self._settle)

    def _settle(self):
        window = self.window
        try:
            if not window.winfo_viewable() or window.state() != "normal":
                return
            left, top, right, bottom, chrome_w, chrome_h = _work_area(window)
            width = min(window.winfo_width(), right - left - chrome_w)
            height = min(window.winfo_height(), bottom - top - chrome_h)
            x = max(left, min(window.winfo_x(), right - width - chrome_w))
            y = max(top, min(window.winfo_y(), bottom - height - chrome_h))
            if (x, y, width, height) != (window.winfo_x(), window.winfo_y(),
                                         window.winfo_width(), window.winfo_height()):
                window.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:
            pass

    def _schedule(self, event=None):
        if self._pending:
            return
        self._pending = True
        self.window.after_idle(self._run_layout)

    def _run_layout(self):
        self._pending = False
        try:
            self._layout(self.shell.winfo_width(), self.shell.winfo_height())
        except tk.TclError:
            pass

    def _layout(self, width, height):
        if width <= 1 or height <= 1:
            return
        need_w = self.body.winfo_reqwidth()
        need_h = self._need_height()
        bar_w = self.vbar.winfo_reqwidth()
        bar_h = self.hbar.winfo_reqheight()
        show_v = need_h > height
        show_h = need_w > width
        if show_v and not show_h:
            show_h = need_w > width - bar_w
        if show_h and not show_v:
            show_v = need_h > height - bar_h
        view_w = width - (bar_w if show_v else 0)
        view_h = height - (bar_h if show_h else 0)
        body_w = max(view_w, need_w)
        body_h = max(view_h, need_h)
        state = (body_w, body_h, show_v, show_h)
        if state == self._last:
            return
        self._last = state
        self._set_bar(self.vbar, show_v, self._show_v, row=0, column=1, sticky="ns")
        self._set_bar(self.hbar, show_h, self._show_h, row=1, column=0, sticky="ew")
        self._show_v = show_v
        self._show_h = show_h
        self.canvas.itemconfigure(self._item, width=body_w, height=body_h)
        self.canvas.configure(scrollregion=(0, 0, body_w, body_h))
        if not show_v:
            self.canvas.yview_moveto(0)
        if not show_h:
            self.canvas.xview_moveto(0)

    @staticmethod
    def _set_bar(bar, show, shown, **grid):
        if show and not shown:
            bar.grid(**grid)
        elif shown and not show:
            bar.grid_remove()

    def _on_wheel(self, event):
        try:
            if event.widget.winfo_class() in OWN_WHEEL:
                return
        except (AttributeError, tk.TclError):
            return
        step = -1 if event.delta > 0 else 1
        if event.state & 1:
            if self._show_h:
                self.canvas.xview_scroll(step, "units")
        elif self._show_v:
            self.canvas.yview_scroll(step, "units")
