# What each file does

This is a simple guide to every file kept in the repository.
The main code for controlling websites is in `chexsa_browser/`.

## Main files

| File | What it does |
|---|---|
| [README.md](README.md) | Explains what Chexsa is and how to install and start it. |
| [file_use.md](file_use.md) | This guide: explains what each file is for. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Explains how the parts work together, including browser safety and task recovery. |
| [pyproject.toml](pyproject.toml) | Lists the Python libraries Chexsa needs and sets up the `chexsa` and `chexsa-voice` commands. |
| [.gitignore](.gitignore) | Keeps local secrets, installed libraries, and generated files out of GitHub. |
| [cli.py](cli.py) | Starts terminal chat and waits for your request. Also lets you list saved tasks and resume one. |
| [app_runtime.py](app_runtime.py) | Chooses chat, browser, or desktop for each request. Starts browser or desktop tools only when needed, for both terminal and voice mode. |
| [voice.py](voice.py) | Listens for "Hey Chexsa" and sends your request to chat, the browser, or Windows desktop. |
| [llm.py](llm.py) | Loads your chosen AI provider and model settings. Answers chat, chooses the right task route, and asks the AI how to handle desktop tasks. |
| [agent.py](agent.py) | Runs the desktop task loop: read the app, ask the AI, act, and repeat. |
| [desktop_state.py](desktop_state.py) | Reads open Windows apps and their buttons, fields, and other controls. |
| [desktop_actions.py](desktop_actions.py) | Opens and controls Windows apps, including clicking, typing, and keyboard shortcuts. |

## Browser code: `chexsa_browser/`

| File | What it does |
|---|---|
| [__init__.py](chexsa_browser/__init__.py) | Marks this folder as a Python package. |
| [runtime.py](chexsa_browser/runtime.py) | Builds the same browser engine for terminal chat and voice mode. |
| [session.py](chexsa_browser/session.py) | Connects to Chrome, skips its first-run setup, keeps a saved profile, and recovers an open tab when the selected tab closes. |
| [backend.py](chexsa_browser/backend.py) | Brings page reading, actions, waiting, and cleanup together. |
| [collector.py](chexsa_browser/collector.py) | Reads the page's text, controls, positions, field values, and states. |
| [regions.py](chexsa_browser/regions.py) | Groups controls into areas such as dialogs and forms so Chexsa can focus on the right area. |
| [context.py](chexsa_browser/context.py) | Chooses a small, useful part of a large page for the AI. Also handles page search and showing more results. |
| [targets.py](chexsa_browser/targets.py) | Connects short IDs such as `e17` to real page elements. Rejects IDs that are out of date. |
| [actions.py](chexsa_browser/actions.py) | Checks browser actions and performs clicks, typing, scrolling, uploads, tab changes, and other supported actions. |
| [visual.py](chexsa_browser/visual.py) | Takes screenshots and handles clicks by screen position and typing into the clicked field. Checks that the target is still valid. |
| [model.py](chexsa_browser/model.py) | Talks to the AI to plan a browser task, choose its next action, and check results. |
| [agent.py](chexsa_browser/agent.py) | Leads the whole browser task. Remembers the goal, runs steps, checks progress, and handles problems. |
| [verification.py](chexsa_browser/verification.py) | Checks evidence of success or failure. For email, checks the draft before sending and looks for a fresh sending result. |
| [journal.py](chexsa_browser/journal.py) | Saves task progress locally so interrupted tasks can be checked and resumed. |
| [models.py](chexsa_browser/models.py) | Defines shared data records for tasks, pages, elements, actions, and results. This file describes data, not an AI model. |

## Start and test scripts

| File | What it does |
|---|---|
| [scripts/start_voice.ps1](scripts/start_voice.ps1) | Starts voice mode from PowerShell, using the local Python setup when available. |
| [scripts/test_browser.ps1](scripts/test_browser.ps1) | Runs browser tests in Chrome. Starts a separate test Chrome if needed and closes the one it started. |

## Automatic GitHub checks

| File | What it does |
|---|---|
| [.github/workflows/ci.yml](.github/workflows/ci.yml) | Runs code checks, unit tests, and Chrome tests on Python 3.11 and 3.12 when code is pushed or a pull request changes. Saves failed test-page screenshots for debugging. |
| [.github/workflows/release.yml](.github/workflows/release.yml) | Builds downloadable Python packages when a version tag such as `v0.1.0` is pushed. |

## Tests

Tests help catch mistakes when the code changes. The browser test pages are local
fake pages: they do not send real email or need an email account.

| File | What it checks |
|---|---|
| [tests/test_agent.py](tests/test_agent.py) | The desktop task loop, its step limit, and error handling. |
| [tests/test_app_runtime.py](tests/test_app_runtime.py) | Chat and desktop requests do not open Chrome; browser requests open it only when needed, and task answers stay attached to their question. |
| [tests/test_llm.py](tests/test_llm.py) | Provider settings, chat replies, request routing, and desktop decisions work. Uses fake API clients. |
| [tests/test_voice.py](tests/test_voice.py) | Wake-phrase handling and sending requests to the correct browser or desktop agent. |
| [tests/test_browser_agent.py](tests/test_browser_agent.py) | Task completion needs evidence, draft requests do not send, and repeated actions trigger recovery. |
| [tests/test_browser_backend.py](tests/test_browser_backend.py) | Reading a page retries if navigation changes a frame, while unrelated errors still surface. |
| [tests/test_browser_collector.py](tests/test_browser_collector.py) | Page details are read correctly, duplicate controls stay separate, and password values are hidden. |
| [tests/test_browser_context.py](tests/test_browser_context.py) | Large pages stay within the AI's page-text limit, searches find omitted controls, and changes are tracked correctly. |
| [tests/test_browser_entrypoints.py](tests/test_browser_entrypoints.py) | Terminal and voice mode use the current browser engine, including task listing, resume, and cleanup. |
| [tests/test_browser_fixtures.py](tests/test_browser_fixtures.py) | The fake browser pages still contain the controls and sending outcomes needed by the tests. |
| [tests/test_browser_journal.py](tests/test_browser_journal.py) | Task progress survives a restart, uncertain sends are not replayed, and completed tasks are not run again. |
| [tests/test_browser_model.py](tests/test_browser_model.py) | AI plans and actions are checked, supplied email addresses are kept, and supported AI clients receive the right request format. |
| [tests/test_browser_regions.py](tests/test_browser_regions.py) | Different dialogs with the same name stay separate, and forms stay inside the correct dialog. |
| [tests/test_browser_runtime.py](tests/test_browser_runtime.py) | Starting the browser engine connects its parts correctly and cleans up after a failed connection. |
| [tests/test_browser_session.py](tests/test_browser_session.py) | Closed-tab recovery, reconnecting, opening a missing tab, and launching a saved Chrome profile without first-run prompts. |
| [tests/test_browser_targets.py](tests/test_browser_targets.py) | An element ID picks the correct control and fails when its page, node, or meaning changes. |
| [tests/test_browser_validation.py](tests/test_browser_validation.py) | Invalid action arguments and unsafe batches are rejected before execution. |
| [tests/test_browser_visual.py](tests/test_browser_visual.py) | Screenshot checks handle rendering delays and reject changed pages, images, and viewports. |
| [tests/browser_engine_integration.py](tests/browser_engine_integration.py) | Uses real Chrome to check 20 email runs, exact targets, uploads, embedded pages, screenshots, recovery after closing a tab, and saved site state after restarting Chrome. |
| [tests/desktop_integration.py](tests/desktop_integration.py) | A manual Windows test that opens Word, writes text, and checks it. Leaves Word open so you can inspect it. |
| [scripts/test_live_browser.py](scripts/test_live_browser.py) | Tests the real terminal with your API key using an empty Chrome profile. Checks YouTube and optionally a fake email, then saves timings. Uses API quota. |
| [tests/fixtures/controls.html](tests/fixtures/controls.html) | A fake page with duplicate buttons, fields, uploads, embedded controls, and a visual-only target. |
| [tests/fixtures/frame.html](tests/fixtures/frame.html) | A small page embedded inside another test page to check controls inside frames. |
| [tests/fixtures/mail.html](tests/fixtures/mail.html) | A fake inbox and compose window with successful, refused, delayed, and uncertain sending outcomes. |

## Local files that are not on GitHub

These files and folders may appear on your computer. They are not extra source
files to maintain.

| File or folder | What it is for |
|---|---|
| `.env` | Your local AI provider settings and API keys. Git ignores it. |
| `.venv/` | The installed Python environment used to run Chexsa. |
| `__pycache__/` and `*.pyc` | Python's temporary files that help code load faster. |
| `*.egg-info/` | Package information made during installation or builds. |
| `build/` and `dist/` | Generated package build files. |
| `.chexsa/` | Local browser test profiles, test diagnostics, and other development output. |
| `.git/` | Git's saved history and branch information. |

Saved tasks normally live outside the repository at
`%LOCALAPPDATA%/Chexsa/tasks.sqlite3`. Chrome's normal Chexsa profile lives at
`%LOCALAPPDATA%/Chexsa/chrome`. `CHEXSA_STATE_DIR` can change the task folder.
