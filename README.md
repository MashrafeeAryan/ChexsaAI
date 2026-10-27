<div align="center">
ChexsaAI

**Your browser. Your desktop. Your next task.**

A small command-line AI assistant for Chrome and Windows apps. (Plan to develop in app)

![Windows](https://img.shields.io/badge/Windows-0078D4?style=flat-square)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=flat-square)
![Terminal](https://img.shields.io/badge/Interface-Terminal-0D9488?style=flat-square)

[Get started](#get-started) &nbsp; / &nbsp; [Run Chexsa](#run-chexsa) &nbsp; / &nbsp; [Explore the code](#explore-the-code)

</div>

---

## Why I am building ChexsaAI

I am building ChexsaAI to automate browser and desktop tasks at the lowest cost
I can achieve. I am focusing on **fewer tokens, faster execution, and reliable
results** with low-cost models.

I am working on benchmarks across different tasks, models, and agents to compare
cost, speed, token use, and success rates.

Long term, I want ChexsaAI to work for hours without supervision.

## Get started

You need **Windows** and **Python 3.11 or newer**.

### 1. Clone the repository

Open PowerShell and run:

```powershell
git clone https://github.com/MashrafeeAryan/ChexsaAI.git
cd ChexsaAI
```

### 2. Install

Run these commands from the repository folder:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

### 3. Connect your model

Create a `.env` file beside `cli_.py`. For Groq:

```dotenv
LLM_API_KEY=your-key
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_MODEL=openai/gpt-oss-120b
```

> Keep your API key private. `.env` is excluded from Git.

Other OpenAI-compatible providers can use their own base URL and model. Desktop
mode requires a model with native tool calling. `LLM_PROVIDER` is not used.

## Run Chexsa

Choose a mode. Browser and desktop run separately for now.

### Desktop

```powershell
.\.venv\Scripts\chexsa.exe
```

### Browser

```powershell
.\.venv\Scripts\chexsa.exe browser
```

Chexsa waits for your request before opening an app.

| Mode | Example request |
| :--- | :--- |
| **Browser** | Open YouTube and search for JavaScript tutorials. |
| **Desktop** | Write 300 words in Microsoft Word. |

With the virtual environment activated, use `python cli_.py desktop`
for desktop mode or `python cli_.py browser` for browser mode.

**Leave the chat:** type `exit` or `quit`. **Cancel a request:** press `Ctrl+C`.
Windows may require you to bring the app to the front before keyboard input continues.

---

## Explore the code

| Guide | What you will find |
| :--- | :--- |
| [File guide](file_use.md) | A simple explanation of each file. |
| [Architecture](ARCHITECTURE.md) | How the browser and desktop pieces connect. |

The rebuilt Python filenames end in `_`, such as `cli_.py`.
