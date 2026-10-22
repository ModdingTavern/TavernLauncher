"""
Window-chrome helpers shared by both apps: dark title bar tinting, the
app icon, and the header-banner crop math. Client's versions used
throughout (server's copies had only cosmetic drift -- an extra bare
`except:` here, a slightly different default there -- confirmed via diff
before merging, not just picked arbitrarily).
"""
import os
import sys
import ctypes
import tempfile
import base64
import io

_ICON_B64 = None
try:
    from icon_data import ICON_B64 as _ICON_B64
except ImportError:
    pass

def _apply_dark_attribute(window):
    """Just the DWMWA_USE_IMMERSIVE_DARK_MODE attribute itself, factored
    out since both _enable_dark_titlebar (the original, reapply-after-
    the-fact approach) and _start_hidden/_finish_dark_window (the new
    apply-before-first-show approach) both need it."""
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+/Win11)
        ok = ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
        if ok != 0:
            # 19 = older Win10 1809/1903 builds that used the pre-release attribute id
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def _start_hidden(window):
    """Call this FIRST, immediately after super().__init__(), before any
    widgets are built. Withdraws the window and applies the dark title
    bar attribute right away -- this works fine on a withdrawn window,
    since the native HWND exists as soon as the Tk widget itself does,
    regardless of visibility.

    Pairs with _finish_dark_window() at the end of __init__. Together
    these replace showing the window immediately (as a plain white
    native window, before Tkinter has finished building or painting its
    actual dark-themed contents) and then fixing up the title bar
    afterward -- which is what caused the visible white flash every
    window previously had for a brief moment on open. Building
    everything while hidden and only revealing it once both the content
    and the title bar are already correct means the very first frame
    the user ever sees is already right.
    """
    try:
        window.withdraw()
    except Exception:
        pass
    _apply_dark_attribute(window)


def _finish_dark_window(window):
    """Call this LAST, after all widgets/geometry are fully set up --
    see _start_hidden()'s docstring. A window that has never been shown
    before doesn't need the hide/show repaint trick _enable_dark_titlebar
    uses below -- that trick exists specifically to force DWM to redraw
    an ALREADY-VISIBLE light-mode title bar, which doesn't apply here
    since deiconify() is this window's first-ever appearance; DWM
    composes it correctly from the current attribute value the first
    time, same as most apps that set this before their first show."""
    _apply_dark_attribute(window)
    try:
        window.update_idletasks()
        window.deiconify()
    except Exception:
        pass


def _enable_dark_titlebar(window):
    """Tint a Tk window's OS title bar dark. Windows 10 (1809+)/11 only;
    silently does nothing anywhere else.

    Kept for anything that shows a window immediately rather than using
    the _start_hidden/_finish_dark_window pair above -- forces a hide/
    show cycle after setting the attribute, since DWM only repaints an
    *already-visible* window's caption on a real recompose (a plain
    SetWindowPos frame-changed message isn't reliable enough). Runs once
    immediately and once more via after(), since the window isn't mapped
    until mainloop() starts."""
    if sys.platform != "win32":
        return

    def _apply(force_repaint):
        _apply_dark_attribute(window)
        if not force_repaint:
            return
        try:
            hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
            SW_HIDE, SW_SHOWNA = 0, 8
            ctypes.windll.user32.ShowWindow(hwnd, SW_HIDE)
            ctypes.windll.user32.ShowWindow(hwnd, SW_SHOWNA)
        except Exception:
            pass

    _apply(force_repaint=False)
    try:
        window.after(60, lambda: _apply(force_repaint=True))
    except Exception:
        pass


def _set_window_icon(root):
    if not _ICON_B64: return
    try:
        tmp = os.path.join(tempfile.gettempdir(), "tavern_icon.ico")
        with open(tmp, "wb") as f: f.write(base64.b64decode(_ICON_B64))
        root.iconbitmap(tmp)
        if root.master is None:
            # The app's own root: also make this the default for every window
            # created later -- including stock dialogs like simpledialog, which
            # no per-window call can reach and would otherwise show Tk's feather.
            root.iconbitmap(default=tmp)
    except Exception: pass


def _header_crop_box(src_w, src_h, target_w, target_h,
                      min_reveal=0.35, min_width=540, reveal_at_width=1400):
    """A centered crop box (source-image pixel coordinates) matching the
    target aspect ratio exactly, so scaling it up to (target_w, target_h)
    afterward never distorts anything — unlike stretching the whole image
    to an arbitrary width, which is what made it look "stretched super far"
    on a maximized window. At the smallest window width this shows a
    modestly zoomed-in slice near the center of the artwork; widening the
    window smoothly reveals more of it (rather than stretching the same
    content further) up to showing the whole image by reveal_at_width, and
    simply staying fully revealed (scaled larger) beyond that."""
    target_w = max(int(target_w), 1)
    target_h = max(int(target_h), 1)
    span = max(1, reveal_at_width - min_width)
    reveal = min_reveal + (1.0 - min_reveal) * min(1.0, max(0.0, (target_w - min_width) / span))
    crop_w = src_w * reveal
    crop_h = crop_w * target_h / target_w
    if crop_h > src_h:
        crop_h = src_h
        crop_w = crop_h * target_w / target_h
    crop_w = min(crop_w, src_w)
    cx, cy = src_w / 2.0, src_h / 2.0
    left   = max(0, int(round(cx - crop_w / 2.0)))
    top    = max(0, int(round(cy - crop_h / 2.0)))
    right  = min(src_w, int(round(cx + crop_w / 2.0)))
    bottom = min(src_h, int(round(cy + crop_h / 2.0)))
    return (left, top, right, bottom)

