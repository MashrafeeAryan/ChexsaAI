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
Windows may require you to bring the app to the front before keyboard input can continue.

Read [file_use.md](file_use.md) for each file's purpose and
[ARCHITECTURE.md](ARCHITECTURE.md) for the current flow. Future goals are in
[PROJECT_GOALS_.md](PROJECT_GOALS_.md).
