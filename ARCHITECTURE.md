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
                    -> llm_.py: ask for one JSON action
                    -> browser_.py: validate and execute
                    -> read again -> next model decision
```

## Future work

- **Voice:** improve wake-word detection and microphone reliability.
- **Automatic mode choice:** let Chexsa choose browser or desktop tools.
- **Saved skills:** remember successful steps and reuse them.
- **Shared skills:** learn useful workflows from other users.
- **More browser tools:** add tabs, scrolling, uploads, and other actions.
- **Screenshots:** let the model use page images when needed.
- **Better result checks:** confirm that the whole task succeeded.
- **Saved progress:** continue an interrupted task safely.
