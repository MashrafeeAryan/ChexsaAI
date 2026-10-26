"""Open Windows apps and read their visible controls."""

import json  # Keeps names readable when they contain quotes or line breaks.
from pathlib import Path
import shlex  # Separates a program path from any startup options.
import win32gui  # Checks which window will actually receive keyboard input.
from time import monotonic, sleep

from pywinauto import Application, Desktop  # Open apps and find their windows.
from pywinauto.application import ProcessNotFoundError, process_module
from pywinauto.uia_defines import IUIA, NoPatternInterfaceError
from comtypes import COMError  # Windows may report an error when a control disappears.


def open_app(executable):
    """Open an app and return its visible window for later reading or clicking.

    Give a program name or quoted path, such as 'notepad.exe'.
    """
    if not isinstance(executable, str) or not executable.strip():
        raise ValueError("Give the name or path of the app to open.")
    program = Path(shlex.split(executable, posix=False)[0].strip('"')).name.casefold()

    # "uia" reads Windows accessibility information instead of guessing screen positions.
    desktop = Desktop(backend="uia")
    app = Application(backend="uia").start(executable, wait_for_idle=False)
    deadline = monotonic() + 15  # Wait at most 15 seconds, not a fixed 15-second pause.
    while monotonic() < deadline:
        windows = desktop.windows(process=app.process)
        if not windows and not app.is_process_running():
            # Some launchers exit after handing the app to another process.
            # Match the exact program filename, never just a similar window title.
            for window in desktop.windows():
                try:
                    if Path(process_module(window.process_id())).name.casefold() == program:
                        windows.append(window)
                except (OSError, ProcessNotFoundError):
                    continue  # A window may close while we are checking it.
        if len(windows) == 1:
            return windows[0]
        if len(windows) > 1:
            raise RuntimeError("More than one app window matched. Choose a window before continuing.")
        sleep(0.2)

    raise RuntimeError("The app did not show a matching window within 15 seconds.")


# Keep controls and useful text; leave out boxes used only to arrange the layout.
_READABLE_TYPES = {
    "Button", "Edit", "Document", "ComboBox", "CheckBox", "RadioButton",
    "MenuItem", "TabItem", "ListItem", "TreeItem", "Hyperlink", "Slider",
    "Spinner", "ScrollBar", "Text", "StatusBar", "DataItem",
}


# Remember the latest reading for each window; older readings cannot run actions.
_observations = {}


def read_window(window):
    """Describe the visible controls inside this window without changing anything.

    Keep the real controls locally so later actions can use the exact same objects.
    """
    if not window.is_visible():
        raise RuntimeError("This window is closed or hidden. Choose a visible window.")

    window_id = tuple(window.element_info.runtime_id or ())
    if not window_id:
        raise RuntimeError("Windows could not identify this window. Read it again.")
    _observations.pop(window_id, None)
    title = window.window_text()
    controls, lines = {}, []
    unavailable = 0
    for control in window.descendants():
        try:
            info = control.element_info
            if info.control_type not in _READABLE_TYPES or not control.is_visible():
                continue
            # Windows gives each control a runtime ID. Two same-name buttons stay separate.
            node_id = tuple(info.runtime_id or ())
            if not node_id:
                unavailable += 1
                continue
            line = f"{json.dumps(node_id)} {info.control_type} {json.dumps(info.name or '', ensure_ascii=False)}"
            if not control.is_enabled():
                line += " | disabled"
            controls[node_id] = control
            lines.append(line)
        except (COMError, OSError):
            unavailable += 1  # A control may disappear while the window is being read.

    # Only title and elements are for the model. The control objects stay in Python.
    observation = {"title": title, "elements": "\n".join(lines), "controls": controls,
                   "unavailable_controls": unavailable, "window": window, "window_id": window_id}
    _observations[window_id] = observation
    return observation



def _get_control(observation, node_id):
    """Find the exact control from the latest reading and check it is still usable."""
    if not isinstance(node_id, (list, tuple)) or not node_id or any(type(part) is not int for part in node_id):
        raise ValueError("Give a Windows control ID from the current reading.")
    if _observations.get(observation["window_id"]) is not observation:
        raise RuntimeError("This reading is old or already used. Read the window again.")
    control = observation["controls"].get(tuple(node_id))
    if control is None:
        raise RuntimeError("This control was not in the window reading.")
    try:
        window = observation["window"]
        if not window.is_visible() or tuple(window.element_info.runtime_id or ()) != observation["window_id"]:
            raise RuntimeError("The observed window is no longer available.")
        if tuple(control.element_info.runtime_id or ()) != tuple(node_id):
            raise RuntimeError("The control changed. Read the window again.")
        if tuple(control.top_level_parent().element_info.runtime_id or ()) != observation["window_id"]:
            raise RuntimeError("The control no longer belongs to this window.")
        if not control.is_visible() or not control.is_enabled():
            raise RuntimeError("This control is hidden or disabled.")
    except (COMError, OSError):
        raise RuntimeError("The control disappeared. Read the window again.") from None
    return control


def click_control(observation, node_id):
    """Click one observed control, then require a fresh window reading.

    A click being sent does not prove that the requested task finished.
    """
    control = _get_control(observation, node_id)
    try:
        invoke = control.iface_invoke
    except NoPatternInterfaceError:
        invoke = None

    _observations.pop(observation["window_id"], None)
    try:
        if invoke is not None:
            invoke.Invoke()  # Ask Windows to activate this exact control without aiming a mouse.
        else:
            control.set_focus()  # Focus the exact control through Windows accessibility.
            point = control.rectangle().mid_point()
            hit = Desktop(backend="uia").from_point(point.x, point.y)
            # A label inside the control is fine; an overlapping window is not.
            while hit is not None and tuple(hit.element_info.runtime_id or ()) != tuple(node_id):
                hit = hit.parent()
            if hit is None:
                raise RuntimeError("Another control covers the click point. Read the window again.")
            control.click_input()
    except Exception as error:
        raise RuntimeError("The click outcome is uncertain. Read the window before continuing; do not repeat it automatically.") from error
    return "Click sent. Read the window again to check the result."


def type_text(observation, node_id, text):
    """Replace the chosen field or document's text and check what was entered.

    Stop on an uncertain result instead of automatically typing the text again.
    """
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("Give text without null characters to enter.")
    control = _get_control(observation, node_id)
    if control.element_info.control_type not in ("Edit", "Document", "ComboBox"):
        raise RuntimeError("Choose an editable field or document.")
    try:
        value = control.iface_value
    except NoPatternInterfaceError:
        value = None
    if value is not None:
        if value.CurrentIsReadOnly:
            raise RuntimeError("This field is read-only.")
    else:
        # This keyboard path cannot yet verify emoji reliably; stop before editing.
        if any(ord(char) > 0xFFFF for char in text):
            raise RuntimeError("Emoji and other supplementary characters are not supported in this editor yet.")
        # Document editors such as Word expose readable text but no direct text setter.
        try:
            text_range = control.iface_text.DocumentRange
            readonly = text_range.GetAttributeValue(IUIA().ui_automation_client.UIA_IsReadOnlyAttributeId)
            if readonly is True or readonly == 1:
                raise RuntimeError("This document is read-only.")
            text_range.GetText(-1)  # Check that we can read the text back before typing.
        except NoPatternInterfaceError:
            raise RuntimeError("This control does not support verified text entry.") from None

    expected = text.replace("\r\n", "\n").replace("\r", "\n")
    _observations.pop(observation["window_id"], None)
    try:
        if value is not None:
            value.SetValue(text)
        else:
            control.set_focus()  # Focus the exact control through Windows accessibility.
            if win32gui.GetForegroundWindow() != observation["window"].handle or not control.has_keyboard_focus():
                raise RuntimeError("The selected editor did not receive keyboard focus.")
            control.type_keys("^a", pause=0, turn_off_numlock=False, set_foreground=False)  # Select this editor's existing text.
            if win32gui.GetForegroundWindow() != observation["window"].handle or not control.has_keyboard_focus():
                raise RuntimeError("Keyboard focus changed before typing.")
            # Escape shortcut symbols so text such as {ENTER} is typed literally.
            keys = "".join("{" + char + "}" if char in "+^%~(){}" else char for char in expected)
            control.type_keys(keys or "{BACKSPACE}", pause=0, with_spaces=True, with_tabs=True,
                              with_newlines=True, turn_off_numlock=False, set_foreground=False)
        # Let the app finish processing input; checking again never repeats the typing.
        deadline = monotonic() + 2
        matched_at = None
        while True:
            actual = value.CurrentValue if value is not None else control.iface_text.DocumentRange.GetText(-1)
            actual = actual.replace("\r\n", "\n").replace("\r", "\n")
            # Word may include its required final paragraph mark in the text reading.
            now = monotonic()
            if actual == expected or (value is None and actual == expected + "\n"):
                if matched_at is None:
                    matched_at = now
                elif now - matched_at >= 0.2:
                    break  # Require a stable read-back, not a single brief match.
            else:
                matched_at = None
            if now >= deadline:
                raise RuntimeError("The field's text did not match what was requested.")
            sleep(0.05)
    except Exception as error:
        raise RuntimeError("Text entry could not be verified. Read the window and investigate before typing again.") from error
    return "Text entered and verified."
