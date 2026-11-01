"""A model response arriving after Stop must not execute its proposed action."""

import unittest
from threading import Event
from unittest.mock import Mock, patch

import agent_
import desktop_agent_
from plugins.gmail import gmail_agent_


class EngineCancellationTests(unittest.TestCase):
    """Check the real engine boundary between a model reply and a tool call."""

    def test_browser_stop_during_reply(self):
        """A delayed navigate decision cannot launch Chrome after cancellation."""
        stopped = Event()

        def reply(*args):
            stopped.set()
            return {"action": "navigate", "url": "https://example.com"}

        with (
            patch.object(agent_, "get_reply", side_effect=reply),
            patch.object(agent_, "open_browser") as launch,
        ):
            with self.assertRaises(InterruptedError):
                agent_.run_agent("Open a website", {"_cancel": stopped})
            launch.assert_not_called()

    def test_desktop_stop_during_reply(self):
        """A cancelled model decision cannot create a file."""
        stopped = Event()

        def reply(*args):
            stopped.set()
            return {
                "tool": "write_file",
                "arguments": {"path": "test.txt", "content": "hello", "done": True},
            }

        with (
            patch.object(desktop_agent_, "get_desktop_action", side_effect=reply),
            patch.object(desktop_agent_, "write_file") as write,
        ):
            with self.assertRaises(InterruptedError):
                desktop_agent_.run_desktop_agent("Create a file", {"_cancel": stopped})
            write.assert_not_called()

    def test_gmail_stop_during_reply(self):
        """A cancelled mailbox task does not fetch the proposed message."""
        stopped = Event()

        def reply(*args):
            stopped.set()
            return {
                "tool": "read_mail",
                "arguments": {"message_id": "mail1", "offset": 0},
            }

        with (
            patch.object(gmail_agent_, "get_gmail_action", side_effect=reply),
            patch.object(gmail_agent_, "read_mail") as read,
        ):
            with self.assertRaises(InterruptedError):
                gmail_agent_.run_gmail_agent(
                    "Read it", {"service": Mock(), "_cancel": stopped}
                )
            read.assert_not_called()
