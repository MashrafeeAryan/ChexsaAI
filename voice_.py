"""Speak requests to the selected browser or desktop agent.

Run python voice_.py for desktop, or python voice_.py browser for Chrome.
Run python voice_.py gmail for connected email tools.
Google transcribes recordings; Windows speaks replies.
"""

from random import choice
import re
import sys

from agent_ import run_agent
from desktop_agent_ import run_desktop_agent
from browser_ import close_browser
from gmail_agent_ import run_gmail_agent

GREETING = "Hi Mashrafee, what can I do for you today?"
ACKNOWLEDGMENTS = (
    "On it.",
    "Sure.",
    "Working on it.",
    "Yes Mashrafee, I am working on it.",
)


# Windows reads the text aloud; this waits until speaking has finished.
def speak(text):
    from win32com.client import Dispatch

    Dispatch("SAPI.SpVoice").Speak(text)


# Pick a short response without asking an AI model to generate one.
def acknowledge():
    text = choice(ACKNOWLEDGMENTS)
    speak(text)
    return text


# Return the words after the wake phrase; None means Chexsa was not addressed.
def get_request(text):
    match = re.match(r"^\s*hey[\s,]+chexsa\b[\s,.:;!?-]*(.*)$", text, re.IGNORECASE)
    return match.group(1).strip() if match else None


# Record one phrase, then ask Google to turn that recording into words.
def listen(recognizer, microphone):
    import speech_recognition as sr

    try:
        # The microphone is closed before transcription or speech playback starts.
        with microphone as source:
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=12)
        return recognizer.recognize_google(audio).strip()
    except (sr.WaitTimeoutError, sr.UnknownValueError):
        return ""  # Silence or unclear speech is not a command.
    except sr.RequestError:
        raise RuntimeError("Speech recognition is unavailable. Check your internet connection.") from None


# Listen for requests, pass them to the chosen agent, and speak its response.
def main(mode="desktop"):
    if mode not in ("desktop", "browser", "gmail"):
        print("Choose desktop, browser, or gmail mode.")
        return
    # Reuse the same app or browser connection across spoken requests.
    state = {}
    try:
        import speech_recognition as sr
    except ImportError:
        print('Install voice support first: python -m pip install -e ".[voice]"')
        return

    try:
        recognizer = sr.Recognizer()
        recognizer.operation_timeout = 10  # Do not wait forever for transcription.
        microphone = sr.Microphone()
        print(f"Chexsa voice - {mode} mode")
        print("Say Hey Chexsa. Press Ctrl+C to stop.")
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)

        while True:
            request = get_request(listen(recognizer, microphone))
            if request is None:
                continue
            if not request:
                speak(GREETING)
                request = listen(recognizer, microphone)
                # Also accept a repeated wake phrase before the follow-up request.
                repeated = get_request(request)
                if repeated is not None:
                    request = repeated
            if not request:
                speak("I didn't catch that. Say Hey Chexsa to try again.")
                continue
            if request.rstrip(".!?").casefold() in ("stop", "exit", "quit", "goodbye"):
                speak("Goodbye, Mashrafee.")
                break
            acknowledge()
            print("You >", request)
            try:
                if mode == "gmail":
                    response = run_gmail_agent(request, state)
                else:
                    response = run_agent(request, state) if mode == "browser" else run_desktop_agent(request, state)
            except KeyboardInterrupt:
                response = "Task cancelled."
            except RuntimeError as error:
                print("Chexsa >", error)
                response = "I couldn't finish that request. Check the terminal for details."
            except Exception:
                response = "I couldn't finish that request. Check your connection and the selected app."
            print("Chexsa >", response)
            speak(response)
    except KeyboardInterrupt:
        pass
    except (OSError, AttributeError):
        print("Could not use the microphone. Check your microphone and Windows microphone access.")
    except RuntimeError as error:
        print(error)
    except Exception:
        print("Voice stopped. Check that Windows speech and your audio device are available.")
    finally:
        # Disconnect Chrome on exit; leave desktop documents open.
        if state.get("playwright") is not None:
            close_browser(state["playwright"])
        print("Voice stopped.")


# Choose the mode just like the terminal version.
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "desktop")
