"""Open Windows apps for the new desktop workflow."""

from pathlib import Path
import shlex  # Separates a program path from any startup options.
from time import monotonic, sleep

from pywinauto import Application, Desktop  # Open apps and find their windows.
from pywinauto.application import ProcessNotFoundError, process_module


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
