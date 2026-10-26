# Local test notes

## Live Groq browser test — 2026-10-25

- Model: `openai/gpt-oss-120b`, using the existing Groq configuration.
- Page: a local fixture in an isolated headless Chrome profile.
- Request: replace Subject with `Hello Chexsa`, click Continue, and stop when Completed appears.
- Result: passed. The correct text was saved, Continue was submitted exactly once, and the completion control was visible.
- Live API requests: 3.
- Reported total tokens: 2,059 (662 + 684 + 713).
- Entire test command wall time: **9.54 seconds** (about 9.5 seconds).
- This time includes Python setup, Chrome startup, model requests, browser actions, verification, and cleanup. Individual model/action times and the agent-only duration were not measured.
- This was a local fixture test, not a Gmail test or a real email submission.
- No saved settings, normal Chrome tabs, or source files were changed by the test.
- Timing was taken from the completed command's recorded duration; no extra API calls were made to write this note.


## Live YouTube search test — 2026-10-25

- Request: Open YouTube and search for JavaScript tutorials.
- Model: `openai/gpt-oss-120b`.
- Browser: isolated headless Chrome with a temporary profile; no personal tabs used.
- Actions selected: navigate, type, click, reply.
- Independent search-results check passed: True.
- Final URL: https://www.youtube.com/results?search_query=JavaScript+tutorials.
- Agent reply: Search completed and results displayed..
- API requests attempted: 4 (limit: 6).
- Reported tokens: 2806.
- Agent run duration: 8.17 seconds (includes page observations, API calls, and actions).
- Script duration: 14.9 seconds (also includes imports, startup, independent verification, and cleanup).
- Request 1: 1.02 seconds, 512 reported tokens.
- Request 2: 0.68 seconds, 664 reported tokens.
- Request 3: 0.41 seconds, 772 reported tokens.
- Request 4: 0.5 seconds, 858 reported tokens.
- No model/settings changes, source edits, or Git operations. No automatic retry after an error.

## Single-read observations comparison — 2026-10-25

- Branch: `feat/page-observations`, based on `rebuild`.
- No live model requests; isolated headless Chrome fixtures only.
- Control descriptions matched rebuild. Text retention, hidden-text exclusion, duplicate-button clicks, and typing passed.
- Timing: 1,000-button local fixture, median of three alternating runs per implementation.
- Rebuild full read: 311.8 ms; single-read full read: 263.3 ms.
- These local fixture timings are not Gmail or YouTube measurements. Model input is unchanged; no token savings are claimed for this change.

## Page changes and discovery fixture — 2026-10-25

- Branch: `feat/page-observations`.
- Plain implementation functions; no new classes.
- Isolated Chrome, 1,000 unchanged buttons plus a form, fake model only.
- Passed typing, exact clicks, local discovery of an omitted unchanged control, text-change detection, and navigation reset.
- New serialized user-message sizes: 3,193 / 2,762 / 2,899 / 3,167 / 3,173 characters.
- Former full-controls user-message sizes for the same snapshots: 56,106 / 56,234 / 56,236 / 56,405 / 56,531 characters.
- These are user-payload character counts, not billed tokens; system prompts and model outputs are excluded. No token-savings percentage is claimed.
- Working view is limited to 40 complete controls; local search can supply 40 more results with continuation offsets.
- No old full-page snapshot is resent as model conversation history. The original request and action outcomes remain in each request.
- Field values stay in local structured control data; duplicate value text under editable fields is excluded from the text payload.
- Zero live API calls. Changes are not committed yet.

## Comparable isolated Chrome timing — 2026-10-25

- Same 1,000-button fixture for rebuild 513928c, single-read 89cd917, and current working changes.
- Identical type Subject, click Continue, reply workflow; three fake model calls per run.
- One warm-up per version; three measured runs each in rotating order, fresh page per run in one isolated temporary headless Chrome profile.
- All 12 runs verified Hello saved, one submission, and Completed visible. Zero live API calls.
- Loop timings exclude Chrome startup, page setup, final independent assertions, and cleanup; include page reads, prompt preparation, fake response parsing, and input actions.
- Input character counts include system plus user content across three calls; they are not billed tokens.
- Raw runs: {"rebuild": [{"loop_ms": 1265.81, "reads_ms": 1180.07, "per_read_ms": [524.21, 380.39, 275.46], "input_characters": 172934, "calls": 3}, {"loop_ms": 1157.04, "reads_ms": 1091.01, "per_read_ms": [375.4, 330.06, 385.55], "input_characters": 172934, "calls": 3}, {"loop_ms": 1121.62, "reads_ms": 1048.01, "per_read_ms": [400.9, 326.38, 320.73], "input_characters": 172934, "calls": 3}], "single_read": [{"loop_ms": 1235.35, "reads_ms": 1156.49, "per_read_ms": [290.31, 256.48, 609.7], "input_characters": 172934, "calls": 3}, {"loop_ms": 959.34, "reads_ms": 856.25, "per_read_ms": [322.14, 274.91, 259.21], "input_characters": 172934, "calls": 3}, {"loop_ms": 1009.1, "reads_ms": 920.85, "per_read_ms": [341.6, 267.74, 311.52], "input_characters": 172934, "calls": 3}], "current_changes": [{"loop_ms": 1261.35, "reads_ms": 1155.79, "per_read_ms": [550.64, 318.09, 287.06], "input_characters": 10702, "calls": 3}, {"loop_ms": 944.03, "reads_ms": 857.1, "per_read_ms": [309.1, 262.75, 285.25], "input_characters": 10702, "calls": 3}, {"loop_ms": 1100.46, "reads_ms": 1008.56, "per_read_ms": [373.09, 319.86, 315.61], "input_characters": 10702, "calls": 3}]}
- Medians: {"rebuild": {"median_loop_ms": 1157.04, "median_reads_ms": 1091.01, "median_input_characters": 172934}, "single_read": {"median_loop_ms": 1009.1, "median_reads_ms": 920.85, "median_input_characters": 172934}, "current_changes": {"median_loop_ms": 1100.46, "median_reads_ms": 1008.56, "median_input_characters": 10702}}
- Local timing cannot establish real model latency savings; no simulated network delay was added.

## Live YouTube current observation comparison — 2026-10-25

- Same request and configured Groq model as the recorded rebuild baseline; isolated temporary headless Chrome profile, no personal tabs.
- Agent timing excludes Chrome startup, independent outcome checks, and cleanup. Limit six requests, no API retries. Stop starting requests if accumulated usage reaches 6,000 tokens.
- Independently checked the search query URL and at least three relevant video headings.
- {"request": "Open YouTube and search for JavaScript tutorials.", "model": "openai/gpt-oss-120b", "verified": true, "reply": "Search completed. You are now viewing YouTube results for JavaScript tutorials.", "failure": null, "agent_seconds": 6.854, "script_seconds": 11.72, "requests_attempted": 4, "tokens": 3751, "prompt_tokens": 3150, "completion_tokens": 601, "calls": [{"number": 1, "seconds": 1.101, "prompt_tokens": 526, "completion_tokens": 135, "total_tokens": 661, "action": "navigate"}, {"number": 2, "seconds": 0.535, "prompt_tokens": 708, "completion_tokens": 172, "total_tokens": 880, "action": "type"}, {"number": 3, "seconds": 0.434, "prompt_tokens": 927, "completion_tokens": 126, "total_tokens": 1053, "action": "click"}, {"number": 4, "seconds": 0.684, "prompt_tokens": 989, "completion_tokens": 168, "total_tokens": 1157, "action": "reply"}], "actions": [{"action": "navigate", "url": "https://www.youtube.com"}, {"action": "type", "backend_node_id": 4, "text": "JavaScript tutorials"}, {"action": "click", "backend_node_id": 794}, {"action": "reply", "text": "Search completed. You are now viewing YouTube results for JavaScript tutorials."}], "final_url": "https://www.youtube.com/results?search_query=JavaScript+tutorials"}
- Prior rebuild run: 8.17 seconds, four requests, 2,806 tokens. Different-time single runs cannot isolate model/network variability.

## Desktop click and type functions — 2026-10-26

- Branch feat/page-observations; current action changes remain uncommitted. No browser edits in this step.
- 166 unit tests passed, compileall passed, git diff --check passed. No new classes. Zero model/API calls.
- Native disposable fixture passed duplicate-button semantic invocation, stale/detached target rejection, direct text replacement including Unicode, clearing, and readonly checks.
- Physical mouse fallback could not be validated: this execution context repeatedly refused cursor movement. The laptop was confirmed unlocked, with matching session and accessible Default input desktop.
- Word UIA editor focus alone proved insufficient: actual foreground window must also match. Guard added before keyboard input.
- First user-assisted Word run entered the sample text, but independent Range.Text read-back found the final emoji as 12 while the immediate UIA check had matched. This was NOT counted as a pass.
- Direct Word API round-trip of the same emoji retained it in Range.Text and stored XML, isolating the problem to simulated typing or its immediate verification.
- Removed supplementary-character splitting from keyboard typing. Unsupported characters are now rejected before editing; direct ValuePattern fields retain Unicode support. Verification requires a stable match for 0.2 seconds within a bounded two-second read-back wait.
- Final user-assisted plain-text Word rerun timed out waiting for the correct foreground window and focused editor. No text entry occurred. The final Word typing check remains pending.
- Tests only used disposable native controls and new unsaved Word documents; no personal documents or API settings were used.

## Desktop CLI and model connection — 2026-10-26

- Desktop tools are connected through desktop_agent_.py using native tool-call schemas and the existing .env keys. Browser implementation was not edited in this step.
- cli_.py defaults to desktop mode; explicit browser mode remains available. Starting and exiting both modes succeeds with empty API settings and no app launch.
- 176 unit tests passed; compileall and git diff --check passed; no new classes.
- Actual SDK request/response serialization and rate limiting were exercised with httpx.MockTransport. One request only on a simulated 429; no external requests.
- A disposable native Windows fixture passed the connected controller: short draft rejected before input, exactly 300 words entered once, fresh read-back verified, completion accepted. Three fake model calls; zero Groq usage.
- Word and Notepad installed-app lookup succeeded. Startup-window recovery stays within the known process; a closed app does not permanently block a new request.
- Full live Groq-to-Word 300-word execution is not validated in this step. Word keyboard fallback still rejects unsupported supplementary characters before editing.
- Current connection changes are local and uncommitted. No push or main-branch changes.


## Rebuild-only cleanup - 2026-10-26

- Saved pending browser, desktop, and documentation work in separate local commits.
- Removed 50 tracked legacy files: the old engines, routing/voice entry points,
  old integration scripts, and tests/fixtures that only exercised the old code.
- Kept the seven rebuilt runtime modules, four unit-test files, two integration
  fixtures, documentation, CI, and packaging. Updated the package command to cli_:main.
- Before removal: 176 unit tests passed. After removal: all 52 tests covering the
  rebuilt implementation passed. The reduction comes from deleting legacy tests.
- Compilation and whitespace checks passed. The isolated 1,000-button Chrome
  fixture passed typing, clicking, omitted-control discovery, and navigation reset.
- Reinstalled the editable package. Both direct and installed CLI commands started
  and exited in desktop and browser modes from another folder with empty API settings.
  The old chexsa-voice command was removed, and the local .env was preserved.
- No live API calls, personal browser tabs, or Word documents were used in cleanup.
  Full live-model-to-Word acceptance remains unverified.
