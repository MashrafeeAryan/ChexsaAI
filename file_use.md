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
| `desktop_.py` | Finds Windows apps, reads controls, clicks, types, and sends shortcuts. |

## Setup and docs

| File | Simple purpose |
| --- | --- |
| `pyproject.toml` | Lists required libraries and makes the `chexsa` terminal command. |
| `.gitignore` | Keeps keys, installed libraries, caches, and local browser data out of Git. |
| `.env` (local only) | Stores your API key, model name, and API address. |
| `README.md` | Explains setup, commands, working features, and current limits. |
| `ARCHITECTURE.md` | Explains how the browser and desktop pieces connect. |
| `file_use.md` | This file: explains the purpose of each file. |
| `PROJECT_GOALS_.md` | Saves the intended token-saving and reusable-skill goals. |
| `TEST_NOTES_.md` | Records past measurements and what has or has not been verified. |
| `.github/workflows/ci.yml` | Runs unit tests and an isolated Chrome fixture in GitHub Actions. |
| `.github/workflows/release.yml` | Builds a Python package when a version tag is pushed. |

## Tests

| File | Simple purpose |
| --- | --- |
| `tests/test_agent_.py` | Checks the browser task loop and model action validation with fake replies. |
| `tests/test_browser_observation_.py` | Checks page reading, node identity, changes, search, clicks, and typing. |
| `tests/test_desktop_.py` | Checks Windows control selection, clicking, typing, and stale-target guards. |
| `tests/test_desktop_agent_.py` | Checks desktop model tools, task progress, word counts, limits, and CLI modes. |
| `tests/browser_changes_integration_.py` | Runs the new browser loop on a large local page in isolated Chrome. |
| `tests/desktop_actions_integration_.py` | Manually tests real disposable Windows controls and a temporary Word document. |

`.venv/`, `.chexsa/`, `__pycache__/`, `build/`, `dist/`, and `*.egg-info/` are local
runtime or generated folders, not extra implementations. Do not put API keys in docs.
