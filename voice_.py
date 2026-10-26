"""Standalone voice pieces. No browser, desktop, or model connections."""

from random import choice

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
