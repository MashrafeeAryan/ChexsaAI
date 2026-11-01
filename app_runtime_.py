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


def _load_engines(states):
    """Create automation objects on the one thread that will use and close them."""
    import pythoncom

    # Windows accessibility uses COM. Initialize it here, not on Tk's UI thread.
    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        import agent_
        import desktop_agent_
        import llm_
        import files_
        import desktop_
        from browser_ import close_browser
        from plugins.gmail import gmail_agent_
    except BaseException:
        pythoncom.CoUninitialize()
        raise

    # App-generated files live outside the install folder, like saved settings.
    original_output = files_.OUTPUT_DIR
    files_.OUTPUT_DIR = settings_path().parent / "output"

    handlers = {
        "browser": agent_.run_agent,
        "desktop": desktop_agent_.run_desktop_agent,
        "gmail": gmail_agent_.run_gmail_agent,
    }

    def reset_clients():
        """Changed API settings need new connections, not the previous API key."""
        for module in (llm_, desktop_agent_):
            client = module._client
            if client is not None:
                client.close()
            module._client = None
        client = states["gmail"].pop("client", None)
        if client is not None:
            client.close()

    def cleanup():
        """Release the browser and Windows objects on their owning thread."""
        try:
            connection = states["browser"].get("playwright")
            if connection is not None:
                close_browser(connection)
            service = states["gmail"].get("service")
            if service is not None:
                service.close()
            reset_clients()
        finally:
            for state in states.values():
                state.clear()
            desktop_._observations.clear()
            files_.OUTPUT_DIR = original_output
            pythoncom.CoUninitialize()

    return handlers, reset_clients, cleanup


def run_worker(jobs, events, cancel, shutdown, initial_settings=None, handlers=None):
    """Run queued requests in order while the window remains responsive.

    Input job: {'kind': 'task', 'mode': 'browser', 'text': 'Open a website'}.
    Output event: {'kind': 'result', 'text': '...', 'review': False}.
    Tests supply fake handlers, so they never need model APIs or personal apps.
    """
    from queue import Empty

    states = {mode: {} for mode in ("browser", "desktop", "gmail")}
    cleanup = lambda: None
    reset_clients = lambda: None
    production = handlers is None

    try:
        if production:
            handlers, reset_clients, cleanup = _load_engines(states)
        baseline = {key: os.getenv(key) for key in SETTING_KEYS}

        def apply(values):
            """Override model settings in this process without editing .env."""
            values = validate_settings(values)
            for key in SETTING_KEYS:
                value = values[key] or baseline[key]
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_clients()

        apply(initial_settings or {})
        events.put({"kind": "ready"})

        while not shutdown.is_set():
            try:
                job = jobs.get(timeout=0.1)
            except Empty:
                continue
            if shutdown.is_set():
                break

            mode = job.get("mode", "desktop")
            try:
                if mode not in states:
                    raise ValueError("Choose browser, desktop, or Gmail mode.")
                state = states[mode]
                state["_cancel"] = cancel
                check_cancelled(state)
                events.put({"kind": "started", "mode": mode})

                if job["kind"] == "settings":
                    values = validate_settings(job["settings"])
                    save_settings(values)
                    apply(values)
                    text = "Settings saved for this Windows user."
                elif job["kind"] == "connect":
                    from plugins.gmail.gmail_auth_ import connect_gmail

                    service = connect_gmail(client_file=job["path"], allow_picker=False)
                    state.clear()
                    state.update(service=service, _cancel=cancel)
                    text = "Gmail connected. You can ask about your inbox or drafts."
                else:
                    if production and mode == "gmail":
                        from plugins.gmail.gmail_auth_ import connect_gmail

                        if job["text"].strip() == "/connect":
                            raise RuntimeError(
                                "Use Connect Gmail to choose the Google file in the window."
                            )
                        if (
                            "service" not in state
                            and job["text"].strip() != "/disconnect"
                        ):
                            # File dialogs belong on Tk's main thread, never this worker.
                            state["service"] = connect_gmail(allow_picker=False)
                    text = handlers[mode](job["text"], state)

                events.put(
                    {
                        "kind": "cancelled" if cancel.is_set() else "result",
                        "text": (
                            "Stopped after the current operation. "
                            if cancel.is_set()
                            else ""
                        )
                        + text,
                        "mode": mode,
                        "review": bool(state.get("pending_send"))
                        and not cancel.is_set(),
                    }
                )
            except InterruptedError as error:
                events.put({"kind": "cancelled", "text": str(error), "mode": mode})
            except (RuntimeError, ValueError) as error:
                events.put({"kind": "error", "text": str(error), "mode": mode})
            except Exception:
                events.put(
                    {
                        "kind": "error",
                        "text": "The request failed. Check settings, account access, and the selected app.",
                        "mode": mode,
                    }
                )
    except Exception:
        events.put(
            {
                "kind": "fatal",
                "text": "Could not start the agent worker. Check your Windows Python installation and dependencies.",
            }
        )
    finally:
        try:
            cleanup()
        except Exception:
            events.put(
                {
                    "kind": "error",
                    "text": "An automation connection could not be closed cleanly.",
                }
            )
        events.put({"kind": "closed"})


def record_message(stop):
    """Record one command for the input box; recording alone never executes it.

    Example speech: 'Hey Chexsa, open a website'. Output: 'open a website'.
    The existing recognizer sends this recording to Google for transcription.
    """
    try:
        import speech_recognition as sr
        from voice_ import get_request, listen
    except ImportError:
        raise RuntimeError(
            'Install microphone support: python -m pip install -e ".[voice]"'
        ) from None

    recognizer = sr.Recognizer()
    recognizer.operation_timeout = 10
    microphone = sr.Microphone()
    with microphone as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
    if stop.is_set():
        raise InterruptedError("Recording cancelled.")

    text = listen(recognizer, microphone)
    if stop.is_set():
        raise InterruptedError("Recording cancelled.")
    request = get_request(text)
    return text if request is None else request


def play_reply(text, stop):
    """Read the selected reply with Windows speech on this audio thread."""
    import pythoncom

    pythoncom.CoInitialize()
    try:
        from voice_ import speak

        if not stop.is_set():
            speak(text, cancel=stop)
    finally:
        pythoncom.CoUninitialize()
