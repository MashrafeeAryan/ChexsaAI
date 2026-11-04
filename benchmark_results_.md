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
