"""Read a visible Windows window and send checked mouse or keyboard input."""

from contextlib import contextmanager
from ctypes import byref, c_void_p, sizeof, windll
from time import monotonic
from uuid import uuid4

import win32api
import win32con
import win32gui
import win32process

from app_runtime_ import check_cancelled


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
        "preview": model_image(image),
        "captured": monotonic(),
    }


def model_image(image):
    """Keep screenshots readable while limiting the pixels sent to the model."""
    from PIL import Image

    preview = image.copy()
    preview.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    return preview


def screen_point(frame, x, y):
    """Map a pixel in the model image to the center of its area on screen.

    Example: a 2x smaller preview at screen origin (-500, 100).
    Preview point (10, 20) maps to screen point (-479, 141).
    """
    width, height = frame["preview"].size
    if type(x) is not int or type(y) is not int or not (0 <= x < width and 0 <= y < height):
        raise ValueError("Choose integer coordinates inside the current screenshot.")

    left, top, right, bottom = frame["bounds"]
    return (
        left + (2 * x + 1) * (right - left) // (2 * width),
        top + (2 * y + 1) * (bottom - top) // (2 * height),
    )


def checked_frame(state, view_id):
    """Reject old coordinates or a changed scene before any input is sent."""
    from PIL import ImageChops

    frame = state.get("frame")
    if frame is None or frame["id"] != view_id or monotonic() - frame["captured"] > 45:
        raise RuntimeError("That screenshot is no longer current. Start again.")

    current = capture_window(frame["handle"])
    if (current["process"], current["bounds"]) != (frame["process"], frame["bounds"]):
        raise RuntimeError("The window moved or changed. Start again.")

    changed = ImageChops.difference(frame["image"], current["image"]).getbbox()
    # A blinking text cursor can change a narrow strip without moving a target.
    if changed and (changed[2] - changed[0] > 3 or changed[3] - changed[1] > 40):
        raise RuntimeError("The visible window changed before input. Start again.")
    return frame


def target_at(frame, point):
    """Check what would actually receive a pointer event at this position."""
    if (frame["process"], frame["bounds"]) != window_bounds(frame["handle"]):
        raise RuntimeError("The target window moved. Start again.")
    hit = win32gui.WindowFromPoint(point)
    if not hit or win32gui.GetAncestor(hit, 2) != frame["handle"]:
        raise RuntimeError("Another window covers that point. No click or scroll was sent.")
    return hit


@contextmanager
def pointer_target(state, view_id, x, y):
    """Move to a current screenshot point and keep the pixel scale through input."""
    check_cancelled(state)
    with physical_pixels():
        frame = checked_frame(state, view_id)
        point = screen_point(frame, x, y)
        hit = target_at(frame, point)
        check_cancelled(state)
        state.pop("frame")  # Moving the pointer can change the page through hover.
        try:
            win32api.SetCursorPos(point)
        except win32api.error:
            raise RuntimeError("Could not move the cursor on this Windows desktop.") from None
        if win32api.GetCursorPos() != point or target_at(frame, point) != hit:
            raise RuntimeError("The pointer target changed. No click or scroll was sent.")
        check_cancelled(state)
        yield


def move_pointer(state, view_id, x, y):
    """Move the real cursor to a checked image point without clicking."""
    with pointer_target(state, view_id, x, y):
        return "Pointer moved. Check the new screenshot."


def send_inputs(events, releases=()):
    """Send a batch to Windows. Release any held input if only part was accepted."""
    from pywinauto.win32functions import SendInput
    from pywinauto.win32structures import INPUT

    batch = (INPUT * len(events))(*events)
    if SendInput(len(batch), byref(batch), sizeof(INPUT)) == len(batch):
        return

    if releases:
        cleanup = (INPUT * len(releases))(*releases)
        SendInput(len(cleanup), byref(cleanup), sizeof(INPUT))
    raise RuntimeError("Input outcome is uncertain. Check the window before repeating it.")


def mouse_input(flag, data=0):
    """Make one Windows mouse event. Flag selects the button or wheel."""
    from pywinauto.win32structures import INPUT

    event = INPUT()
    event.type = 0  # INPUT_MOUSE
    event.mi.dwFlags = flag
    event.mi.mouseData = data
    return event


def click_pointer(state, view_id, x, y, button, count):
    """Send one primary/secondary click or a double click to a checked point."""
    if button not in ("left", "right") or type(count) is not int or count not in (1, 2):
        raise ValueError("Choose left or right and a click count of 1 or 2.")

    # Respect the Windows setting for users with swapped mouse buttons.
    swapped = win32api.GetSystemMetrics(win32con.SM_SWAPBUTTON)
    primary = (button == "left") != bool(swapped)
    if primary:
        down, up = win32con.MOUSEEVENTF_LEFTDOWN, win32con.MOUSEEVENTF_LEFTUP
    else:
        down, up = win32con.MOUSEEVENTF_RIGHTDOWN, win32con.MOUSEEVENTF_RIGHTUP
    events = [mouse_input(down), mouse_input(up)] * count

    with pointer_target(state, view_id, x, y):
        send_inputs(events, [events[-1]])
    return "Click sent. Check the new screenshot for the result."


def scroll_pointer(state, view_id, x, y, steps):
    """Scroll at a checked point. Positive steps go up; negative steps go down."""
    if type(steps) is not int or steps == 0 or abs(steps) > 8:
        raise ValueError("Choose 1 to 8 wheel steps in either direction.")

    with pointer_target(state, view_id, x, y):
        send_inputs([mouse_input(win32con.MOUSEEVENTF_WHEEL, 120 * steps)])
    return "Wheel input sent. Check the new screenshot."
