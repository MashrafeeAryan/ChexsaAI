"""Check voice and agent wiring without playing sound or using a microphone."""

import unittest
from unittest.mock import MagicMock, Mock, patch
from types import SimpleNamespace
import sys

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


# Wake matching accepts punctuation and combined requests, but ignores other speech.
def test_wake_phrase():
    assert voice_.get_request("Hey Chexsa!") == ""
    assert voice_.get_request("HEY, CHEXSA open Word") == "open Word"
    assert voice_.get_request("Hey Chexsa, open YouTube.") == "open YouTube."
    for text in ("", "open Word", "hey chexsaurus", "they said hey chexsa"):
        assert voice_.get_request(text) is None


# Exercise wake, greeting, follow-up, acknowledgment, and exit without using audio.
def test_conversation():
    fake = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
    with patch.dict(sys.modules, {"speech_recognition": fake}), \
         patch.object(voice_, "listen", side_effect=["background words", "Hey Chexsa", "open Word", "Hey Chexsa quit."]), \
         patch.object(voice_, "speak") as speak, patch.object(voice_, "acknowledge") as acknowledge, \
         patch("builtins.print") as output, \
         patch.object(voice_, "run_desktop_agent", return_value="Word opened") as agent:
        voice_.main()
        assert speak.call_args_list[0].args == (voice_.GREETING,)
        acknowledge.assert_called_once()
        agent.assert_called_once_with("open Word", {})
        speak.assert_any_call("Word opened")


# Combined requests need no second recording; silence must never trigger an action.
def test_combined_request_and_silence():
    fake = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
    with patch.dict(sys.modules, {"speech_recognition": fake}), \
         patch.object(voice_, "listen", side_effect=["hey chexsa", "", "hey chexsa open YouTube", "hey chexsa stop"]), \
         patch.object(voice_, "speak") as speak, patch.object(voice_, "acknowledge") as acknowledge, \
         patch("builtins.print") as output, \
         patch.object(voice_, "run_agent", return_value="YouTube opened") as agent:
        voice_.main("browser")
        acknowledge.assert_called_once()
        agent.assert_called_once_with("open YouTube", {})
        speak.assert_any_call("YouTube opened")
        assert any("didn't catch" in call.args[0] for call in speak.call_args_list)


# Unclear recordings are ignored; transcription failures stop without retrying.
def test_transcription_errors():
    fake = SimpleNamespace(WaitTimeoutError=TimeoutError, UnknownValueError=ValueError, RequestError=ConnectionError)
    for error in (TimeoutError(), ValueError(), ConnectionError()):
        recognizer, microphone = Mock(), MagicMock()
        recognizer.recognize_google.side_effect = error
        with patch.dict(sys.modules, {"speech_recognition": fake}):
            if isinstance(error, ConnectionError):
                with unittest.TestCase().assertRaisesRegex(RuntimeError, "unavailable"):
                    voice_.listen(recognizer, microphone)
            else:
                assert voice_.listen(recognizer, microphone) == ""
        recognizer.recognize_google.assert_called_once()
        microphone.__exit__.assert_called_once()


# Failures are spoken without retrying; later requests reuse state and exit disconnects.
def test_agent_error_and_cleanup():
    fake = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
    connection = Mock()
    states = []
    def run(request, state):
        states.append(state)
        state["playwright"] = connection
        if request == "click Send":
            raise RuntimeError("Click result uncertain")
        return "Page read"
    with patch.dict(sys.modules, {"speech_recognition": fake}), \
         patch.object(voice_, "listen", side_effect=["hey chexsa click Send", "hey chexsa read page", "hey chexsa stop"]), \
         patch.object(voice_, "speak") as speak, patch.object(voice_, "acknowledge"), \
         patch.object(voice_, "run_agent", side_effect=run) as agent, \
         patch.object(voice_, "run_desktop_agent") as desktop, \
         patch.object(voice_, "close_browser") as close, patch("builtins.print"):
        voice_.main("browser")
        assert agent.call_count == 2
        assert states[0] is states[1]
        desktop.assert_not_called()
        close.assert_called_once_with(connection)
        speak.assert_any_call("I couldn't finish that request. Check the terminal for details.")
        speak.assert_any_call("Page read")


# Starting or stopping voice must not call an agent or open an app by itself.
def test_no_task_on_startup_or_invalid_mode():
    fake = SimpleNamespace(Recognizer=Mock(), Microphone=MagicMock())
    with patch.dict(sys.modules, {"speech_recognition": fake}), \
         patch.object(voice_, "listen", side_effect=["background speech", "hey chexsa stop"]), \
         patch.object(voice_, "speak"), patch.object(voice_, "run_agent") as browser, \
         patch.object(voice_, "run_desktop_agent") as desktop, patch("builtins.print"):
        voice_.main("desktop")
        browser.assert_not_called()
        desktop.assert_not_called()
        fake.Microphone.reset_mock()
        voice_.main("invalid")
        fake.Microphone.assert_not_called()


# Run these plain test functions without introducing application classes.
def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_windows_speech, test_acknowledgment, test_wake_phrase,
        test_conversation, test_combined_request_and_silence, test_transcription_errors,
        test_agent_error_and_cleanup, test_no_task_on_startup_or_invalid_mode,
    ))
