"""Test microphone parsing and speech cancellation without recording or playing audio."""

import sys
from threading import Event
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch

import app_runtime_
import voice_


class AppAudioTests(unittest.TestCase):
    """Speech input is reviewable and Windows playback can be stopped."""

    def test_recording_removes_optional_wake_phrase(self):
        """One recording returns plain command text, without running the agent."""
        speech = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
        with (
            patch.dict(sys.modules, {"speech_recognition": speech}),
            patch.object(voice_, "listen", return_value="Hey Chexsa, open a website"),
        ):
            self.assertEqual(app_runtime_.record_message(Event()), "open a website")

    def test_stopped_recording_is_discarded(self):
        """An utterance arriving after Stop must not become a new request."""
        speech = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
        stop = Event()

        def recording(*args):
            stop.set()
            return "send the email"

        with (
            patch.dict(sys.modules, {"speech_recognition": speech}),
            patch.object(voice_, "listen", side_effect=recording),
        ):
            with self.assertRaises(InterruptedError):
                app_runtime_.record_message(stop)

    def test_speech_stop_purges_playback(self):
        """The Stop flag clears Windows speech instead of waiting for a long reply."""
        stop = Event()
        speaker = Mock()

        def wait(_timeout):
            """Stop while the first speech item is still queued."""
            stop.set()
            return False

        speaker.WaitUntilDone.side_effect = wait
        with patch("win32com.client.Dispatch", return_value=speaker):
            voice_.speak("Example reply", cancel=stop)
        self.assertEqual(speaker.Speak.call_args.args, ("", 3))


    def test_stopped_speech_does_not_start(self):
        """An already cancelled request must stay silent."""
        stop = Event()
        stop.set()
        with patch("win32com.client.Dispatch") as dispatch:
            voice_.speak("Example reply", cancel=stop)
        dispatch.assert_not_called()
