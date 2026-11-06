"""Check saved chat behavior with temporary files, real Tk, and fake engines."""

import gc
from pathlib import Path
import tempfile
import tkinter as tk
import unittest

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
