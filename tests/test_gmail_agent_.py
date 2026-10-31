"""Check Gmail task flow without any model or Google account calls."""

import unittest
from unittest.mock import Mock, patch

import gmail_agent_


class GmailAgentTests(unittest.TestCase):
    """Keep drafts editable and sends dependent on an exact user-reviewed version."""

    def test_task_summary_uses_search_results(self):
        """A work summary searches and reads messages before answering."""
        actions = [
            {
                "tool": "search_mail",
                "arguments": {"query": "in:inbox", "page_token": ""},
            },
            {"tool": "read_mail", "arguments": {"message_id": "mail1", "offset": 0}},
            {
                "tool": "reply",
                "arguments": {
                    "text": "Report due Friday (mail1); reviewed this inbox page."
                },
            },
        ]
        with (
            patch.object(gmail_agent_, "get_gmail_action", side_effect=actions),
            patch.object(
                gmail_agent_,
                "search_mail",
                return_value={"messages": [{"id": "mail1"}]},
            ),
            patch.object(
                gmail_agent_, "read_mail", return_value={"body": "Report due Friday"}
            ),
        ):
            result = gmail_agent_.run_gmail_agent(
                "What work do I have?", {"service": Mock()}
            )
        self.assertIn("Friday", result)

    def test_unknown_id_does_not_reach_google(self):
        """Invented target IDs cannot read or edit an email."""
        action = {
            "tool": "read_mail",
            "arguments": {"message_id": "invented", "offset": 0},
        }
        with (
            patch.object(gmail_agent_, "get_gmail_action", return_value=action),
            patch.object(gmail_agent_, "read_mail") as read,
        ):
            with self.assertRaises(RuntimeError):
                gmail_agent_.run_gmail_agent("Read it", {"service": Mock()})
            read.assert_not_called()

    def test_review_then_confirmation(self):
        """The model can prepare a send; the direct confirmation performs it exactly once."""
        state = {"service": Mock(), "drafts": {"draft1"}}
        draft = {
            "draft_id": "draft1",
            "to": "a@example.com",
            "subject": "Hello",
            "body": "Hi",
        }
        action = {"tool": "review_send", "arguments": {"draft_id": "draft1"}}
        with (
            patch.object(gmail_agent_, "get_gmail_action", return_value=action),
            patch.object(gmail_agent_, "read_draft", return_value=draft),
            patch.object(
                gmail_agent_, "send_draft", return_value={"message_id": "sent1"}
            ) as send,
        ):
            preview = gmail_agent_.run_gmail_agent("Send the draft", state)
            self.assertIn("a@example.com", preview)
            send.assert_not_called()
            self.assertIn(
                "accepted", gmail_agent_.run_gmail_agent("confirm send", state)
            )
            self.assertIn("No reviewed", gmail_agent_.run_gmail_agent("/send", state))
            send.assert_called_once()

    def test_intervening_request_invalidates_review(self):
        """Asking for edits discards old send approval before any next operation."""
        state = {"service": Mock(), "pending_send": {"id": "draft1"}}
        with patch.object(
            gmail_agent_,
            "get_gmail_action",
            return_value={
                "tool": "reply",
                "arguments": {"text": "What should I change?"},
            },
        ):
            gmail_agent_.run_gmail_agent("Edit it", state)
        self.assertNotIn("pending_send", state)
