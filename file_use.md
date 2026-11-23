# What each file does

ChexsaAI's main Python code now lives under the `chexsa/` package. Root files such as
`agent_.py`, `browser_.py`, and `cli_.py` are compatibility shims so existing
commands, tests, and editable installs keep working during the package transition.

## Package layout

```text
chexsa/
├── core/
│   ├── metrics.py
│   └── observations.py
├── browser/
│   ├── agent.py
│   ├── model.py
│   └── runtime.py
├── desktop/
│   ├── agent.py
│   ├── runtime.py
│   └── visual.py
├── files/
│   └── runtime.py
├── app/
│   ├── runtime.py
│   └── ui.py
├── interfaces/
│   ├── cli.py
│   └── voice.py
└── mcp/
    └── server.py
```

## Core

| File | Simple purpose |
| --- | --- |
| `chexsa/core/metrics.py` | Counts model calls, tokens, outcomes, and local task timing. |
| `chexsa/core/observations.py` | Builds compact browser/desktop views, change summaries, and action validation. |

## Browser

| File | Simple purpose |
| --- | --- |
| `chexsa/browser/agent.py` | Runs browser tasks, recovery, checkpoints, Canvas routing, and verified progress. |
| `chexsa/browser/runtime.py` | Opens Chrome, reads accessibility nodes, resolves exact targets, and executes browser actions. |
| `chexsa/browser/model.py` | Builds browser prompts, calls the configured model, and validates model actions. |

## Desktop

| File | Simple purpose |
| --- | --- |
| `chexsa/desktop/agent.py` | Runs Windows tasks and coordinates desktop/file tools. |
| `chexsa/desktop/runtime.py` | Reads Windows UI Automation controls and performs checked desktop actions. |
| `chexsa/desktop/visual.py` | Provides screenshot-based Windows fallback when accessibility controls are insufficient. |

## Files

| File | Simple purpose |
| --- | --- |
| `chexsa/files/runtime.py` | Creates, reads, edits, copies, and verifies text, Python, CSV, and Word files. |

## Application and interfaces

| File | Simple purpose |
| --- | --- |
| `chexsa/app/ui.py` | Builds the Windows chat application. |
| `chexsa/app/runtime.py` | Stores local settings/chats and runs agent work away from the UI thread. |
| `chexsa/interfaces/cli.py` | Runs terminal Browser, Desktop, Gmail, or Auto mode. |
| `chexsa/interfaces/voice.py` | Runs the spoken-request interface. |
| `chexsa/mcp/server.py` | Exposes selected local file tools through MCP. |

## Integrations

Service-specific integrations remain under `plugins/` so they stay isolated from
the computer-use engines.

| Path | Simple purpose |
| --- | --- |
| `plugins/gmail/` | Gmail OAuth, search/read tools, draft review, and duplicate-send protection. |
| `plugins/canvas_.py` | Canvas assignment reading, drafting, upload, and submission-status helpers. |

## Compatibility files

The old root module names remain intentionally small. They forward imports to the
package modules so older scripts and tests continue to work:

`agent_.py`, `browser_.py`, `desktop_.py`, `desktop_agent_.py`, `llm_.py`,
`observations_.py`, `task_metrics_.py`, `files_.py`, `visual_.py`,
`app_runtime_.py`, `app_.py`, `cli_.py`, `voice_.py`, and `mcp_server_.py`.

New code should import from `chexsa.*` instead of adding new root modules.

## Other repository folders

| Path | Simple purpose |
| --- | --- |
| `tests/` | Unit, integration, benchmark, and disposable browser/desktop fixtures. |
| `chexsa_assets/` | Packaged mascot and UI artwork. |
| `.github/workflows/ci.yml` | Windows CI for package compilation, unit tests, and isolated Chrome workflows. |
| `README.md` | Setup and usage overview. |
| `ARCHITECTURE.md` | Runtime architecture, recovery behavior, benchmarks, and future work. |
