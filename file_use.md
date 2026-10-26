# What each file does

The new Python files end in `_`. The old code was removed; Git history keeps it.

## App files

| File | Simple purpose |
| --- | --- |
| `cli_.py` | Shows the terminal chat and sends your request to the selected engine. |
| `agent_.py` | Holds the browser task together: ask, act, read again, repeat. |
| `browser_.py` | Opens or connects to Chrome, reads controls, clicks, and types. |
| `llm_.py` | Sends the browser request to the model and checks its JSON answer. |
| `observations_.py` | Finds page changes and chooses a smaller page view for the model. |
| `desktop_agent_.py` | Gives the model desktop tools and checks progress on its task. |
| `files_.py` | Creates a new text or code file, saves it, and checks the saved contents. |
| `desktop_.py` | Finds Windows apps, reads controls, clicks, types, and sends shortcuts. |
| `voice_.py` | Listens for Hey Chexsa, sends requests to the selected agent, and speaks the result. |

## Setup and docs

| File | Simple purpose |
| --- | --- |
| `pyproject.toml` | Lists required libraries and makes the `chexsa` terminal command. |
| `.gitignore` | Keeps keys, installed libraries, caches, and local browser data out of Git. |
| `.env` (local only) | Stores your API key, model name, and API address. |
| `README.md` | Explains setup, commands, working features, and current limits. |
| `ARCHITECTURE.md` | Explains how the browser and desktop pieces connect. |
| `file_use.md` | This file: explains the purpose of each file. |
| `.github/workflows/ci.yml` | Runs unit tests and an isolated Chrome fixture in GitHub Actions. |
| `.github/workflows/release.yml` | Builds a Python package when a version tag is pushed. |

## Tests

| File | Simple purpose |
| --- | --- |
| `tests/test_agent_.py` | Checks the browser task loop and model action validation with fake replies. |
| `tests/test_browser_observation_.py` | Checks page reading, node identity, changes, search, clicks, and typing. |
| `tests/test_desktop_.py` | Checks Windows control selection, clicking, typing, and stale-target guards. |
| `tests/test_desktop_agent_.py` | Checks desktop model tools, task progress, word counts, limits, and CLI modes. |
| `tests/test_files_.py` | Checks file creation, saved contents, and protection against overwriting existing files. |
| `tests/test_voice_.py` | Checks wake phrases, spoken replies, agent selection, and cleanup with fake audio. |
| `tests/browser_changes_integration_.py` | Runs the new browser loop on a large local page in isolated Chrome. |
| `tests/desktop_actions_integration_.py` | Manually tests real disposable Windows controls and a temporary Word document. |

`.venv/`, `.chexsa/`, `__pycache__/`, `build/`, `dist/`, and `*.egg-info/` are local
runtime or generated folders, not extra implementations. Do not put API keys in docs.

## Run voice

Install the optional microphone support:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[voice]"
```

Desktop mode:

```powershell
.\.venv\Scripts\python.exe voice_.py
```

Browser mode:

```powershell
.\.venv\Scripts\python.exe voice_.py browser
```

Say **Hey Chexsa**, wait for the greeting, then give a request. You can also say
**Hey Chexsa, open YouTube** in one sentence when running browser mode.
Chexsa acknowledges the request, runs the selected agent, and speaks its result.

Say **Hey Chexsa, stop** or press **Ctrl+C** to close it. During a running task,
Ctrl+C cancels that task; voice then returns to listening.

- You choose browser or desktop mode at startup; there is no automatic mode choice yet.
- Speech recognition sends recordings to Google's speech service and needs internet.
- The wake phrase is detected from transcribed speech, not by an offline wake-word detector.
- Windows speaks fixed greetings and acknowledgments without an AI model call.
- Agent tasks use your existing model settings and API quota, like terminal tasks.
- Listening pauses during speech and task execution. Spoken stop commands work while listening.
- Voice must be running to hear the wake phrase; it does not start with Windows.

## Create a file without opening an editor

Start desktop mode with `python cli_.py`. For example:

- `Create fibonacci.py with a function that returns the first 10 Fibonacci numbers.`
- `Create notes.txt containing Hello Mashrafee.`
- `Create a Markdown file called ideas.md with my project ideas.`

The model chooses the path and text; `files_.py` creates and saves the file.
Relative paths go inside the repository's `output/` folder. You can also request
an absolute path. Chexsa reads the contents back before reporting success.
Existing files are never overwritten, and generated code is not executed.
Python files receive a syntax check. Office documents and images need other tools.
