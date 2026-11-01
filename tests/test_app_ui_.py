"""Exercise a real hidden Tk window with fake task handlers."""

from threading import Event
from time import monotonic, sleep
import tkinter as tk
import unittest

from app_ import build_app
from app_runtime_ import check_cancelled


def pump_until(root, condition):
    """Let Tk process events while waiting up to five seconds for a test result."""
    deadline = monotonic() + 5
    while not condition():
        if monotonic() > deadline:
            raise AssertionError("The app did not process its result in time.")
        root.update()
        sleep(0.01)


class AppWindowTests(unittest.TestCase):
    """Use real widgets without opening personal apps or calling a provider."""

    def test_chat_and_clean_shutdown(self):
        """Sending text displays its fake result and leaves the window responsive."""
        root = tk.Tk()
        root.withdraw()
        context = build_app(
            root,
            handlers={"desktop": lambda text, state: "Verified: " + text},
            initial_settings={},
        )
        try:
            pump_until(root, lambda: context["ready"])
            context["entry"].insert("1.0", "Example task")
            context["submit"]()
            pump_until(root, lambda: not context["busy"])
            self.assertIn("Verified: Example task", context["chat"].get("1.0", "end"))
        finally:
            context["shutdown"].set()
            context["worker"].join(timeout=3)
            root.destroy()
        self.assertFalse(context["worker"].is_alive())

    def test_stop_and_next_request(self):
        """Stop interrupts a cooperative task and the next request still works."""
        started = Event()

        def handler(text, state):
            if text == "wait":
                started.set()
                state["_cancel"].wait(timeout=3)
                check_cancelled(state)
            return "Done"

        root = tk.Tk()
        root.withdraw()
        context = build_app(root, handlers={"desktop": handler}, initial_settings={})
        try:
            pump_until(root, lambda: context["ready"])
            context["submit"]("wait")
            pump_until(root, started.is_set)
            context["stop"]()
            pump_until(root, lambda: not context["busy"])
            self.assertEqual(context["status"].get(), "Stopped")
            context["submit"]("next")
            pump_until(root, lambda: not context["busy"])
            self.assertIn("Done", context["chat"].get("1.0", "end"))
        finally:
            context["shutdown"].set()
            context["worker"].join(timeout=3)
            root.destroy()
