# ChexsaAI

A small command-line AI agent for Chrome and Windows apps. The browser and
desktop engines run separately for now. The rebuilt Python files end in `_`.

## Set up

Use Windows, Python 3.11 or newer, and installed Google Chrome for browser tasks.
Word tasks also require Microsoft Word. From the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Create `.env` beside `cli_.py` with your existing Groq settings:

```dotenv
LLM_API_KEY=your-key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
```

The model must support native tool calls for desktop tasks. Other OpenAI-compatible
providers can use their own base URL and model. `.env` stays out of Git.
`LLM_PROVIDER` is not used by the rebuild.

## Run

Desktop mode:

```powershell
.\.venv\Scripts\chexsa.exe
```

Browser mode:

```powershell
.\.venv\Scripts\chexsa.exe browser
```

You can also run `python cli_.py` or `python cli_.py browser` with the virtual
environment activated. Type `exit` or `quit` to close; Ctrl+C cancels a request.
Starting the CLI does not open Chrome or Word. It waits for your request.

Browser example: `Open YouTube and search for JavaScript tutorials.`

Desktop example: `Open Word and write a 300-word essay about how AI impacts humans.`
This is the intended writing workflow. The real Windows text-field fixture passes;
the complete live-model-to-Word workflow still needs verification. Windows may
require you to bring the app to the front before keyboard input can continue.

## What is implemented

- Browser: open a URL, observe the page, search collected controls, click exact
  Chrome nodes, and replace text with read-back verification.
- Large pages: collect the complete page locally, send at most 40 current controls
  plus bounded change lists, and let the model search omitted controls.
- Desktop: open an installed app, read its controls, click, replace text, send
  supported keyboard shortcuts, and verify entered text and requested numeric
  word counts. The desktop must be available for keyboard or mouse input.
- Both loops stop after 10 model decisions. API requests have a 30-second timeout
  and no automatic retries. Tests use fake model replies unless explicitly stated.

The browser connects to Chrome's debugging port 9222 if available. Otherwise it
opens Chrome with a persistent profile at `%LOCALAPPDATA%/Chexsa/chrome`.
Website logins in that profile can survive restarts. This does not copy logins
from a regular Chrome profile. Exit releases the browser connection; an owned
Chrome process may close, and desktop documents are left open.

The browser model currently has no dedicated tab, scroll, upload, select-option,
checkbox, batch, screenshot, or email-verification tools. Some simple page controls
can still be operated with clicks. Voice, automatic browser/desktop routing, saved
skills, shared learning, and task persistence are not implemented in the rebuild.
The old implementation is available in Git history.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
.\.venv\Scripts\python.exe tests/browser_changes_integration_.py
```

The Chrome fixture uses a temporary headless profile and a fake model; it does not
read personal tabs or spend API quota. CI runs it and the unit suite on Windows.
`tests/desktop_actions_integration_.py` contains manual disposable-window and Word
tests; running that full script can bring windows to the front. It uses no AI API.

Read [file_use.md](file_use.md) for each file's purpose and
[ARCHITECTURE.md](ARCHITECTURE.md) for the current flow. Recorded measurements are
in [TEST_NOTES_.md](TEST_NOTES_.md); future goals are in
[PROJECT_GOALS_.md](PROJECT_GOALS_.md).
