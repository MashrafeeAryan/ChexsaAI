# ✨ Chexsa

### Your personal AI that can use your computer.

For a simple explanation of every project file, read [file_use.md](file_use.md).

Chexsa is an open-source AI assistant that is being built to **see what is happening on your computer and take actions for you**.

Instead of only answering questions, Chexsa can work through a task step by step.

> You tell Chexsa what you want.  
> Chexsa figures out what to do next and gets to work.

---

## 🌸 What can Chexsa do?

Right now, Chexsa can use your browser.

You can ask it things like:

```text
Open Gemini and ask what the capital of the USA is.
```

```text
Open YouTube and search for a Java tutorial.
```

```text
Go to this website and fill out the form.
```

Chexsa looks at the page, decides what to do, performs the action, and looks again.

```text
You
 ↓
Chexsa
 ↓
See what is there
 ↓
Decide what to do
 ↓
Do it
 ↓
Repeat
```

No separate script needs to be written for every website.

---

## 🖥️ Desktop control

Chexsa is also learning how to use normal Windows apps.

The goal is to support requests like:

```text
Open Word and write a paragraph about AI.
```

```text
Open my document and add a new section.
```

Chexsa can already read many Windows buttons, menus, text boxes, and windows. Desktop actions are still being developed.

---

## 🚧 Current progress

| Feature | Status |
|---|---|
| Terminal chat | ✅ |
| Open websites | ✅ |
| Click and type | ✅ |
| Search websites | ✅ |
| Work with browser tabs | ✅ |
| Scroll pages | ✅ |
| Upload files | ✅ |
| Read webpage content | ✅ |
| "Hey Chexsa" voice commands | ✅ |
| Read Windows apps | 🚧 |
| Control Windows apps | 🚧 |
| Browser + desktop together | 🔜 |
| Choose chat, browser, or desktop from your request | ✅ |
| Check its own work | ✅ Browser verification |
| Learn repeated tasks | 🔜 |

Chexsa is still an early project, so some things will break while it grows.

---

## 💡 The idea

Most AI assistants work like this:

```text
You ask something
      ↓
AI answers
```

Chexsa is trying to work like this:

```text
You ask for something
        ↓
Chexsa understands the goal
        ↓
Chexsa uses your computer
        ↓
Task complete
```

The bigger goal is a personal AI that can work across websites, apps, and files instead of being limited to a chat box.

---

## 🌱 Where Chexsa is going

A future goal is for Chexsa to learn from tasks it has already completed.

Instead of figuring out the same workflow from scratch every time, it could save what worked and reuse it later.

```text
First time
Think through the task
        ↓
Task succeeds
        ↓
Save what worked
        ↓
Next time
Reuse it
```

This could make repeated tasks faster and more reliable.

---

## 🛠️ Getting Started

Chexsa currently works best on **Windows**.

### 1. Clone it

```bash
git clone https://github.com/MashrafeeAryan/Chexsa.git
cd Chexsa
```

### 2. Install it

```bash
pip install -e .
```

### 3. Add your AI provider

Create a `.env` file.

For an OpenAI-compatible provider:

```env
LLM_PROVIDER=openai_compatible
LLM_MODEL=your-model
LLM_API_KEY=your-api-key
LLM_BASE_URL=your-api-url
```

Or use Gemini:

```env
LLM_PROVIDER=gemini
LLM_MODEL=your-model
GEMINI_API_KEY=your-api-key
```

Never upload your API keys to GitHub.

OpenAI-compatible models use page text and element refs by default. This works
with Groq's text-only GPT-OSS models. Only set `LLM_SUPPORTS_VISION=1` if your
chosen model accepts images; this enables screenshot and coordinate actions.
Gemini enables images by default. `LLM_TIMEOUT_SECONDS` defaults to 30 seconds.

### 4. Start Chexsa

```powershell
chexsa
```

Use `--model` to choose a model for this terminal session without editing your
saved settings. For example, with a Groq API key:

```powershell
chexsa --model openai/gpt-oss-20b
```

If you ask to send an email without giving the message, Chexsa asks for it. If
you provide the message but omit a subject, it uses a short neutral subject.

Chexsa first waits for your request. Greetings and normal questions stay in chat.
Browser tasks connect to Chrome; Windows app tasks use the desktop agent.
Voice mode makes the same choice after hearing your command.

For a browser task, Chexsa reuses Chrome's debugging connection on port 9222.
A normal Chrome window without that connection cannot be attached automatically.
If needed, Chexsa starts a separate persistent profile under
`%LOCALAPPDATA%/Chexsa/chrome` and skips Chrome's first-run setup.

Chrome account sign-in/sync is not required. Sign into Gmail or other websites
once in the Chexsa profile; their saved login state is reused across sessions,
subject to the website's normal expiry and security checks. This profile does
not copy logins from your usual Chrome profile and does not use Guest mode.

Type a task at `You >`. Ctrl+C cancels a running task. Exit with `exit` or `quit`.
Chrome stays open when Chexsa disconnects. If the selected tab closes, the next
observation selects an open tab or creates a blank one. Old element refs are
rejected, so a pending action cannot silently hit a different tab.

To reuse another saved Chrome profile, add its user-data root and profile folder
to `.env`:

```env
CHEXSA_CHROME_USER_DATA_DIR=C:\path\to\your\saved-chrome-data
CHEXSA_CHROME_PROFILE=Profile 1
```

Chexsa reads that root's `DevToolsActivePort` to attach to an enabled session.
An explicit `CHEXSA_CDP_URL` takes priority. Otherwise a custom profile launches
on its own port, so it cannot accidentally attach to a different profile on 9222.

For your normal Chrome data directory, Chrome 144+ provides an opt-in route:
enable debugging at `chrome://inspect/#remote-debugging`, then allow Chrome's
connection prompt. Point the setting above at the normal user-data root.
Chexsa does not change that setting or copy your login data. See
[Chrome's connection guide](https://developer.chrome.com/docs/devtools/agents/use-cases/auto-connect).

List saved tasks or resume after observing the current browser:

```powershell
chexsa --tasks
chexsa --resume TASK_ID
```

The browser engine keeps large pages locally and sends focused regions to the
model. It supports node-bound refs, search/expansion, visual fallback, verified
results, and recovery without automatically repeating uncertain submissions.
See [ARCHITECTURE.md](ARCHITECTURE.md) for settings and behavior.

### Test your actual model

```powershell
python scripts/test_live_browser.py
```

This runs the terminal with your saved API settings, tests chat and YouTube
navigation/search, and checks the real resulting page. It uses a separate empty
Chrome profile and does not read your personal tabs. It uses API quota. Add
`--email` to test sending on a local fake inbox with a fixture recipient;
no real email is sent. Results and timings go to `.chexsa/live-smoke.json`.

Free API token limits can delay repeated tasks. Chexsa announces a short quota
wait and makes bounded retries, instead of silently waiting through SDK retries. Longer
or repeated quota failures stop with a clear result and preserve browser progress.


---


## 🎙️ Voice Mode

Chexsa can listen for **"Hey Chexsa"** and route the rest of the sentence to chat,
the browser, or the Windows desktop, just like terminal mode.

Install the optional voice tools:

```powershell
pip install -e ".[voice]"
```

Start voice mode:

```powershell
chexsa-voice
```

Or start Chrome and voice mode together:

```powershell
.\scripts\start_voice.ps1
```

Then say:

```text
Hey Chexsa, search JavaScript tutorials on YouTube.
```

You can also say only **"Hey Chexsa"** and Chexsa will listen once more for your command.

Voice mode must be running to hear the wake phrase. Speech is currently transcribed with Google Speech Recognition through the SpeechRecognition package.

---

## ✅ Tests

Run the fast unit tests:

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```

Run the isolated Chrome integration fixtures (no model key or real email needed):

```powershell
.\scripts\test_browser.ps1
```

GitHub Actions runs the unit and Chrome fixture tests on Python 3.11 and 3.12 for pushes and pull requests. The fixture suite includes 20 consecutive email workflows, delayed/refused/uncertain sends, large pages, frames, and visual targeting. It uses a scripted model; live Gmail and model-provider behavior require separate account-based validation. Version tags such as `v0.1.0` also build release packages automatically.

---

## 🗺️ Roadmap

```text
Browser control              ✅
        ↓
Windows app control          🚧
        ↓
Browser + desktop together
        ↓
Check whether browser actions worked ✅
        ↓
Recover when something fails
        ↓
Learn reusable tasks
        ↓
Personal memory
```

---

## ⚠️ Early Project

Chexsa is experimental.

It can interact with real websites and is being developed to control more of your computer. Avoid using it for anything where a wrong action could cause serious problems.

---

## 🤝 Contributing

Chexsa is open source and still growing.

Bug reports, ideas, experiments, and pull requests are welcome.

---

<div align="center">

### 🌸 Chexsa

**An AI that doesn't just tell you what to do.  
It helps do it.**

</div>
