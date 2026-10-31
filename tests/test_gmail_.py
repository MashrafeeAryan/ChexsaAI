"""Test mailbox reads with fake Gmail responses, never a real account."""

import base64
import unittest
from unittest.mock import Mock
from unittest.mock import patch
import tempfile
from pathlib import Path

import gmail_


def message(text="Please send the report on Friday."):
    """Make one small API message that tests can read and modify."""
    return {
        "id": "mail1", "threadId": "thread1",
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": "Subject", "value": "Report"}, {"name": "From", "value": "a@example.com"}],
            "body": {"data": base64.urlsafe_b64encode(text.encode()).decode()},
        },
    }


class GmailReadTests(unittest.TestCase):
    """Search stays bounded and full bodies remain available by explicit reading."""

    def test_search_returns_page_without_body(self):
        """Search gives small summaries and a cursor instead of the whole inbox."""
        service = Mock()
        service.users().messages().list().execute.return_value = {"messages": [{"id": "mail1"}], "nextPageToken": "page2"}
        service.users().messages().get().execute.return_value = message()
        result = gmail_.search_mail(service)
        self.assertEqual(result["next_page"], "page2")
        self.assertNotIn("body", result["messages"][0])
        service.users().messages().get().execute.assert_called_once_with(num_retries=0)

    def test_body_continuation(self):
        """Long emails have a continuation offset rather than silently missing text."""
        service = Mock()
        service.users().messages().get().execute.return_value = message("x" * 6000 + "deadline")
        self.assertEqual(gmail_.read_mail(service, "mail1")["next_offset"], 6000)
        self.assertEqual(gmail_.read_mail(service, "mail1", 6000)["body"], "deadline")

    def test_alternative_and_attachment(self):
        """Prefer one plain-text copy and skip attachments and HTML scripts."""
        plain = message("hello")["payload"]
        html = message("<p>hello</p><script>bad()</script>")["payload"]
        html["mimeType"] = "text/html"
        self.assertEqual(gmail_._body({"mimeType": "multipart/alternative", "parts": [html, plain]}), "hello")
        self.assertNotIn("bad", gmail_._body(html))
        plain["filename"] = "secret.txt"
        self.assertEqual(gmail_._body(plain), "")

    def test_errors_hide_private_server_details(self):
        """API failures do not leak message contents or authentication errors."""
        request = Mock()
        request.execute.side_effect = OSError("private token")
        with self.assertRaisesRegex(RuntimeError, "Gmail could not"):
            gmail_._execute(request)


class GmailWriteTests(unittest.TestCase):
    """Verify drafts and prevent changed or uncertain messages from being sent twice."""

    def setUp(self):
        self.service = Mock()
        self.draft = {"draft_id": "draft1", "id": "mail1", "to": "b@example.com", "subject": "Hello", "body": "Hi\n"}

    def test_create_verifies_saved_contents(self):
        """A successful draft save requires reading the same recipient, subject, and body."""
        self.service.users().drafts().create().execute.return_value = {"id": "draft1"}
        with patch.object(gmail_, "read_draft", return_value=self.draft):
            self.assertEqual(gmail_.save_draft(self.service, "b@example.com", "Hello", "Hi"), self.draft)

    def test_header_injection_is_rejected(self):
        """A newline cannot add hidden recipients to an email header."""
        with self.assertRaises(ValueError):
            gmail_.save_draft(self.service, "b@example.com\nBcc: c@example.com", "Hi", "Hello")
        self.service.users.assert_not_called()

    def test_reply_uses_original_headers(self):
        """Replies use the real sender and original thread, not an invented recipient."""
        original = message()
        original["payload"]["headers"].append({"name": "Message-ID", "value": "<original@example.com>"})
        self.service.users().messages().get().execute.return_value = original
        self.service.users().drafts().create().execute.return_value = {"id": "draft1"}
        reply = dict(self.draft, to="a@example.com", subject="Re: Report")
        with patch.object(gmail_, "read_draft", return_value=reply):
            gmail_.save_draft(self.service, "invented@example.com", "Wrong", "Hi", reply_to="mail1")
        content = self.service.users().drafts().create.call_args.kwargs["body"]["message"]
        raw = base64.urlsafe_b64decode(content["raw"]).decode()
        self.assertIn("in-reply-to: <original@example.com>", raw.lower())
        self.assertEqual(content["threadId"], "thread1")

    def test_changed_draft_is_not_sent(self):
        """An edit after review requires a fresh review."""
        with patch.object(gmail_, "read_draft", return_value=self.draft):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                gmail_.send_draft(self.service, "draft1", "old-version")
        self.service.users.assert_not_called()

    def test_uncertain_send_is_not_repeated_after_restart(self):
        """The persistent intent record prevents a second submission after a timeout."""
        self.service.users().drafts().send().execute.side_effect = TimeoutError()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(gmail_, "account_folder", return_value=Path(directory)), patch.object(gmail_, "read_draft", return_value=self.draft):
                fingerprint = gmail_.draft_fingerprint(self.draft)
                with self.assertRaisesRegex(RuntimeError, "uncertain"):
                    gmail_.send_draft(self.service, "draft1", fingerprint)
                with self.assertRaisesRegex(RuntimeError, "submission record"):
                    gmail_.send_draft(self.service, "draft1", fingerprint)
        self.service.users().drafts().send().execute.assert_called_once_with(num_retries=0)
