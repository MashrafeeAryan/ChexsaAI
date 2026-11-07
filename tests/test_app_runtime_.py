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
                self.assertEqual(app_runtime_.load_settings(), {**values, "VISION_MODEL": ""})

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


    def test_vision_model_is_separate(self):
        """Changing the vision model does not change the text model."""
        values = app_runtime_.validate_settings(
            {"LLM_MODEL": "text-fixture", "VISION_MODEL": "image-fixture"}
        )
        self.assertEqual(values["LLM_MODEL"], "text-fixture")
        self.assertEqual(values["VISION_MODEL"], "image-fixture")


class ChatStorageTests(unittest.TestCase):
    """Saved conversations survive restarts without storing automation objects."""

    def test_encrypted_chat_round_trip_and_delete(self):
        """Save, replace, and delete one chat without losing another conversation."""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chats.sqlite3"
            self.assertEqual(app_runtime_.load_chats(path), [])
            first = {
                "id": "first",
                "title": "Private example",
                "mode": "desktop",
                "messages": [{"speaker": "You", "text": "Private example task"}],
                "window": object(),
                "pending_send": {"id": "never-save"},
            }
            app_runtime_.save_chat(first, path)
            second = {**first, "id": "second", "title": "Another task", "mode": "visual"}
            app_runtime_.save_chat(second, path)
            first["title"] = "Renamed"
            app_runtime_.save_chat(first, path)
            chats = app_runtime_.load_chats(path)
            self.assertEqual(len(chats), 2)
            self.assertEqual(chats[0]["title"], "Renamed")
            self.assertNotIn("window", chats[0])
            self.assertNotIn("pending_send", chats[0])
            self.assertNotIn(b"Private example", path.read_bytes())
            app_runtime_.delete_chat("first", path)
            self.assertEqual(
                [chat["id"] for chat in app_runtime_.load_chats(path)], ["second"]
            )

    def test_broken_chat_is_not_silently_removed(self):
        """An unreadable record remains available for recovery instead of being overwritten."""
        import sqlite3
        from contextlib import closing

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chats.sqlite3"
            app_runtime_.load_chats(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.execute(
                    "INSERT INTO chats VALUES ('broken', 0, ?)", (b"invalid",)
                )
            with self.assertRaises(Exception):
                app_runtime_.load_chats(path)
            with closing(sqlite3.connect(path)) as connection, connection:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM chats").fetchone()[0], 1
                )
