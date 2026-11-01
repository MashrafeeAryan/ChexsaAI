"""Exercise a real hidden Tk window with fake task handlers."""

from threading import Event
from time import monotonic, sleep
import tkinter as tk
import unittest
import gc
from unittest.mock import patch

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

    def tearDown(self):
        """Release old Tk reference cycles on the UI thread before another worker starts."""
        gc.collect()

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
            context["close"]()
            pump_until(root, lambda: context.get("closed", False))
            context["worker"].join(timeout=3)
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
            context["close"]()
            pump_until(root, lambda: context.get("closed", False))
            context["worker"].join(timeout=3)

    def test_microphone_fills_input_without_execution(self):
        """Recorded text goes into the editor for review; it does not auto-run a task."""
        calls = []
        root = tk.Tk()
        root.withdraw()
        context = build_app(
            root,
            handlers={"desktop": lambda *args: calls.append(args)},
            initial_settings={},
        )
        try:
            pump_until(root, lambda: context["ready"])
            with patch("app_.record_message", return_value="open a website"):
                context["start_audio"]("record")
                pump_until(root, lambda: not context["audio_busy"])
            self.assertIn("open a website", context["entry"].get("1.0", "end"))
            self.assertEqual(calls, [])
        finally:
            context["close"]()
            pump_until(root, lambda: context.get("closed", False))
            context["worker"].join(timeout=3)

    def test_controls_fit_small_window(self):
        """The message editor and task buttons remain visible at the minimum size."""
        root = tk.Tk()
        context = build_app(
            root, handlers={"desktop": lambda *args: "Done"}, initial_settings={}
        )
        try:
            root.geometry("720x560")
            pump_until(root, lambda: context["ready"])
            root.update()
            editor = context["entry"]
            self.assertLess(
                editor.winfo_rooty() + editor.winfo_height(),
                root.winfo_rooty() + root.winfo_height(),
            )
            buttons = []

            def visit(widget):
                for child in widget.winfo_children():
                    if child.winfo_class() == "TButton":
                        buttons.append(child)
                    visit(child)

            visit(root)
            for button in buttons:
                self.assertTrue(button.winfo_ismapped())
                self.assertLessEqual(
                    button.winfo_rooty() + button.winfo_height(),
                    root.winfo_rooty() + root.winfo_height(),
                )
        finally:
            context["close"]()
            pump_until(root, lambda: context.get("closed", False))
            context["worker"].join(timeout=3)
