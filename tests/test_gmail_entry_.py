"""Check that terminal and voice reach the same Gmail engine."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import cli_
import voice_


class GmailEntryTests(unittest.TestCase):
    """Gmail is an explicit third mode and starts without an unsolicited email action."""

    def test_cli_gmail(self):
        """A terminal message reaches Gmail; simply starting the chat does not sign in."""
        with patch("builtins.input", side_effect=["What work is due?", "quit"]), patch("builtins.print"), patch.object(cli_, "run_gmail_agent", return_value="One task") as agent:
            cli_.main("gmail")
        agent.assert_called_once_with("What work is due?", {})

    def test_voice_gmail(self):
        """A spoken Gmail command uses the existing wake phrase and voice reply path."""
        fake = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
        with patch.dict(sys.modules, {"speech_recognition": fake}), patch.object(voice_, "listen", side_effect=["hey chexsa summarize my emails", "hey chexsa quit"]), patch.object(voice_, "speak"), patch.object(voice_, "acknowledge"), patch("builtins.print"), patch.object(voice_, "run_gmail_agent", return_value="Two tasks") as agent:
            voice_.main("gmail")
        agent.assert_called_once_with("summarize my emails", {})
