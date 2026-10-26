# Current ChexsaAI architecture

The rebuild uses plain functions and dictionaries. There are seven runtime Python
files. The user chooses desktop or browser mode; the model does not switch engines.

```text
cli_.py: user request
    |
    +-- desktop (default)
    |     desktop_agent_.py: ask the model for one tool call
    |           -> desktop_.py: validate and execute
    |           -> read the app again -> verify -> next model decision
    |
    +-- browser
          agent_.py -> browser_.py: read the page
                    -> observations_.py: select current controls and changes
                    -> llm_.py: ask for one JSON action
                    -> browser_.py: validate and execute
                    -> read again -> next model decision
```

## Browser observations and targets

Playwright manages Chrome and navigation. Public CDP calls read the accessibility
tree and identify controls by Chrome's `backendDOMNodeId`. The collector retains
names, roles, parent regions, state, values, and ordinary text locally. Duplicate
names keep distinct node IDs. Headings supply page text rather than click targets.

`observations_.py` compares nodes on the same page and document. It selects up to
40 current controls, favoring changed controls, focus, the recent target, dialogs,
and request matches. Each description stays intact. Added and removed text lists
are limited to 30 entries each; removed-control lists are limited to 40, with
omission counts. These limits count records, not characters or tokens. Values stay
local; the model is told which IDs changed. A new document starts a fresh view.

`find_elements` searches all locally collected controls and returns up to 40
matches, with an offset for more. The model can target only IDs shown in the current
view or search results. Node resolution checks the latest observation, document,
attachment, and supported control behavior. Click or type consumes the observation;
the loop reads again before another action. It never substitutes a same-name node.
The current collector reads the selected tab's accessibility tree; full frame and
shadow-DOM coverage is not an acceptance claim of this rebuild.

Each model request includes the original goal and action results, rather than all
previous page snapshots. Text entry reads back the resulting value. Click dispatch
alone does not prove task completion. Browser completion is still a model judgment
based on fresh page data, not an independent general-purpose verifier.

## Desktop observations and targets

`desktop_.py` uses pywinauto and Windows UI Automation. It retains exact control
wrappers locally and shows the model Windows runtime IDs, names, types, and state.
Old observations and detached, covered, or disabled targets are rejected. Native
Invoke/Value interfaces are preferred; guarded mouse and keyboard input are fallbacks.
Keyboard fallback requires the intended window and editor to have focus. New text
replaces the full field and must match a stable read-back. Keyboard fallback rejects
emoji and other supplementary characters before editing.

`desktop_agent_.py` advertises open_app, observe, click_control, type_text, press_key,
and reply as native model tools. App lookup uses PATH and Windows App Paths, not
model-provided shell commands. A replaced startup window can be recovered only
within the known app process; ambiguous windows stop execution.

For writing requests, completion requires a verified write and another fresh text
read. A single explicit numeric word count is checked before typing and at completion,
using whitespace-separated words. Only the latest rejected draft stays in model
history for correction. Successfully entered text is not repeatedly resent in history.
New-document creation is currently a model instruction, not a deterministic safeguard.
The live Word end-to-end workflow is still pending validation.

## Limits and future work

Both controllers allow at most 10 model decisions per request. SDK retries are off,
API requests time out after 30 seconds, and uncertain input errors stop the run.
Repeated identical actions without a relevant observation change stop as well.
The same browser tab or app state can be reused for a later request, but task history
is not persisted or automatically resumed.

Voice, automatic engine routing, skill storage/reuse, shared skills, advanced browser
actions, screenshots, and general outcome verification are future work. The rebuild
has no Gmail-specific automation. Lower prompt size on a fixture is not proof of
lower billed tokens for all tasks; see TEST_NOTES_.md for measured results and limits.
