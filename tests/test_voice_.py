"""Check standalone speech without playing sound or using a microphone."""

import unittest
from unittest.mock import patch

import voice_


# Speech uses Windows directly and waits for the spoken message to finish.
def test_windows_speech():
    with patch("win32com.client.Dispatch") as speaker:
        voice_.speak(voice_.GREETING)
        speaker.assert_called_once_with("SAPI.SpVoice")
        speaker.return_value.Speak.assert_called_once_with(voice_.GREETING)


# Acknowledgments come from fixed phrases, not an API request.
def test_acknowledgment():
    with patch.object(voice_, "choice", return_value="On it."), patch.object(voice_, "speak") as speak:
        assert voice_.acknowledge() == "On it."
        speak.assert_called_once_with("On it.")


# Run these plain test functions without introducing application classes.
def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_windows_speech, test_acknowledgment,
    ))
