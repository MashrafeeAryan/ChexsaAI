# Benchmark results

## Desktop

### Readable-type filtering

| Mode | With `_READABLE_TYPES`: observation tokens | Without `_READABLE_TYPES`: observation tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Desktop | 4,270 | 8,252 | 3,982 | 48.25% |

This reduced observation tokens by **48.25%**.

### Hidden-control filtering

| Mode | With hidden controls skipped: observation tokens | Without skipping hidden controls: observation tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Desktop | 4,270 | 4,812 | 542 | 11.26% |

This reduced observation tokens by **11.26%**.

### Compact descriptions

| Mode | Compact: observation tokens | Verbose baseline: observation tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Desktop | 4,270 | 14,024 | 9,754 | 69.55% |

This reduced observation tokens by **69.55%** against the verbose baseline.

### Local verification

| Mode | Local Python checks: model input tokens | Local verification |
| :--- | ---: | :--- |
| Desktop | 0 | Passed |

Local verification used **0 model tokens**; no percentage comparison was measured.

### Direct file creation (.txt, scripted workflow)

| Route | Decisions | Request-text tokens | Tool-call-text tokens | Total text tokens | Saved file |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Direct file tool | 1 | 1,183 | 152 | 1,335 | Verified |
| Editor fixture | 5 | 7,228 | 243 | 7,471 | Verified |

This reduced text tokens by **82.13%**.

### Finish after verified final save (scripted workflow)

| Route | Decisions | Request-text tokens | Tool-call-text tokens | Total text tokens | Saved file |
| :--- | ---: | ---: | ---: | ---: | :--- |
| Finish immediately | 1 | 1,182 | 151 | 1,333 | Verified |
| Extra completion reply | 2 | 2,456 | 173 | 2,629 | Verified |

This reduced text tokens by **49.30%**.

## browser_.py

### Skip InlineTextBox duplicates

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 1,049 | 1,050 | 1 | 0.10% |

This reduced model-context tokens by **0.10%**.

### Keep input-field text local

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 1,049 | 1,146 | 97 | 8.46% |

This reduced model-context tokens by **8.46%**.

### Compact descriptions (verbose AX baseline)

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 1,049 | 11,053 | 10,004 | 90.51% |

This reduced model-context tokens by **90.51%**.

## observations_.py

### Change summaries (3 updated views)

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 2,382 | 3,147 | 765 | 24.31% |

This reduced model-context tokens by **24.31%**.

### 40-control working view (4 views)

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 3,431 | 71,776 | 68,345 | 95.22% |

This reduced model-context tokens by **95.22%**.

### 30-entry text-change limit (4 views)

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 3,431 | 8,306 | 4,875 | 58.69% |

This reduced model-context tokens by **58.69%**.

### Local search in batches of 40

| Mode | With optimization: model-context tokens | Without optimization: model-context tokens | Tokens saved | Reduction |
| :--- | ---: | ---: | ---: | ---: |
| Browser fixture | 1,493 | 17,827 | 16,334 | 91.63% |

This reduced model-context tokens by **91.63%**.

## Browser workflow improvements — November 2, 2026

20 runs per workflow in isolated Chrome, using scripted model replies and the
GPT-OSS tokenizer. Counts include system/request/history text and action/reply
text, excluding chat framing and hidden reasoning. No model API calls were made.
Before: engine `72db9b0`. After: checked groups, shorter instructions, and compact history.

| Workflow | Model calls before → after | Input text tokens before → after | Output text tokens before → after | Total text tokens before → after |
| :--- | ---: | ---: | ---: | ---: |
| Three-field profile and save | 5 → 2 | 3,707.8 → 1,501.2 | 94.4 → 105.2 | 3,802.2 → 1,606.4 |
| Search and location filters | 4 → 2 | 2,767.4 → 1,416.0 | 69.0 → 79.4 | 2,836.4 → 1,495.4 |
| Profile with a supplied 100-word note | 5 → 2 | 4,466.5 → 1,752.7 | 201.6 → 213.4 | 4,668.1 → 1,966.1 |

Total text tokens fell by **57.8%**, **47.3%**, and **57.9%**, respectively.
Model decisions fell by **60%**, **50%**, and **60%**.

| Workflow | Before: median local seconds | After: single actions | After: grouped actions | Verified grouped runs |
| :--- | ---: | ---: | ---: | ---: |
| Three-field profile and save | 0.5578 | 0.3225 | 0.3435 | 20/20 |
| Search and location filters | 0.3559 | 0.2184 | 0.2575 | 20/20 |
| Profile with a supplied 100-word note | 0.5393 | 0.2920 | 0.3227 | 20/20 |

Times exclude model inference and network waiting. Groups add local checks and
were slower than current single actions locally; fewer model calls are expected
to reduce real API waiting, but that live speedup has not been measured.

All 60 grouped runs saved the exact expected values, with **zero wrong-target
actions and zero duplicate submissions**. A separate delayed-filter check used
three decisions: group, local wait, and evidence-based reply. Replaced nodes,
changed parents, disabled controls, cancellation, and uncertain actions stopped
remaining work. Scripted replies do not measure live model reliability or
performance against other agents.

Tokenizer: `openai/gpt-oss-120b`, revision
`b5c939de8f754692c1647ca79fbf85e8c1e70f8a`. Repeat commands are in
[ARCHITECTURE.md](ARCHITECTURE.md#browser-fixture-checks).

## Browser continuation — November 3, 2026

20 runs per workflow, using scripted replies and the same GPT-OSS tokenizer as above.
Counts include the cancelled first attempt. Before (`a24e99b`), the original request
was reissued because progress was lost; after, `/continue` uses the checkpoint.
These are local text counts, not provider-reported API usage.

| Interrupted workflow | Input text tokens before -> after | Output text tokens before -> after | Total text tokens before -> after | Model calls before -> after |
| :--- | ---: | ---: | ---: | ---: |
| Stop after the first field | 2,595.25 -> 2,589.55 | 412.20 -> 390.55 | 3,007.45 -> 2,980.10 | 3 -> 3 |
| Stop with a replaced next field | 2,595.25 -> 2,589.75 | 412.20 -> 390.55 | 3,007.45 -> 2,980.30 | 3 -> 3 |
| Stop, then delayed confirmation | 3,507.10 -> 3,547.60 | 432.20 -> 410.55 | 3,939.30 -> 3,958.15 | 4 -> 4 |

Total text tokens decreased by **0.91%** and **0.90%** in the first two cases,
and increased by **0.48%** with delayed confirmation. Model-call savings: **0%**.
Token usage was effectively unchanged; this is a recovery improvement.

| Interrupted workflow | Input events before -> after | Verified runs before / after | Median local seconds before -> after |
| :--- | ---: | ---: | ---: |
| Stop after the first field | 4 -> 3 | 20/20 / 20/20 | 0.7997 -> 0.8249 |
| Stop with a replaced next field | 4 -> 3 | 20/20 / 20/20 | 0.6655 -> 0.8297 |
| Stop, then delayed confirmation | 4 -> 3 | 20/20 / 20/20 | 1.1597 -> 1.2891 |

Field input events decreased by **25%** in all three workflows. Both versions
finished all 60 runs with exact saved values, zero wrong-target actions, and
zero duplicate submissions. A separate uncertain-submit check sent the fixture
submission once, then blocked a model-requested repeat during inspection.

Local times exclude model inference, network waiting, and token counting.
No speedup was demonstrated; these were separate captures on the same laptop.
No live API calls or personal accounts were used. Scripted replies do not test
live model reliability. Recovery remains in memory and is cleared on app exit.

## Windows working view — November 4, 2026

Scripted replies with a simulated 181-control window and a real temporary text
file. Counts include model message text, serialized tool definitions, and
scripted tool-call text using the GPT-OSS tokenizer above. They exclude provider
framing and reasoning tokens. The full-view baseline uses the same controller.

| Workflow | Full input + output | Compact input + output | Model calls | Extra searches | Total text-token reduction |
| :--- | ---: | ---: | ---: | ---: | ---: |
| Direct file, no open window | 1,020 + 50 | 1,020 + 50 | 1 to 1 | 0 | 0% |
| Confirm changes, target omitted | 5,712 + 38 | 4,281 + 60 | 2 to 3 | 1 | 24.5% |
| Create a file and click Apply | 8,746 + 88 | 4,674 + 88 | 3 to 3 | 0 | 46.1% |

Both views passed the file and simulated click checks. The compact view used
an extra decision when Apply was absent. A separate native Windows fixture
checked text entry and target handling. These runs did not measure live model
success, end-to-end latency, or a matched Windows MCP comparison.

Run the offline comparison with the optional benchmark dependency and the local tokenizer:

```powershell
python tests/desktop_context_benchmark_.py --tokenizer C:\path\to\tokenizer.json
```

## Smaller browser view experiment — November 5, 2026

The existing 40-control default is retained. An isolated benchmark policy tried
eight controls, retained same-name alternatives from the original view, and used
existing local search to expand to up to 40 matches. Five repeats across two
control-order/name variants produced 70 runs per policy. The second variant was
withheld during policy definition; scripted variants do not establish live model
generalization. All model replies were scripted and no API quota was used.

Both policies completed **60/60 normal runs** and safely stopped **10/10 replaced-node
runs**. Counting the guarded stops as unfinished gives **60/70 completed** for each
policy. There were **zero wrong-target events, duplicate submissions, and false
completion replies** in the fixtures. Costs include those unfinished attempts.

| Case | Current input / output tokens | Small input / output tokens | Calls current -> small | Searches / expansions current -> small | Total text-token reduction |
| :--- | ---: | ---: | ---: | ---: | ---: |
| simple | 1,830.4 / 47.6 | 1,830.4 / 47.6 | 3 -> 3 | 0 -> 0 | 0.00% |
| crowded | 6,885.2 / 85.6 | 3,990.6 / 85.6 | 5 -> 5 | 2 -> 2 | 41.52% |
| unchanged | 2,763.4 / 47.6 | 3,931.6 / 85.6 | 3 -> 5 | 0 -> 2 | -42.91% |
| omitted | 2,771.2 / 47.8 | 4,530.9 / 81.8 | 3 -> 5 | 0 -> 2 | -63.63% |
| duplicate | 2,833.0 / 48.0 | 3,978.0 / 86.0 | 3 -> 5 | 0 -> 2 | -41.06% |
| dialog | 2,789.0 / 48.0 | 3,085.0 / 67.0 | 3 -> 4 | 0 -> 1 | -11.10% |
| replaced | 1,865.0 / 36.0 | 3,114.0 / 74.0 | 2 -> 4 | 0 -> 2 | -67.70% |

The smaller view used **13.08% more total text tokens** across all runs.
Negative reductions in the table mean increased token use. Search/expansion
counts refer to the same find_elements calls and should not be added together.
All retry counts were zero. Counts use the GPT-OSS tokenizer recorded above,
covering system/request/history text and scripted action/reply text.
Provider framing and hidden reasoning are excluded.

| Case | Median local seconds, current -> small |
| :--- | ---: |
| simple | 0.1505 -> 0.1547 |
| crowded | 0.3167 -> 0.2894 |
| unchanged | 0.1603 -> 0.2053 |
| omitted | 0.1681 -> 0.2308 |
| duplicate | 0.1581 -> 0.2253 |
| dialog | 0.1557 -> 0.1837 |
| replaced | 0.1051 -> 0.1633 |

Times cover the local scripted agent loop and browser operations. They exclude
live model inference/network time, fixture reset, and token counting. Policy
order alternated between repeats. These measurements do not demonstrate a
live-agent speedup or establish success-rate equivalence on general websites.

### Playwright MCP observation reference

Playwright MCP **0.0.84** was run headlessly with Chrome and `--isolated`, using a
temporary localhost server with the same fixture HTML and a fresh browser context.
The server reported Playwright version `1.65.0-alpha-2026-10-30`. The initial attempt
to set content via browser_run_code failed because that tool was unavailable;
fixture setup then used browser_navigate. All 14 initial snapshots were captured.

| Fixture | Initial MCP snapshot text tokens, two variants |
| :--- | ---: |
| simple | 130–133 |
| crowded | 1170–1170 |
| unchanged | 360–360 |
| omitted | 360–360 |
| duplicate | 385–385 |
| dialog | 358–358 |
| replaced | 359–359 |

The MCP tools/list JSON contained **5,417 locally counted text tokens**. Snapshot
counts include the textual tool response. These observation counts are separate
from full task costs. An end-to-end MCP agent comparison was not run because a
matched model/tool-call driver was not implemented in this experiment. No claim
of outperforming Playwright MCP follows from these results.

Run the experiment with the optional benchmark dependency and a local tokenizer.

```powershell
python tests/browser_context_benchmark_.py --repeat 5 --tokenizer C:\path\to\tokenizer.json
# Optional snapshot reference using an installed Playwright MCP cli.js
python tests/browser_context_benchmark_.py --mcp-cli C:\path\to\mcp\cli.js --tokenizer C:\path\to\tokenizer.json
```

## Shorter working prompts — November 8, 2026

[You don't need long context](https://arxiv.org/abs/2611.05306) explores keeping
the current working context short while allowing selective access to earlier
information. Chexsa applies that idea by offering tools when they can run and
sending each useful part of the current browser view once.

### Desktop

| Scripted task | Input tokens before | Input tokens after | Input tokens saved | Model calls |
| --- | ---: | ---: | ---: | ---: |
| Create a file with no window | 1,020 | 689 | 32.5% | 1 → 1 |
| Find an omitted button and apply | 4,281 | 4,281 | 0% | 3 → 3 |
| Create a file, then apply in an open window | 4,690 | 4,690 | 0% | 3 → 3 |

All three tasks completed on both versions. Scripted output tokens stayed at
54, 60, and 92 respectively. A separate regression covers saving a file after
a window action and continuing with the correct previous window reading.

### Browser

| Scripted case | Input tokens before | Input tokens after | Input tokens saved | Model calls |
| --- | ---: | ---: | ---: | ---: |
| First decision before Chrome opens | 402 | 88 | 78.1% | 1 → 1 |
| Standard browser view, 28 runs | 86,488 | 82,432 | 4.7% | 88 → 88 |
| Experimental smaller view, 28 runs | 97,629 | 90,509 | 7.3% | 124 → 124 |

For each browser view, both versions completed 24 runs and safely stopped
on all four replaced-control runs. There were zero wrong targets or duplicate
submissions. Searches stayed at 8 for the standard view and 44 for the smaller
view. Scripted output tokens stayed at 15, 1,434, and 2,102 respectively.
The standard view remains the default and used fewer tokens overall.

Baseline: 7cc500b. Counts use the local GPT-OSS tokenizer and include scripted
replies, desktop tool definitions, and all guarded stops. The standard Chrome
fixture totals took 11.18 and 7.24 seconds locally under varying test load.
These results measure fixture outcomes and text usage. Live latency, model
reliability, and provider billing need separate measurements.

## Read one section before editing a file

| Scripted edit | Whole-file input tokens | Section input tokens | Input tokens saved | Model calls |
| --- | ---: | ---: | ---: | ---: |
| Change the Fibonacci function | 3,716 | 2,155 | 42.0% | 2 → 2 |
| Shorten the Word conclusion | 3,914 | 2,114 | 46.0% | 2 → 2 |

Both versions saved and verified the same edit. Scripted outputs used 55 and 58
tokens respectively. The quoted exact-replacement fixture also verified a save
in one decision. Local GPT-OSS counts at d0c2beb compare full-file and excerpt
inputs with the same tools and scripted replies.

## Copy a Word section locally

Both scripted runs copied the same conclusion to a verified text file.

| Method | Input tokens | Output tokens | Total tokens | Model calls | Local time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Pass the text through the model | 3,112 | 1,011 | 4,123 | 2 | 0.077 s |
| Copy the text locally | 1,204 | 37 | 1,241 | 1 | 0.078 s |

Local copying used **69.9% fewer total text tokens**. These are local GPT-OSS
counts and scripted timings. Live API latency needs a separate measurement.

Run the fixture with `python tests/desktop_context_benchmark_.py --handoff --tokenizer PATH`.

## Canvas assignment to Word outline

A scripted request opened the selected assignment, read it with one Canvas API
request, and saved a verified Word outline after one model decision. The fixture
checked the saved text and the destination link. It used a mocked Chrome page,
Canvas API, and model. A matched live UI run is still needed to compare tokens
and elapsed time.
