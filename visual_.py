"""Read a visible Windows window and send checked mouse or keyboard input."""

from contextlib import contextmanager
from ctypes import byref, c_void_p, sizeof, windll
from time import monotonic
from uuid import uuid4

import win32api
import win32gui
import win32process


@contextmanager
def physical_pixels():
    """Use real screen pixels on this thread, including on scaled monitors."""
    set_context = windll.user32.SetThreadDpiAwarenessContext
    set_context.argtypes = [c_void_p]
    set_context.restype = c_void_p
    previous = set_context(c_void_p(-4))  # Per-monitor DPI awareness, version 2.
    if not previous:
        raise RuntimeError("Windows could not set physical screen coordinates.")
    try:
        yield
    finally:
        set_context(previous)


def window_bounds(handle):
    """Read the foreground window and its visible bounds on its main monitor."""
    if not handle or win32gui.GetForegroundWindow() != handle:
        raise RuntimeError("The target window lost focus. Select it and start again.")

    _, process = win32process.GetWindowThreadProcessId(handle)
    left, top, right, bottom = win32gui.GetWindowRect(handle)
    monitor = win32api.MonitorFromWindow(handle, 2)  # Nearest monitor.
    x1, y1, x2, y2 = win32api.GetMonitorInfo(monitor)["Monitor"]
    bounds = (max(left, x1), max(top, y1), min(right, x2), min(bottom, y2))
    if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
        raise RuntimeError("The target window is outside the visible screen.")
    return process, bounds


def capture_window(handle):
    """Capture the visible window area in memory and label this one reading."""
    from PIL import ImageGrab

    with physical_pixels():
        process, bounds = window_bounds(handle)
        try:
            image = ImageGrab.grab(bbox=bounds, all_screens=True).convert("RGB")
        except OSError:
            raise RuntimeError("Could not capture this window. Check that Windows is unlocked.") from None

        # Capture and window geometry must describe the same moment.
        if (process, bounds) != window_bounds(handle):
            raise RuntimeError("The window moved during capture. Start again.")

    return {
        "id": uuid4().hex,
        "handle": handle,
        "process": process,
        "bounds": bounds,
        "image": image,
        "captured": monotonic(),
    }
