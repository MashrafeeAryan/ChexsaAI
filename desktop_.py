"""Open Windows apps and read their visible controls."""

import json  # Keeps names readable when they contain quotes or line breaks.
from pathlib import Path
import shlex  # Separates a program path from any startup options.
from shutil import which
import winreg  # Windows keeps registered app paths here.
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
    controls, lines, document_ids = {}, [], []
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
            # Editors can look alike. Show whether a field belongs to a document.
            in_document = info.control_type == "Document"
            context = []
            if info.control_type in ("Edit", "Document", "ComboBox"):
                parent = control.parent()
                for _ in range(8):  # Bound the walk if an app exposes a broken tree.
                    if parent is None:
                        break
                    parent_info = parent.element_info
                    identity = parent_info.runtime_id
                    if isinstance(identity, (list, tuple)) and tuple(identity) == window_id:
                        break
                    kind, name = parent_info.control_type, parent_info.name
                    if kind == "Document":
                        in_document = True
                    if isinstance(kind, str) and isinstance(name, str) and name.strip():
                        context.append(f"{kind} {json.dumps(name, ensure_ascii=False)}")
                    parent = parent.parent()
            if context:
                line += " | context: " + " > ".join(reversed(context))
            if in_document and info.control_type in ("Edit", "Document"):
                document_ids.append(list(node_id))
                line += " | document body" if info.control_type == "Edit" else " | document container"
            controls[node_id] = control
            lines.append(line)
        except (COMError, OSError):
            unavailable += 1  # A control may disappear while the window is being read.

    # Only title and elements are for the model. The control objects stay in Python.
    observation = {"title": title, "elements": "\n".join(lines), "controls": controls,
                   "unavailable_controls": unavailable, "window": window, "window_id": window_id,
                   "document_ids": document_ids}
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
            focus_window(observation["window"])
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
            focus_window(observation["window"])
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
        raise RuntimeError(f"Text entry could not be verified: {error} Read the window before trying again.") from error
    return "Text entered and verified."



def find_app(executable):
    """Find an installed program by its filename, without running shell commands."""
    if not isinstance(executable, str) or not executable.lower().endswith(".exe") or any(
        char in executable for char in '\\/:"<>|&;%^\r\n'
    ):
        raise ValueError("Give just an installed program name, such as winword.exe.")
    path = which(executable)
    if path:
        return path
    # Office and other apps may be registered in Windows without being on PATH.
    for registry in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(registry, "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + executable,
                                    0, winreg.KEY_READ | view) as key:
                    path = str(winreg.QueryValueEx(key, None)[0]).strip('"')
                    if Path(path).is_file():
                        return path
            except OSError:
                continue
    raise RuntimeError("Could not find the installed app: " + executable)


def focus_window(window):
    """Bring the chosen window forward, and stop if Windows refuses to focus it."""
    window.set_focus()
    if win32gui.GetForegroundWindow() != window.handle:
        try:
            win32gui.SetForegroundWindow(window.handle)
        except Exception:
            raise RuntimeError("Bring the selected app to the front, then try again.") from None
    if win32gui.GetForegroundWindow() != window.handle:
        raise RuntimeError("The selected app did not become the foreground window.")


def press_key(observation, keys):
    """Send a key or shortcut to this window, such as Enter or Ctrl+N."""
    if not isinstance(keys, list) or not keys or len(keys) > 4 or any(not isinstance(key, str) for key in keys):
        raise ValueError("Give a key list, such as ['CTRL', 'N'].")
    keys = [key.upper() for key in keys]
    modifiers = {"CTRL": "^", "ALT": "%", "SHIFT": "+"}
    named = {name: "{" + name + "}" for name in (
        "ENTER", "TAB", "ESC", "BACKSPACE", "DELETE", "SPACE", "UP", "DOWN", "LEFT", "RIGHT", "HOME", "END",
    )}
    base = keys[-1]
    if any(key not in modifiers for key in keys[:-1]) or len(set(keys)) != len(keys):
        raise ValueError("Use modifiers first and one key last.")
    if base not in named and not (len(base) == 1 and base.isascii() and base.isalnum()):
        raise ValueError("That key is not supported yet.")
    if _observations.get(observation["window_id"]) is not observation:
        raise RuntimeError("Read the window again before sending keys.")
    window = observation["window"]
    if tuple(window.element_info.runtime_id or ()) != observation["window_id"] or not window.is_visible():
        raise RuntimeError("The observed window is no longer available.")
    _observations.pop(observation["window_id"], None)
    focus_window(window)
    sequence = "".join(modifiers[key] for key in keys[:-1]) + named.get(base, base.lower())
    window.type_keys(sequence, set_foreground=False, pause=0, turn_off_numlock=False)
    return "Keys sent. Read the window again to check the result."


def read_text(observation, node_id):
    """Read a chosen field again so completion uses its current text."""
    control = _get_control(observation, node_id)
    try:
        text = control.iface_value.CurrentValue
    except NoPatternInterfaceError:
        text = control.iface_text.DocumentRange.GetText(-1)
    return text.replace("\r\n", "\n").replace("\r", "\n")
