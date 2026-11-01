"""Keep desktop-app settings and background work together, away from the window."""

import json
import os
from pathlib import Path

SETTING_KEYS = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")


def settings_path():
    """Save settings under this Windows user, so an app update cannot replace them."""
    return (
        Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Chexsa" / "settings.dpapi"
    )


def validate_settings(settings):
    """Check model settings before saving them. Empty fields use the existing .env.

    Input: {'LLM_MODEL': 'example-model'}. Output: the three allowed text fields.
    """
    from urllib.parse import urlsplit

    if not isinstance(settings, dict) or set(settings) - set(SETTING_KEYS):
        raise ValueError("Use only API key, API address, and model settings.")

    result = {}
    for key in SETTING_KEYS:
        value = settings.get(key, "")
        if not isinstance(value, str) or "\n" in value or "\r" in value:
            raise ValueError("Each setting must be a single line of text.")
        result[key] = value.strip()

    address = result["LLM_BASE_URL"]
    if address:
        parsed = urlsplit(address)
        if (
            parsed.scheme not in ("https", "http")
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError(
                "Give an HTTP or HTTPS API address without embedded credentials."
            )
    return result


def load_settings():
    """Read this user's encrypted settings. No saved file means use .env as before."""
    path = settings_path()
    if not path.exists():
        return dict.fromkeys(SETTING_KEYS, "")

    import win32crypt

    try:
        raw = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 0)[1]
        return validate_settings(json.loads(raw))
    except Exception:
        raise RuntimeError(
            "Saved settings could not be read. Open Settings and save them again."
        ) from None


def save_settings(settings):
    """Encrypt settings for this Windows user, then replace the saved file atomically."""
    import win32crypt

    values = validate_settings(settings)
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    encrypted = win32crypt.CryptProtectData(
        json.dumps(values).encode(),
        "Chexsa settings",
        None,
        None,
        None,
        0,
    )
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(encrypted)
    temporary.replace(path)
    return values


def check_cancelled(state):
    """Stop at a safe boundary when the app's Stop button has been pressed.

    CLI dictionaries have no cancel event, so their existing behavior stays the same.
    """
    event = state.get("_cancel")
    if event is not None and event.is_set():
        raise InterruptedError(
            "Task stopped. Earlier actions may already have completed; check their results before repeating them."
        )
