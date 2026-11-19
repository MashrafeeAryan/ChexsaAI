"""Open Windows apps and read their visible controls."""

from task_metrics_ import time_step
from observations_ import control_details

from collections import Counter
import json  # Keeps names readable when they contain quotes or line breaks.
from pathlib import Path  # Gets filenames and checks whether a file exists.

import shlex  # Separates a program path from any startup options.
from shutil import which  # Finds programs in the folders listed in PATH.
import winreg  # Windows keeps registered app paths here.
import win32gui  # Checks which window will actually receive keyboard input.
from time import monotonic, sleep  # Measure waiting time and pause between checks.

from pywinauto import Application, Desktop  # Open apps and find their windows.
from pywinauto.application import ProcessNotFoundError, process_module  # Identify running apps.
# Read Windows text settings and detect unsupported control features.
from pywinauto.uia_defines import IUIA, NoPatternInterfaceError
from comtypes import COMError  # Windows may report an error when a control disappears.


def open_app(executable):
    """Open an app and return its visible window for later reading or clicking.

    Give a program name or quoted path, such as 'notepad.exe'.
    """
    # Accept a program name or path, such as notepad.exe.
    if not isinstance(executable, str) or not executable.strip():
        raise ValueError("Give the name or path of the app to open.")

    # Keep only the program filename; ignore quotes and letter case.
    program = Path(shlex.split(executable, posix=False)[0].strip('"')).name.casefold()

    # "uia" reads Windows accessibility information instead of guessing screen positions.
    desktop = Desktop(backend="uia")
    app = Application(backend="uia").start(executable, wait_for_idle=False)

    deadline = monotonic() + 15  # Wait at most 15 seconds, not a fixed 15-second pause.
    while monotonic() < deadline:
        # Find only windows belonging to the process we just opened.
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

        sleep(0.2)  # Check again soon without keeping the CPU busy.

    raise RuntimeError("The app did not show a matching window within 15 seconds.")


# Keep controls and useful text; leave out boxes used only to arrange the layout.
_READABLE_TYPES = {
    "Button", "Edit", "Document", "ComboBox", "CheckBox", "RadioButton",
    "MenuItem", "TabItem", "ListItem", "TreeItem", "Hyperlink", "Slider",
    "Spinner", "ScrollBar", "Text", "StatusBar", "DataItem",
}


# Remember the latest reading for each window; older readings cannot run actions.
_observations = {}


@time_step("observation")
def read_window(window):
    """Describe the visible controls inside this window without changing anything.

    Keep the real controls locally so later actions can use the exact same objects.
    """
    if not window.is_visible():
        raise RuntimeError("This window is closed or hidden. Choose a visible window.")

    # Tuples let us use Windows IDs as dictionary keys.
    window_id = tuple(window.element_info.runtime_id or ())

    if not window_id:
        raise RuntimeError("Windows could not identify this window. Read it again.")

    # The previous reading must no longer be used for actions.
    _observations.pop(window_id, None)

    title = window.window_text()
    controls, lines = {}, []  # Real objects for Python; descriptions for the AI.
    unavailable = 0
    try:
        focused = tuple(IUIA().iuia.GetFocusedElement().GetRuntimeId())
    except (AttributeError, COMError, OSError, TypeError):
        focused = None  # Some apps cannot report focus through Windows.

    # descendants() includes nested controls. Example printed objects:
    # [<uia_controls.ButtonWrapper - 'Save', Button, 123456>,
    #  <uia_controls.EditWrapper - 'File name', Edit, 234567>,
    #  <uia_controls.ButtonWrapper - 'Cancel', Button, 345678>
    #  <uiawrapper.UIAWrapper - '', Pane, 111111>,
    #  <uiawrapper.UIAWrapper - '', Group, 222222>,]
    # The printed numbers are debug hashes, not the runtime IDs we use.
    for control in window.descendants():
        try:
            # Will contain info such as:
            # info.name          # "Save"
            # info.control_type  # "Button"
            # info.runtime_id    # Example: [42, 1001]
            # info.process_id    # Example: 5000
            # info.rectangle     # Position and size on the screen
            info = control.element_info

            # Skip hidden controls and types we do not need.
            if info.control_type not in _READABLE_TYPES or not control.is_visible():
                continue

            # Windows gives each control a runtime ID. Two same-name buttons stay separate.
            node_id = tuple(info.runtime_id or ())
            if not node_id:
                unavailable += 1
                continue
            if node_id in controls:
                continue

            # Example description for the AI: [42, 1001] Button "Save" | disabled
            line = f"{json.dumps(node_id)} {info.control_type} {json.dumps(info.name or '', ensure_ascii=False)}"
            if not control.is_enabled():
                line += " | disabled"

            # Keep the ID-to-object lookup locally; send only the description.
            controls[node_id] = control
            lines.append(line)
            # controls keeps the real object:
            # {(42, 1001): <uia_controls.ButtonWrapper - 'Save', Button, 123456>}
            #
            # lines keeps the text description for the AI:
            # ['[42, 1001] Button "Save"']
            #
            # The AI chooses [42, 1001]; Python uses that ID to find the real object.
        except (COMError, OSError):
            unavailable += 1  # A control may disappear while the window is being read.

    # Give same-name controls enough context to tell them apart.
    labels = Counter(line.partition("] ")[2].removesuffix(" | disabled") for line in lines)
    for index, (node_id, line) in enumerate(zip(controls, lines)):
        label = line.partition("] ")[2].removesuffix(" | disabled")
        if labels[label] < 2:
            continue

        context = ""
        try:
            parent = controls[node_id].parent()
            for _ in range(3):
                if parent is None:
                    break
                name = parent.window_text()
                if isinstance(name, str) and name.strip():
                    context = " | in " + json.dumps(name[:80], ensure_ascii=False)
                    break
                parent = parent.parent()
        except (AttributeError, COMError, OSError):
            pass  # Still flag the duplicate when its parent cannot be read.
        lines[index] += f"{context} | {labels[label]} with this label"

    # The agent sends the title, descriptions, and count; objects stay local.
    observation = {
        "title": title,
        "elements": "\n".join(lines),
        "controls": controls,
        "unavailable_controls": unavailable,
        "window": window,
        "window_id": window_id,
        "focused": focused,
    }

    # Register this as the latest reading for this window.
    _observations[window_id] = observation
    return observation


def _get_control(observation, node_id, *, require_enabled=True):
    """Find the exact control from the latest reading and check it is still usable."""

    if not isinstance(node_id, (list, tuple)) or not node_id or any(type(part) is not int for part in node_id):
        raise ValueError("Give a Windows control ID from the current reading.")

    # Accept only the exact reading still registered as current.
    if _observations.get(observation["window_id"]) is not observation:
        raise RuntimeError("This reading is old or already used. Read the window again.")

    # Turn the AI's ID back into the real Windows control object.
    control = observation["controls"].get(tuple(node_id))

    if control is None:
        raise RuntimeError("This control was not in the window reading.")

    try:
        window = observation["window"]
        if not window.is_visible() or tuple(window.element_info.runtime_id or ()) != observation["window_id"]:
            raise RuntimeError("The observed window is no longer available.")

        # Make sure this is still the same control in the same window.
        if tuple(control.element_info.runtime_id or ()) != tuple(node_id):
            raise RuntimeError("The control changed. Read the window again.")
        if tuple(control.top_level_parent().element_info.runtime_id or ()) != observation["window_id"]:
            raise RuntimeError("The control no longer belongs to this window.")

        if not control.is_visible() or (require_enabled and not control.is_enabled()):
            raise RuntimeError("This control is hidden or disabled.")
    except (COMError, OSError):
        raise RuntimeError("The control disappeared. Read the window again.") from None
    return control


@time_step("observation")
def read_selection(observation, node_id):
    """Read actual selected text from a Windows text control, capped for the model."""
    control = _get_control(observation, node_id)
    try:
        if control.element_info.element.CurrentIsPassword:
            raise RuntimeError("Password field selections cannot be read.")
        ranges = control.iface_text.GetSelection()
        remaining, parts = 4001, []
        for index in range(min(ranges.Length, 10)):
            text = ranges.GetElement(index).GetText(remaining)
            parts.append(text)
            remaining -= len(text) + 1
            if remaining <= 0:
                break
    except (AttributeError, NoPatternInterfaceError, COMError, OSError):
        raise RuntimeError("This Windows control does not expose a text selection.") from None
    text = "\n".join(parts)
    return {"text": text[:4000], "more": len(text) > 4000 or len(parts) < ranges.Length}


@time_step("observation")
def inspect_control(observation, node_id):
    """Use the actual UI Automation patterns to describe what a control can do."""
    control = _get_control(observation, node_id, require_enabled=False)
    info = control.element_info
    state = {"disabled": not control.is_enabled()}
    actions = []
    if not state["disabled"]:
        patterns = (
            ("iface_invoke", "click_control", None, None),
            ("iface_toggle", "toggle_control", "checked", "CurrentToggleState"),
            ("iface_selection_item", "select_control", "selected", "CurrentIsSelected"),
            ("iface_expand_collapse", "expand_control", "expanded", "CurrentExpandCollapseState"),
        )
        for interface, action, flag, prop in patterns:
            try:
                pattern = getattr(control, interface)
                if flag:
                    value = getattr(pattern, prop)
                    if value not in (0, 1):
                        continue
                    state[flag] = bool(value)
                actions.append(action)
            except (NoPatternInterfaceError, COMError, OSError):
                continue
    return control_details(tuple(node_id), info.control_type, info.name or "", state, actions)


@time_step("action")
def click_control(observation, node_id):
    """Click one observed control, then require a fresh window reading.

    A click being sent does not prove that the requested task finished.
    """
    control = _get_control(observation, node_id)

    # Some controls support direct activation without a mouse click.
    try:
        invoke = control.iface_invoke
    except NoPatternInterfaceError:
        invoke = None

    # This action may change the window; require a new reading afterward.
    _observations.pop(observation["window_id"], None)

    try:
        if invoke is not None:
            invoke.Invoke()  # Ask Windows to activate this exact control without aiming a mouse.
        else:
            focus_window(observation["window"])
            control.set_focus()  # Focus the exact control through Windows accessibility.

            # Check what is at the control's center before clicking there.
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


@time_step("action")
def expand_control(observation, node_id, expanded):
    """Open or close a Windows group through its ExpandCollapse pattern."""
    if type(expanded) is not bool:
        raise ValueError("Choose true or false for expanded.")
    control = _get_control(observation, node_id)
    try:
        group = control.iface_expand_collapse
        before = group.CurrentExpandCollapseState
    except (NoPatternInterfaceError, COMError, OSError):
        raise RuntimeError("This control does not expose an expand or collapse action.") from None

    # UI Automation uses 0 for collapsed, 1 for expanded, and 3 for a leaf.
    desired = int(expanded)
    if before == desired:
        return {"expanded": expanded, "verified": True}
    if before not in (0, 1, 2):
        raise RuntimeError("This control has no expandable children.")

    _observations.pop(observation["window_id"], None)
    try:
        if expanded:
            group.Expand()
        else:
            group.Collapse()
        if group.CurrentExpandCollapseState == desired:
            return {"expanded": expanded, "verified": True}
    except (COMError, OSError):
        pass
    raise RuntimeError("The expand or collapse result is uncertain. Read the window again.")


@time_step("action")
def select_control(observation, node_id):
    """Select an exact list item, tab, or option via UI Automation."""
    control = _get_control(observation, node_id)
    try:
        selection = control.iface_selection_item
        if selection.CurrentIsSelected:
            return {"selected": True, "verified": True}
    except (NoPatternInterfaceError, COMError, OSError):
        raise RuntimeError("This control does not expose a selection action.") from None

    _observations.pop(observation["window_id"], None)
    try:
        selection.Select()
        if selection.CurrentIsSelected:
            return {"selected": True, "verified": True}
    except (COMError, OSError):
        pass
    raise RuntimeError("The selection could not be verified. Read the window before trying again.")


@time_step("action")
def toggle_control(observation, node_id, checked):
    """Set a Windows toggle through its accessibility pattern and verify it."""
    if type(checked) is not bool:
        raise ValueError("Choose true or false for checked.")
    control = _get_control(observation, node_id)
    try:
        toggle = control.iface_toggle
        before = toggle.CurrentToggleState
    except (NoPatternInterfaceError, COMError, OSError):
        raise RuntimeError("This control does not expose its toggle state.") from None

    desired = int(checked)
    if before == desired:
        return {"checked": checked, "verified": True}
    if before not in (0, 1):
        raise RuntimeError("This toggle has an indeterminate state. Read the window again.")

    # Another input can use the target only after a fresh reading.
    _observations.pop(observation["window_id"], None)
    try:
        toggle.Toggle()
        if toggle.CurrentToggleState == desired:
            return {"checked": checked, "verified": True}
    except (COMError, OSError):
        pass
    raise RuntimeError("The toggle outcome could not be verified. Read the window before trying again.")


@time_step("action")
def type_text(observation, node_id, text):
    """Replace the chosen field or document's text and check what was entered.

    Stop on an uncertain result instead of automatically typing the text again.
    """
    if not isinstance(text, str) or "\0" in text:
        raise ValueError("Give text without null characters to enter.")

    control = _get_control(observation, node_id)
    if control.element_info.control_type not in ("Edit", "Document", "ComboBox"):
        raise RuntimeError("Choose an editable field or document.")

    # Prefer setting the field directly. Use keyboard input if unsupported.
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

        # Before typing, check that this editor lets us read and verify its text.
        try:
            text_range = control.iface_text.DocumentRange
            readonly = text_range.GetAttributeValue(IUIA().ui_automation_client.UIA_IsReadOnlyAttributeId)

            if readonly is True or readonly == 1:
                raise RuntimeError("This document is read-only.")

            text_range.GetText(-1)  # Check that we can read the text back before typing.
        except NoPatternInterfaceError:
            raise RuntimeError("This control does not support verified text entry.") from None

    # Compare all line breaks in the same format.
    expected = text.replace("\r\n", "\n").replace("\r", "\n")
    _observations.pop(observation["window_id"], None)

    try:
        if value is not None:
            value.SetValue(text)  # Replace the field through Windows directly.
        else:
            focus_window(observation["window"])
            control.set_focus()  # Focus the exact control through Windows accessibility.

            # Both the app and this editor must have focus before we send keys.
            if win32gui.GetForegroundWindow() != observation["window"].handle or not control.has_keyboard_focus():
                raise RuntimeError("The selected editor did not receive keyboard focus.")

            # ^a means Ctrl+A: select the existing text so we replace it.
            control.type_keys("^a", pause=0, turn_off_numlock=False, set_foreground=False)

            if win32gui.GetForegroundWindow() != observation["window"].handle or not control.has_keyboard_focus():
                raise RuntimeError("Keyboard focus changed before typing.")

            # Escape shortcut symbols so text such as {ENTER} is typed literally.
            keys = "".join("{" + char + "}" if char in "+^%~(){}" else char for char in expected)
            # Empty replacement text means delete the current selection.
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

            sleep(0.05)  # Read again after 50 milliseconds; do not type again.

    except Exception as error:
        raise RuntimeError("Text entry could not be verified. Read the window and investigate before typing again.") from error

    return "Text entered and verified."


def find_app(executable):
    """Find an installed program by its filename, without running shell commands."""
    if not isinstance(executable, str) or not executable.lower().endswith(".exe") or any(
        char in executable for char in '\\/:"<>|&;%^\r\n'
    ):
        raise ValueError("Give just an installed program name, such as winword.exe.")

    # First search the program folders listed in PATH.
    path = which(executable)
    if path:
        return path

    # Office and other apps may be registered in Windows without being on PATH.
    for registry in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        # Check both 64-bit and 32-bit app registrations.
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

    # If normal focus did not work, ask Windows directly.
    if win32gui.GetForegroundWindow() != window.handle:
        try:
            win32gui.SetForegroundWindow(window.handle)
        except Exception:
            raise RuntimeError("Bring the selected app to the front, then try again.") from None

    if win32gui.GetForegroundWindow() != window.handle:
        raise RuntimeError("The selected app did not become the foreground window.")


@time_step("action")
def press_key(observation, keys):
    """Send a key or shortcut to this window, such as Enter or Ctrl+N."""
    if not isinstance(keys, list) or not keys or len(keys) > 4 or any(not isinstance(key, str) for key in keys):
        raise ValueError("Give a key list, such as ['CTRL', 'N'].")

    # Accept names such as ctrl and CTRL in the same way.
    keys = [key.upper() for key in keys]

    # Translate readable key names into pywinauto's keyboard syntax.
    modifiers = {"CTRL": "^", "ALT": "%", "SHIFT": "+"}
    named = {name: "{" + name + "}" for name in (
        "ENTER", "TAB", "ESC", "BACKSPACE", "DELETE", "SPACE", "UP", "DOWN", "LEFT", "RIGHT", "HOME", "END",
    )}

    base = keys[-1]  # The final key is the letter or named key to press.
    if any(key not in modifiers for key in keys[:-1]) or len(set(keys)) != len(keys):
        raise ValueError("Use modifiers first and one key last.")
    if base not in named and not (len(base) == 1 and base.isascii() and base.isalnum()):
        raise ValueError("That key is not supported yet.")

    # Do not send keys using an old window reading.
    if _observations.get(observation["window_id"]) is not observation:
        raise RuntimeError("Read the window again before sending keys.")
    window = observation["window"]
    if tuple(window.element_info.runtime_id or ()) != observation["window_id"] or not window.is_visible():
        raise RuntimeError("The observed window is no longer available.")

    _observations.pop(observation["window_id"], None)
    focus_window(window)

    # For example, ["CTRL", "N"] becomes ^n.
    sequence = "".join(modifiers[key] for key in keys[:-1]) + named.get(base, base.lower())
    window.type_keys(sequence, set_foreground=False, pause=0, turn_off_numlock=False)
    return "Keys sent. Read the window again to check the result."


def read_text(observation, node_id):
    """Read a chosen field again so completion uses its current text."""
    control = _get_control(observation, node_id)

    # Read a field value first; fall back to the document text interface.
    try:
        text = control.iface_value.CurrentValue
    except NoPatternInterfaceError:
        text = control.iface_text.DocumentRange.GetText(-1)

    return text.replace("\r\n", "\n").replace("\r", "\n")
