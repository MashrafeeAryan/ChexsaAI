# Current ChexsaAI architecture

The rebuild uses plain functions and dictionaries. The user chooses desktop or
browser mode; the model does not switch engines. `voice_.py` accepts spoken
requests, calls the selected agent, and speaks its response.

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
                    -> llm_.py: ask for one action or a checked action group
                    -> browser_.py: validate, execute, and check locally
                    -> read again -> next model decision
```

## Browser efficiency

- **Checked groups:** one model decision can request up to five independent actions. Typing can be followed by one final click.
- **Fresh targets:** all IDs must have been shown to the model. Each action still uses Chrome's exact node and a fresh reading.
- **Stop on changes:** navigation, added or removed controls, or changes to planned targets stop the remaining actions. Reordering the same nodes is allowed.
- **Keep progress:** a stopped group reports its completed count and remaining count. An uncertain action stops the task without an automatic retry.
- **Wait locally:** `wait_for` checks for page text or an observed control's enabled/checked state. The model does not need to poll repeatedly.
- **Short waits:** waits default to three seconds and allow at most five seconds, apart from a Chrome command already in progress. Stop is checked between polls and actions.
- **Smaller history:** long text copied from the original request can be represented by character offsets. The original request and new model-generated text are preserved.
- **Same entry points:** the terminal, desktop app, and voice mode all use this browser agent.

Example model action:

```json
{
  "action": "batch",
  "actions": [
    {"action": "type", "backend_node_id": 12, "text": "Example"},
    {"action": "click", "backend_node_id": 18}
  ]
}
```

A completed click only means input was sent. Fresh page evidence is still needed
before reporting that the user's task succeeded. Groups are deliberately
conservative: even unrelated added or removed controls can require another model
decision. Autocomplete choices and dependent fields should be handled separately.

## Browser fixture checks

```powershell
python -m unittest discover -s tests -p "test_*.py" -q
python tests/browser_changes_integration_.py
python tests/browser_workflows_integration_.py
```

The Chrome fixtures use temporary browser profiles and scripted model replies.
They do not use personal accounts or live model API quota. The workflow checks
cover forms, search/filter controls, duplicate buttons, changed targets, delayed
updates, cancellation, and uncertain actions.

For optional offline token counts, install `.[benchmark]` and pass
`--tokenizer C:\path\to\tokenizer.json` to the workflow check. `--repeat 20`
repeats each scenario. Counts cover serialized system/request/history text and
scripted action/reply text; they are not provider-reported total API usage.

## Future work

- **Voice:** improve wake-word detection and microphone reliability.
- **Automatic mode choice:** let Chexsa choose browser or desktop tools.
- **Saved skills:** remember successful steps and reuse them.
- **Shared skills:** learn useful workflows from other users.
- **More browser tools:** add tabs, scrolling, uploads, and other actions.
- **Screenshots:** let the model use page images when needed.
- **Better result checks:** confirm that the whole task succeeded.
- **Saved progress:** continue an interrupted task safely.
