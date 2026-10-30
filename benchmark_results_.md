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
