"""Check Gmail account handling without signing in to a real account."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gmail_auth_


class GmailAccountTests(unittest.TestCase):
    """Keep tokens outside Git and allow removing local account access."""

    def test_account_location(self):
        """Account files belong to the Windows user, not the checkout."""
        with patch.dict("os.environ", {"LOCALAPPDATA": "C:/ExampleUser"}):
            self.assertEqual(gmail_auth_.account_folder(), Path("C:/ExampleUser/Chexsa/gmail"))

    def test_disconnect(self):
        """Disconnect removes tokens and also works when already disconnected."""
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "account.dpapi").write_bytes(b"encrypted-example")
            with patch.object(gmail_auth_, "account_folder", return_value=folder):
                gmail_auth_.disconnect_gmail()
                gmail_auth_.disconnect_gmail()
            self.assertFalse((folder / "account.dpapi").exists())
