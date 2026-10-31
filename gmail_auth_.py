"""Connect a Gmail account through Google's normal sign-in page."""

import json
import os
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
]


def account_folder():
    """Keep account files outside the repository, under this Windows user."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Chexsa" / "gmail"


def choose_credentials():
    """Ask for Google's Desktop app JSON file; cancel leaves the account unchanged."""
    from tkinter import Tk, filedialog

    root = Tk()
    root.withdraw()
    try:
        return filedialog.askopenfilename(
            title="Choose your Google Desktop app OAuth credentials",
            filetypes=[("Google credentials", "*.json")],
        )
    finally:
        root.destroy()


def connect_gmail(client_file=None):
    """Open Google sign-in when needed and return an authorized Gmail connection.

    Input: a Desktop app credentials path, or None to reuse saved access.
    Output: Google's Gmail API service; account tokens never go to the AI.
    """
    try:
        import httplib2
        import win32crypt
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_httplib2 import AuthorizedHttp
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError(
            'Install Gmail support: python -m pip install -e ".[gmail]"'
        ) from None

    folder = account_folder()
    token_path = folder / "account.dpapi"
    credentials = None

    # Windows encrypts the saved token for this user. It is not a repo file.
    if token_path.exists() and client_file is None:
        try:
            data = win32crypt.CryptUnprotectData(
                token_path.read_bytes(), None, None, None, 0
            )[1]
            credentials = Credentials.from_authorized_user_info(
                json.loads(data), SCOPES
            )
            if not credentials.has_scopes(SCOPES):
                credentials = None
            elif credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
        except Exception:
            raise RuntimeError(
                "Saved Gmail access could not be refreshed. Use /connect to sign in again."
            ) from None

    if credentials is None or not credentials.valid:
        selected = client_file or os.getenv("GMAIL_CLIENT_FILE") or choose_credentials()
        if not selected:
            raise RuntimeError(
                "Gmail sign-in cancelled. See the Gmail setup in README.md."
            )

        try:
            config = json.loads(Path(selected).read_text(encoding="utf-8-sig"))
            if "installed" not in config:
                raise ValueError("Use Desktop app credentials.")
            flow = InstalledAppFlow.from_client_config(
                config, SCOPES, autogenerate_code_verifier=True
            )
            # A temporary loopback port receives Google's reply, not your password.
            credentials = flow.run_local_server(
                host="127.0.0.1",
                port=0,
                timeout_seconds=180,
                access_type="offline",
                prompt="consent select_account",
                success_message="Gmail connected. You can close this tab and return to Chexsa.",
            )
        except Exception:
            raise RuntimeError(
                "Google sign-in failed. Check Desktop app credentials, test users, and Gmail API access."
            ) from None

    folder.mkdir(parents=True, exist_ok=True)
    encrypted = win32crypt.CryptProtectData(
        credentials.to_json().encode(), "Chexsa Gmail", None, None, None, 0
    )
    temporary = token_path.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(token_path)

    # Bound API waiting and disable retries when executing individual requests.
    http = AuthorizedHttp(credentials, http=httplib2.Http(timeout=20))
    return build("gmail", "v1", http=http, cache_discovery=False)


def disconnect_gmail():
    """Forget local login tokens. Google account permissions can also be revoked at Google."""
    (account_folder() / "account.dpapi").unlink(missing_ok=True)
