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
            self.assertEqual(
                gmail_auth_.account_folder(), Path("C:/ExampleUser/Chexsa/gmail")
            )

    def test_disconnect(self):
        """Disconnect removes tokens and also works when already disconnected."""
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            (folder / "account.dpapi").write_bytes(b"encrypted-example")
            with patch.object(gmail_auth_, "account_folder", return_value=folder):
                gmail_auth_.disconnect_gmail()
                gmail_auth_.disconnect_gmail()
            self.assertFalse((folder / "account.dpapi").exists())


class GmailSignInTests(unittest.TestCase):
    """Test Google login wiring and real Windows token encryption without network calls."""

    def test_sign_in_encrypts_and_reuses_access(self):
        """Google opens once; a second connection reuses the encrypted local token."""
        import json
        from datetime import datetime, timedelta, timezone
        import win32crypt
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow

        credentials = Credentials(
            token="example-token-not-a-secret",
            refresh_token="example-refresh",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="example-client",
            client_secret="example-client-secret",
            scopes=gmail_auth_.SCOPES,
            expiry=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1),
        )
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            client_file = folder / "client.json"
            client_file.write_text(
                json.dumps(
                    {
                        "installed": {
                            "client_id": "example-client",
                            "client_secret": "example-client-secret",
                            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                            "token_uri": "https://oauth2.googleapis.com/token",
                            "redirect_uris": ["http://localhost"],
                        }
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch.object(gmail_auth_, "account_folder", return_value=folder),
                patch.object(
                    InstalledAppFlow, "run_local_server", return_value=credentials
                ) as login,
                patch("googleapiclient.discovery.build", return_value="service"),
                patch.object(
                    Credentials,
                    "refresh",
                    side_effect=AssertionError("No network refresh in this test"),
                ),
            ):
                self.assertEqual(gmail_auth_.connect_gmail(str(client_file)), "service")
                encrypted = (folder / "account.dpapi").read_bytes()
                self.assertNotIn(b"example-token", encrypted)
                decrypted = win32crypt.CryptUnprotectData(
                    encrypted, None, None, None, 0
                )[1]
                self.assertEqual(
                    json.loads(decrypted)["token"], "example-token-not-a-secret"
                )
                self.assertEqual(gmail_auth_.connect_gmail(), "service")
                login.assert_called_once()
                self.assertEqual(login.call_args.kwargs["host"], "127.0.0.1")
                self.assertEqual(login.call_args.kwargs["port"], 0)
