"""Keep desktop-app settings and background work together, away from the window."""

import json
import os
from pathlib import Path

SETTING_KEYS = ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL")
MASCOTS = ("Foxy", "Fluffy", "Bruhhh")


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

    if not isinstance(settings, dict) or set(settings) - (
        set(SETTING_KEYS) | {"DISPLAY_NAME", "MASCOT"}
    ):
        raise ValueError("Use model settings, a display name, and an available mascot.")

    result = {}
    for key in SETTING_KEYS:
        value = settings.get(key, "")
        if not isinstance(value, str) or "\n" in value or "\r" in value:
            raise ValueError("Each setting must be a single line of text.")
        result[key] = value.strip()

    # Interface preferences stay local; they are never added to model requests.
    if "DISPLAY_NAME" in settings:
        name = settings["DISPLAY_NAME"]
        if (
            not isinstance(name, str)
            or len(name) > 60
            or any(char in name for char in "\r\n\t")
        ):
            raise ValueError("Use a short display name on one line.")
        result["DISPLAY_NAME"] = name.strip()
    if "MASCOT" in settings:
        # Older saved profiles used Foxxy. Keep those profiles working after the rename.
        mascot = "Foxy" if settings["MASCOT"] == "Foxxy" else settings["MASCOT"]
        if mascot not in MASCOTS:
            raise ValueError("Choose Foxy, Fluffy, or Bruhhh.")
        result["MASCOT"] = mascot

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


def chats_path():
    """Keep saved chats under this Windows user, outside the installed app."""
    return settings_path().parent / "chats.sqlite3"


def _chat_database(path):
    """Open the local chat store. Only encrypted chat contents go into its rows."""
    import sqlite3

    path = Path(path) if path is not None else chats_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=2)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS chats (id TEXT PRIMARY KEY, saved REAL, data BLOB)"
    )
    return connection


def save_chat(chat, path=None):
    """Save one conversation, never live app objects or approval state.

    Input: {'id': 'abc', 'title': 'A task', 'mode': 'desktop', 'messages': [...]}.
    Output: no value; the encrypted conversation is saved on this laptop.
    """
    from contextlib import closing
    from time import time
    import win32crypt

    # Copy only display data. Old Windows IDs and Gmail send approvals cannot return.
    values = {key: chat[key] for key in ("id", "title", "mode", "messages")}
    data = win32crypt.CryptProtectData(
        json.dumps(values, ensure_ascii=False).encode("utf-8"),
        "Chexsa chat",
        None,
        None,
        None,
        0,
    )
    with closing(_chat_database(path)) as connection, connection:
        connection.execute(
            "INSERT OR REPLACE INTO chats VALUES (?, ?, ?)",
            (values["id"], time(), data),
        )


def load_chats(path=None):
    """Read newest chats first. A damaged record raises an error instead of being erased."""
    from contextlib import closing
    import win32crypt

    with closing(_chat_database(path)) as connection:
        rows = connection.execute(
            "SELECT data FROM chats ORDER BY saved DESC"
        ).fetchall()

    chats = []
    for (data,) in rows:
        raw = win32crypt.CryptUnprotectData(data, None, None, None, 0)[1]
        chat = json.loads(raw)
        if (
            not isinstance(chat, dict)
            or not all(
                isinstance(chat.get(key), str) for key in ("id", "title", "mode")
            )
            or chat["mode"] not in ("desktop", "browser", "gmail")
            or not isinstance(chat.get("messages"), list)
            or any(
                not isinstance(message, dict)
                or not all(
                    isinstance(message.get(key), str) for key in ("speaker", "text")
                )
                for message in chat["messages"]
            )
        ):
            raise ValueError("A saved chat could not be read.")
        chats.append(chat)
    return chats


def delete_chat(chat_id, path=None):
    """Remove one saved conversation; files created by its tasks are left alone."""
    from contextlib import closing

    with closing(_chat_database(path)) as connection, connection:
        connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))


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
                elif job["kind"] == "reset":
                    # Keep live connections, but discard the previous chat's selected targets.
                    states["desktop"].clear()
                    states["browser"].pop("_browser_task", None)
                    gmail = states["gmail"]
                    for key in tuple(gmail):
                        if key not in ("service", "client", "_cancel"):
                            gmail.pop(key)
                    text = "New chat ready."
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
                        "operation": job["kind"],
                        "paused": mode == "browser"
                        and job["kind"] == "task"
                        and state.get("_browser_task", {}).get("status") == "paused",
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
