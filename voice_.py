"""Standalone voice prototype: run python voice_.py.

Google transcribes recordings; Windows speaks replies. Requests are only printed.
No browser, desktop, or model connections.
"""

from random import choice
import re

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


# Try the voice conversation alone; captured requests are printed, never executed.
def main():
    try:
        import speech_recognition as sr
    except ImportError:
        print('Install voice support first: python -m pip install -e ".[voice]"')
        return

    try:
        recognizer = sr.Recognizer()
        recognizer.operation_timeout = 10  # Do not wait forever for transcription.
        microphone = sr.Microphone()
        print("Voice prototype: requests are captured, not executed.")
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
            print("Captured request (not executed):", request)
    except KeyboardInterrupt:
        pass
    except (OSError, AttributeError):
        print("Could not use the microphone. Check your microphone and Windows microphone access.")
    except RuntimeError as error:
        print(error)
    except Exception:
        print("Voice stopped. Check that Windows speech and your audio device are available.")
    finally:
        print("Voice stopped.")


# Running this file starts only the voice prototype.
if __name__ == "__main__":
    main()
