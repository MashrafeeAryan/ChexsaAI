"""Check app settings and cancellation without any model requests."""

import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

import app_runtime_


class AppSettingsTests(unittest.TestCase):
    """Settings survive installation changes and keep API keys out of plain text."""

    def test_encrypted_settings_round_trip(self):
        """Windows can recover saved values, but the file does not contain the key."""
        values = {
            "LLM_API_KEY": "example-test-key",
            "LLM_BASE_URL": "https://example.com/v1",
            "LLM_MODEL": "example-model",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.dpapi"
            with patch.object(app_runtime_, "settings_path", return_value=path):
                self.assertEqual(app_runtime_.load_settings()["LLM_MODEL"], "")
                app_runtime_.save_settings(values)
                self.assertNotIn(b"example-test-key", path.read_bytes())
                self.assertEqual(app_runtime_.load_settings(), values)

    def test_settings_reject_bad_addresses(self):
        """A mistyped address or an unknown setting fails before a model call."""
        for values in ({"LLM_BASE_URL": "file:///private"}, {"other": "value"}):
            with self.assertRaises(ValueError):
                app_runtime_.validate_settings(values)

    def test_cancel_only_when_requested(self):
        """CLI state remains valid and a pressed Stop button raises a clear interruption."""
        app_runtime_.check_cancelled({})
        event = Event()
        app_runtime_.check_cancelled({"_cancel": event})
        event.set()
        with self.assertRaises(InterruptedError):
            app_runtime_.check_cancelled({"_cancel": event})

    def test_interface_preferences_round_trip(self):
        """Mascots and display names save locally without becoming model environment keys."""
        values = {"DISPLAY_NAME": "Example User", "MASCOT": "Fluffy"}
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                app_runtime_,
                "settings_path",
                return_value=Path(directory) / "settings.dpapi",
            ):
                app_runtime_.save_settings(values)
                saved = app_runtime_.load_settings()
        self.assertEqual(saved["MASCOT"], "Fluffy")
        self.assertEqual(saved["DISPLAY_NAME"], "Example User")
        self.assertNotIn("MASCOT", app_runtime_.SETTING_KEYS)
        with self.assertRaises(ValueError):
            app_runtime_.validate_settings({"MASCOT": "Unknown"})

    def test_old_fox_name_migrates(self):
        """An existing Foxxy preference opens as Foxy instead of breaking settings."""
        values = app_runtime_.validate_settings({"MASCOT": "Foxxy"})
        self.assertEqual(values["MASCOT"], "Foxy")
