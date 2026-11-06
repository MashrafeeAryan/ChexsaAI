"""Check saved chat behavior with temporary files, real Tk, and fake engines."""

import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from app_ import build_app
from app_runtime_ import load_chats
from test_app_ui_ import pump_until


class SavedChatTests(unittest.TestCase):
    """No personal apps, saved accounts, or model APIs are used here."""

    def setUp(self):
        """Give each test its own local chat store and hidden window."""
        self.directory = tempfile.TemporaryDirectory()
        self.path = Path(self.directory.name) / "chats.sqlite3"
        self.windows = []
        self.calls = []

    def open_window(self):
        """Start a real app whose only engine returns a harmless fixture reply."""
        root = tk.Tk()
        root.withdraw()

        def handler(text, state):
            self.calls.append(text)
            return "Fixture result: " + text

        context = build_app(
            root,
            handlers={"desktop": handler},
            initial_settings={},
            history_path=self.path,
        )
        self.windows.append(context)
        pump_until(root, lambda: context["ready"])
        return context

    def close_window(self, context):
        """Wait for worker cleanup before disposing of its Tk window."""
        context["close"]()
        pump_until(context["root"], lambda: context.get("closed", False))
        context["worker"].join(timeout=3)
        self.windows.remove(context)

    def tearDown(self):
        """Close every fake session even if a check failed."""
        for context in list(self.windows):
            self.close_window(context)
        gc.collect()
        self.directory.cleanup()

    def test_messages_are_saved_before_restart(self):
        """Both sides of a conversation reach the encrypted store without executing again."""
        context = self.open_window()
        context["submit"]("Example task")
        pump_until(context["root"], lambda: not context["busy"])
        saved = load_chats(self.path)
        self.assertEqual(len(saved), 1)
        self.assertEqual(
            [message["text"] for message in saved[0]["messages"]],
            ["Example task", "Fixture result: Example task"],
        )
        self.close_window(context)
        self.assertEqual(len(load_chats(self.path)), 1)
        self.assertEqual(self.calls, ["Example task"])

    def test_reopen_after_restart_does_not_replay_actions(self):
        """Sidebar history survives a restart, but old tools and send approvals do not run."""
        context = self.open_window()
        context["submit"]("First task")
        pump_until(context["root"], lambda: not context["busy"])
        saved_id = context["active_chat"]
        self.close_window(context)
        context = self.open_window()
        self.assertEqual(context["history_box"].size(), 1)
        context["open_chat"](saved_id)
        pump_until(context["root"], lambda: not context["busy"])
        self.assertIn("Fixture result: First task", context["chat"].get("1.0", "end"))
        self.assertEqual(self.calls, ["First task"])
        self.assertFalse(context["review"])
        context["new_chat"]()
        pump_until(context["root"], lambda: not context["busy"])
        context["submit"]("Second task")
        pump_until(context["root"], lambda: not context["busy"])
        self.assertEqual(len(load_chats(self.path)), 2)
        context["open_chat"](saved_id)
        pump_until(context["root"], lambda: not context["busy"])
        self.assertNotIn("Second task", context["chat"].get("1.0", "end"))

    def test_rename_and_delete_only_the_selected_chat(self):
        """Names persist; cancelling deletion keeps the chat and confirming removes only it."""
        context = self.open_window()
        context["submit"]("First task")
        pump_until(context["root"], lambda: not context["busy"])
        context["rename_chat"]("My example")
        first_id = context["active_chat"]
        self.assertEqual(load_chats(self.path)[0]["title"], "My example")
        context["new_chat"]()
        pump_until(context["root"], lambda: not context["busy"])
        context["submit"]("Second task")
        pump_until(context["root"], lambda: not context["busy"])
        context["open_chat"](first_id)
        pump_until(context["root"], lambda: not context["busy"])
        with patch("app_.messagebox.askyesno", return_value=False):
            context["remove_chat"]()
        self.assertEqual(len(load_chats(self.path)), 2)
        with patch("app_.messagebox.askyesno", return_value=True):
            context["remove_chat"]()
        pump_until(context["root"], lambda: not context["busy"])
        self.assertIsNone(context["active_chat"])
        self.assertEqual(
            [item["title"] for item in load_chats(self.path)], ["Second task"]
        )
        self.assertEqual(self.calls, ["First task", "Second task"])

    def test_failed_request_shows_error_and_keeps_its_message(self):
        """An error is displayed and saved; the app still accepts another request."""
        context = self.open_window()
        context["events"].put(
            {"kind": "error", "mode": "desktop", "text": "Fixture failure"}
        )
        pump_until(context["root"], lambda: context["phase"] == "error")
        self.assertIn(
            "Fixture failure", load_chats(self.path)[0]["messages"][-1]["text"]
        )
        context["submit"]("Try a different task")
        pump_until(context["root"], lambda: not context["busy"])
        self.assertEqual(context["phase"], "finished")
