"""Test mailbox reads with fake Gmail responses, never a real account."""

import base64
import unittest
from unittest.mock import Mock

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
