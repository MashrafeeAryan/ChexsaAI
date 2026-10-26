"""Open Windows apps and read their visible controls."""

import json  # Keeps names readable when they contain quotes or line breaks.
from pathlib import Path
import shlex  # Separates a program path from any startup options.
from time import monotonic, sleep

from pywinauto import Application, Desktop  # Open apps and find their windows.
from pywinauto.application import ProcessNotFoundError, process_module
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


def read_window(window):
    """Describe the visible controls inside this window without changing anything.

    Keep the real controls locally so later actions can use the exact same objects.
    """
    if not window.is_visible():
        raise RuntimeError("This window is closed or hidden. Choose a visible window.")

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
    return {"title": title, "elements": "\n".join(lines), "controls": controls,
            "unavailable_controls": unavailable}
