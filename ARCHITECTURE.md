# Chexsa architecture

Chexsa accepts terminal or "Hey Chexsa" requests. `app_runtime.AppSession` waits
for a request, classifies it as chat, browser, or desktop, and creates only the
resources needed by that route. Starting the terminal or microphone does not
start Chrome. Browser tasks use `chexsa_browser/`; desktop tasks retain the
existing Windows agent. The new desktop backend and Gmail API integration are
future work.

## Browser flow

```text
Request -> plan -> focused observation -> choose action -> validate target
             ^                                              |
             |                                              v
          recover <- verify fresh evidence <- observe <- execute
                         |
                         v
                report a verified result
```

The browser engine is site independent. The model interprets the page; platform
code collects state and executes validated operations. It has no Gmail selectors
or Gmail-specific click sequence.

## Responsibilities and contracts

- `TaskSpec` holds the original goal, inputs, subgoals, completion criteria, and
  draft/act intent. `TaskState` retains progress, failures, submission state, and metrics.
- `Observation` retains the complete collected local element/text structures, tabs,
  regions, changes, and a bounded model view. Screenshots are requested separately.
- `ActionRequest` carries a validated action, arguments, and expected effect.
  `ActionResult` distinguishes dispatched operations, errors, and uncertain results.
- `TaskResult` distinguishes success, blocked, failed, uncertain, and cancelled runs.
- The `Backend` protocol exposes observation, execution, waiting, and cleanup.
  `BrowserModel` supplies planning, action selection, preflight, and independent
  completion assessment through the configured Gemini or OpenAI-compatible provider.

All browser tasks use `chexsa_browser/`. The desktop agent continues using its
existing `Agent` and UI Automation modules. `llm.py` supplies the shared model
client, voice routing, and desktop decisions.

## Exact browser targets

The collector joins `Accessibility.getFullAXTree` and `DOMSnapshot.captureSnapshot`
using `backendDOMNodeId`. Each identity includes the CDP target, frame, document,
and browser node. Parent landmarks, names, field values, state, and action
capabilities are retained. Password values are redacted in observations.

Refs such as `e17` are issued for each observation and never reused within that
backend instance. The registry resolves the recorded node with `DOM.resolveNode`.
It checks document generation, attachment, capability, disabled/read-only state,
and current accessible role/name before an element action. It never re-finds a
different control by matching its name or occurrence.

Reordering duplicate Send controls therefore does not swap their identity.
Replacing a node, changing Send to Delete, refreshing observations, or switching
tabs makes an old target fail explicitly. Headings provide context and do not
automatically acquire click capabilities.

## Large pages

Collected elements stay local. The default model page view has a 6,000-character
budget; this is a serialization budget, not an exact provider token count.
It contains an overview, a selected region, complete control records, relevant
text, and changes. Large individual fields are marked for expansion.

Active dialogs and focused forms are initially prioritized. Explicit inspection
can select another region. Regions are identified by nodes, so identical names
do not merge. Repeated inbox rows stay inside their containing region.

- `find_elements(query, cursor?)` searches the full collected local structure.
  An empty query can enumerate it, including omitted region anchors.
- `inspect_region(ref?, cursor?)` expands a region; `page` enumerates the page.
  Passing a control ref reads its full name/value/context in bounded chunks.
- Every page reports omitted records and an observation-scoped continuation cursor.
  Old cursors are rejected. Unloaded content requires scrolling/navigation and
  another observation.
- Changes compare stable node identity and state, not temporary ref numbers.
  Current controls accompany deltas; removed duplicates are not collapsed by name.

Discovery operations retain the current observation and refs. Browser mutations
are followed by fresh observation. An unsupported or closed frame is surfaced
as an observation issue when its CDP snapshot cannot be collected.

## Actions, screenshots, and waiting

Supported operations include navigation/history, tabs, click/type/keyboard,
selection, check/uncheck, scrolling, uploads, and guarded batches. Element
interaction uses public CDP DOM/Input operations. Playwright owns browser lifecycle,
navigation, screenshots, and keyboard/mouse helpers. No model-provided JavaScript
is evaluated.

Typing, native option selection, toggles, and uploads read back actual control
state. Batches validate all items and targets before starting and stop on errors,
navigation, tab changes, or invalidated targets. Enter/submission-capable batch
operations are rejected. Waits are bounded and watch relevant page changes rather
than demanding whole-page network idleness.

`capture_screenshot` returns a screenshot ID and CSS-pixel dimensions.
`click_coordinates(x, y, screenshot_id)` checks the observation, page, document,
viewport, and current image before clicking. The image uses CSS pixels even on
high-DPI displays. Lossless PNG capture waits for matching rendered frames within
a bounded number of attempts. Image comparison remains exact: animation or even
a native control repaint can reject a visual action and require a new capture.
Prefer node refs where available. A click consumes its pointer authority.
`type_focused(text, screenshot_id)` additionally requires the exact editable node
focused by that click. Fresh screenshots support independent visual verification.

Screenshots are transient by default. Set `CHEXSA_TRACE_SCREENSHOTS=1` to save
requested screenshots next to the task journal for debugging.

## Verification, recovery, and persistence

The model's `finish` action is a completion proposal. The controller refreshes the
page and asks the verifier. Text evidence must quote actual current page content;
visual evidence must reference the fresh attached screenshot. Execution success
alone is not task completion.

Observed URL and title are also valid exact evidence for navigation and searches.
The verifier must quote the actual value, without invented labels or paraphrases.

Email plans retain literal recipient addresses from the user request. Before a
submission, a separate preflight identifies the compose region and reads the
subject/body controls and recipient value or committed chip. Values must match
the intended draft. Draft-only requests cannot submit.

Submission intent is committed to SQLite before execution. After sending, the
controller requires new evidence; an old confirmation is insufficient. An explicit
application refusal is a failed result. Missing evidence is uncertainty. Neither
uncertain submissions nor interrupted submission intents are automatically replayed.
Live status/alert text has a separate bounded notices section so a large inbox
cannot hide a sending receipt. After checked dispatch, a fresh same-page and
same-frame affirmative email receipt is recorded as verified progress. Old notices
and quoted draft text do not qualify. The independent verifier must still assess
the whole requested goal; a receipt alone cannot finish unrelated remaining work.
Application acceptance does not prove delivery or that a recipient read the message.

Task state, action results, recovery history, model token/call counts, and latency
are saved locally. The default location is `%LOCALAPPDATA%/Chexsa/tasks.sqlite3`;
`CHEXSA_STATE_DIR` overrides it. Task history can contain user-provided message data.
Browser objects and credentials are not serialized.

Defaults are 50 action steps, 600 seconds per invocation, and three consecutive
recoverable failures. Repeated identical actions without progress cause a replan,
then a blocked/uncertain result if repetition continues. Ctrl+C cancels a task.
Questions preserve task state for clarification. Programmatic resume first observes and reconciles
the current browser; a completed task returns its recorded result without executing.

## Configuration and validation

Existing `LLM_PROVIDER`, `LLM_MODEL`, `GEMINI_API_KEY`, `LLM_API_KEY`, and
`LLM_BASE_URL` settings remain supported. The terminal starts with `chexsa` and
uses the saved settings without startup flags. Task limits are fixed at 50 actions,
600 seconds, and three consecutive recoverable failures. The page context budget
is fixed at 6,000 characters. Browser connection settings are:

| Setting | Default |
|---|---|
| `CHEXSA_CDP_URL` | `http://127.0.0.1:9222` |
| `CHEXSA_CHROME_USER_DATA_DIR` | Chexsa's persistent profile root; optional saved Chrome root |
| `CHEXSA_CHROME_PROFILE` | `Default`; can select `Profile 1`, etc. |
| `CHEXSA_AUTO_LAUNCH` | `1` |
| `CHEXSA_TRACE_SCREENSHOTS` | `0` |
| `LLM_SUPPORTS_VISION` | `0` for compatible providers, `1` for Gemini |
| `LLM_TIMEOUT_SECONDS` | `30` seconds per API request |
| `LLM_REASONING_EFFORT` | `medium` for GPT-OSS 20B/120B; otherwise provider default |

Text-only models receive string content and are not offered screenshot actions.
Groq GPT-OSS 20B/120B use the provider's strict JSON schemas for plans,
preflight, and verification. Action selection uses JSON object mode with a typed
action catalog and local validation; this avoids unsupported provider union schemas. Optional schema fields use null and are removed before
normal validation; false, zero, and empty strings remain meaningful. Plan inputs
use unique name/value entries at the API boundary and are stored as a flat map.
If a provider validation error contains usable JSON, Chexsa checks it locally
against that schema; only missing nullable fields may be omitted. Malformed
objects and unknown fields remain rejected.
Other endpoints retain JSON object mode. Schema compliance does not prove that
an action is correct: action, target, and outcome checks still run.
Compatible-provider SDK retries are disabled. Invalid JSON gets one corrective
retry. Rate limits get up to two announced retries within a 60-second total wait
budget, rounding up fractional delays with a margin. JSON and quota retries have
separate budgets. Repeated or longer limits stop the task; no browser action is
replayed by API retries.

Planning sends only a page overview. Ordinary verification sends current data;
external-submission verification also retains the before-state. The focused view
includes a small index of editable fields in other regions, and limits the share
used for changes, reducing repeated context and unnecessary discovery calls.

Auto launch uses a dedicated persistent Chrome profile under
`%LOCALAPPDATA%/Chexsa/chrome`, with first-run and default-browser prompts disabled.
It opens the Default profile rather than an ephemeral Guest session. Chrome
account sync is not required; website cookies and local storage persist across
restarts. Sites can still expire or revoke their own sessions. This does not
copy another Chrome profile's logins. Existing Chrome can be reused when its
configured CDP endpoint is available. Disconnecting Chexsa leaves Chrome open.

For an explicitly configured user-data root, the session discovers a local
WebSocket endpoint from `DevToolsActivePort`. An explicit CDP URL overrides that
discovery. A custom root without a discovery file launches on a separate free
port, avoiding accidental attachment to an unrelated profile on 9222. Named
profiles preserve their own cookies/storage and remain isolated from one another.
The profile-folder setting selects a profile when launching. Attaching uses the
profile exposed by that debugging endpoint; it does not switch the signed-in account.

Chrome 136+ ignores debugging flags on its standard data directory. Chrome 144+
offers a separate user-approved connection flow: enable remote debugging at
`chrome://inspect/#remote-debugging`, then allow the connection prompt. Chexsa
can discover the endpoint from that configured root; it never changes Chrome's
approval setting or copies encrypted login data. This route needs an open Chrome
and user approval. See [Chrome's official guide](https://developer.chrome.com/docs/devtools/agents/use-cases/auto-connect).

Observation boundaries recover a closed selected tab, preferring an open page
and creating a blank tab when necessary. A disconnected browser reconnects at
that boundary. Execution remains strict: it never substitutes another tab or
replays old refs. Startup tabs disappearing during observation are retried within
a bounded number of attempts. Browser clarification answers stay with the task
that asked for them rather than being routed as unrelated chat.

Run fast tests with `python -m unittest discover -s tests -p "test_*.py" -v`.
Run real Chrome fixtures with `scripts/test_browser.ps1`. They use dedicated tabs
and localhost pages, including 20 consecutive email flows and explicit refused,
delayed, and uncertain outcomes. A scripted model tests the contract without API
keys. These tests do not establish live-model or production Gmail success rates.
Live sending requires a separately requested task with a connected account.

`python scripts/test_live_browser.py` is an opt-in live-model check. It invokes
the actual CLI using the saved API configuration in an isolated temporary Chrome
profile. It independently checks YouTube navigation/search against the real URL
and title. `--email` additionally checks a local fake inbox with 2,000 rows, exact
recipient/subject/body, one submission, and zero wrong duplicate-button clicks.
It records timings and task token metrics in `.chexsa/live-smoke.json`.
