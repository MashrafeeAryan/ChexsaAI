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

## Limits and future work

Both controllers allow at most 10 model decisions per request. SDK retries are off,
API requests time out after 30 seconds, and uncertain input errors stop the run.
Repeated identical actions without a relevant observation change stop as well.
The same browser tab or app state can be reused for a later request, but task history
is not persisted or automatically resumed.

Voice, automatic engine routing, skill storage/reuse, shared skills, advanced browser
actions, screenshots, and general outcome verification are future work. The rebuild
has no Gmail-specific automation. Lower prompt size on a fixture is not proof of
lower billed tokens for all tasks.
