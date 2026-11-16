"""Host a SUMO GUI window inside a Tk frame on Windows."""
import ctypes
from ctypes import wintypes
import time

user32 = ctypes.WinDLL("user32", use_last_error=True)
EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = (EnumWindowsProc, wintypes.LPARAM)
user32.EnumChildWindows.argtypes = (wintypes.HWND, EnumWindowsProc, wintypes.LPARAM)
user32.GetClassNameW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
user32.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
user32.IsWindow.argtypes = (wintypes.HWND,)
user32.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
user32.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_long)
user32.SetParent.argtypes = (wintypes.HWND, wintypes.HWND)
user32.SetParent.restype = wintypes.HWND
user32.GetParent.argtypes = (wintypes.HWND,)
user32.GetParent.restype = wintypes.HWND
user32.MoveWindow.argtypes = (wintypes.HWND, ctypes.c_int, ctypes.c_int,
                             ctypes.c_int, ctypes.c_int, wintypes.BOOL)
user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT)


def embed(frame, process):
    matches = []

    @EnumWindowsProc
    def collect(hwnd, _):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == process.pid:
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            if "grid.net.xml" in title.value:
                matches.append(hwnd)
        return True

    deadline = time.monotonic() + 8
    while not matches and time.monotonic() < deadline:
        user32.EnumWindows(collect, 0)
        if not matches:
            frame.update_idletasks()
            time.sleep(0.05)
    if not matches:
        raise RuntimeError("Could not locate the native SUMO window")

    hwnd = matches[0]
    parent = frame.winfo_id()
    style = user32.GetWindowLongW(hwnd, -16)
    user32.SetWindowLongW(hwnd, -16, (style & ~0x80CF0000) | 0x40000000)
    user32.SetParent(hwnd, parent)
    if user32.GetParent(hwnd) != parent:
        raise RuntimeError("Windows could not attach the SUMO view")
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x37)

    canvas = []

    @EnumWindowsProc
    def find_canvas(child, _):
        name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(child, name, len(name))
        if name.value == "FXGLCanvas":
            canvas.append(child)
            return False
        return True

    user32.EnumChildWindows(hwnd, find_canvas, 0)
    if not canvas:
        raise RuntimeError("Could not locate the SUMO map inside the window")
    outer, inner = wintypes.RECT(), wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(outer))
    user32.GetWindowRect(canvas[0], ctypes.byref(inner))
    left, top = inner.left - outer.left, inner.top - outer.top
    horizontal = left + outer.right - inner.right
    vertical = top + outer.bottom - inner.bottom

    def resize(event=None):
        if user32.IsWindow(hwnd):
            width, height = ((event.width, event.height) if event else
                             (frame.winfo_width(), frame.winfo_height()))
            # Keep FOX's layout intact and let the host clip everything outside the map.
            user32.MoveWindow(hwnd, -left, -top, width + horizontal, height + vertical, True)

    frame.bind("<Configure>", resize)
    resize()

    def align_canvas():
        nonlocal left, top, horizontal, vertical
        if not user32.IsWindow(hwnd) or not user32.IsWindow(canvas[0]):
            return
        user32.GetWindowRect(hwnd, ctypes.byref(outer))
        user32.GetWindowRect(canvas[0], ctypes.byref(inner))
        new_left, new_top = inner.left - outer.left, inner.top - outer.top
        new_horizontal = new_left + outer.right - inner.right
        new_vertical = new_top + outer.bottom - inner.bottom
        if (left, top, horizontal, vertical) != (new_left, new_top, new_horizontal, new_vertical):
            left, top, horizontal, vertical = new_left, new_top, new_horizontal, new_vertical
            resize()
        frame.after(500, align_canvas)

    # FOX settles its toolbar geometry after the first resize.
    frame.after(500, align_canvas)

    def detach():
        if user32.IsWindow(hwnd):
            user32.SetParent(hwnd, None)

    return detach
