# Use and develop the Chexsa desktop app

The window uses the same browser, desktop, and Gmail engines as the terminal.
There is no website or separate web server.

## Start the app

From the repository folder:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[gmail,voice]"
.\.venv\Scripts\python.exe app_.py
```

Gmail and voice are optional. For chat with browser and desktop tools only,
`python -m pip install -e .` is enough. After installing, `chexsa-app` also opens
the window. The existing `chexsa` and `python cli_.py` commands still work.

## Use the window

- Choose **Desktop**, **Browser**, **Gmail**, or **Visual desktop**.
- Type a request and press **Enter** or **Send request**. Shift+Enter adds a line.
- Read progress in the status line and the result in the chat.
- **Stop** prevents the next model call or action at a safe boundary.
- A network request, recording, app launch, or input already in progress may
  finish before Stop takes effect. Stop does not undo actions or prove they failed.
- A busy app runs one task at a time, so requests cannot compete for app focus.
- Closing waits for the current operation and releases connections on their
  owning worker thread. It leaves desktop documents open.

Example input: **Open a website and search for a topic** in browser mode.
Output: progress and a result from the existing browser agent; the window itself
does not decide which page control to click.

## Appearance and fresh chats

The app has a sidebar, a mascot greeting, and a rounded message composer. In
**Settings**, choose **Foxy** the fox, **Fluffy** the golden retriever, or **Bruhhh** the robot and set your display name.
These preferences stay local and are not sent to the model.

Suggestion buttons fill an editable request and choose its mode; they do not run
the task. **New chat** clears the current display and selected desktop/Gmail targets
while keeping connections. Double-click a saved chat to read its messages.
Use **Chat options** to rename or delete it. Stop and email-send review appear when needed.

The terminal launch commands are independent of this interface and keep their
existing behavior.

## Settings and files survive app updates

Open **Settings** to enter an API key, API address, and model name. The key is
masked. Blank fields use your existing `.env` or environment settings. Saving
settings resets API clients so later tasks use the changed account or model.

The app stores settings at `%LOCALAPPDATA%\Chexsa\settings.dpapi`. Windows encrypts
them for this Windows user. Gmail tokens stay in `%LOCALAPPDATA%\Chexsa\gmail`.

Files created by the desktop app with relative filenames go under
`%LOCALAPPDATA%\Chexsa\output`. An explicitly requested absolute path still works.
The terminal keeps its existing repository `output/` default.

Windows encrypts saved chat text in the local chat database under the same folder.
Requested task and email contents go to your configured model provider.

## Edit a saved file

Use **Desktop** in the app or terminal. For example:

1. Ask **Create fibonacci.py with a function called fib that generates the Fibonacci series.**
2. In the same chat, ask **Edit that same file so fib rejects negative inputs.**
3. Chexsa reads the function, applies the exact change, checks Python syntax,
   and verifies the saved file.

You can also name an existing file, such as **In note.txt, replace "Monday" with
"Tuesday".** Relative paths point into the output folder. Give a full path for
a file elsewhere. Give the filename when the last request touched several files.
File references last for the current session or chat.

Direct edits support UTF-8 text, Markdown, Python, and Word documents. Save and
close a Word document first. A Word edit changes one plain text run in a body
paragraph, keeping its formatting and the rest of the document. For example,
ask **Shorten the conclusion in report.docx.** Chexsa stops if the old text is
ambiguous or the saved file changed after reading.

## Copy saved text between files

Use **Desktop** and ask **Copy the Conclusion from report.docx to summary.txt.**
You can also ask **Turn notes.md into a Word file.** In the same running chat,
**that file** works when there is one recent file.

Chexsa sends the model the filenames and section name. Python copies the text
locally and checks the new file. An existing destination stays untouched.
Copies support UTF-8 text, Markdown, and Word body paragraphs as plain text.
A named section uses a Word heading or a Markdown heading starting with #.
For a plain Word label, Chexsa copies the first nonempty paragraph below it.
Name a full path to work outside the output folder.

## Canvas assignments

Use **Browser** in the app or terminal. Canvas file submissions use your school's
Canvas API. Update your local install with `python -m pip install -e .`. Add these
settings to your local `.env`, then restart Chexsa.

```dotenv
CANVAS_URL=https://your-school.instructure.com
CANVAS_TOKEN=your-canvas-access-token
```

Use a token for your own student account if your school provides one. The school
address must match the assignment link. Keep the token in `.env`.

| Command | What it does |
| --- | --- |
| `/canvas open LINK` | Opens the assignment in Chrome. Sign in there if Canvas asks. |
| `/canvas view LINK` | Reads the title and written instructions. |
| `/canvas draft LINK` | Saves a draft and shows the file to review. Add `\| YOUR NOTES` after the link to supply material. |
| `/canvas attach LINK \| FULL_FILE_PATH` | Shows an existing file for review. Use this again after editing a draft. |
| `/canvas submit` | Sends the reviewed file and checks the Canvas receipt. |
| `/canvas status LINK` | Checks the submission time and filenames. Omit the link to check the last assignment in this chat. |

Replace `LINK` with the full assignment URL. For example, use a link ending in
`/courses/123/assignments/456`. Drafting uses your configured model and sends it
the assignment instructions, rubric, and notes you supplied. Review the saved
file before submitting. Canvas already-submitted, locked, and group assignments
and assignments with a pledge or LockDown Browser requirement use Canvas's own
submission page. This workflow covers individual file uploads up to 25 MiB.

The local tests use fake Canvas and storage responses. They cover the upload,
receipt, file changes after review, and a lost response. Check the status or
open Canvas when the receipt is uncertain.

[Canvas submissions API](https://developerdocs.instructure.com/services/canvas/resources/submissions)
and [Canvas upload steps](https://developerdocs.instructure.com/services/canvas/basics/file.file_uploads).

## Visual desktop

1. Open the window you want Chexsa to work in.
2. In **Settings**, set **Vision model** to a model that accepts images at your API
   address. You can also set `VISION_MODEL` in `.env`. This uses your configured
   API address and key.
3. Choose **Visual desktop**, write a request, and accept the screenshot notice.
4. Switch to the target window within five seconds. To stop, switch back and
   press **Stop**.

Example request: **Type Hello in the blank editor.** The model sees the current
window image, chooses a point or keyboard action, then checks a new image for
the result. It can move, click, double-click, right-click, scroll, type, and press
common Ctrl/Shift shortcuts. **Desktop** uses Windows controls as before.

Each request stays in one foreground window. Keep it visible and leave the mouse
and keyboard free during input. Covered points, changing screens, and a switch
to another window can stop the request. If the window spans monitors, the preview
covers its visible area on the nearest monitor. Screenshots go to your vision model
and stay in memory for the request. Chat history saves text only.

The disposable native test uses scripted replies and makes zero model API calls:

```powershell
python tests/desktop_actions_integration_.py --visual
```

The native input portion needs an unlocked, interactive Windows desktop.
Live vision accuracy, API latency, and comparative cost against Windows MCP
require separate benchmarks.

## Microphone and spoken replies

- **Microphone** records one phrase and puts its text into the message editor.
- You can say **Hey Chexsa, ...** or just the command.
- Review or edit the text, then press **Send request**. Recording does not run it.
- **Read reply** speaks the last result using Windows speech.
- **Stop** cancels playback or discards a recording when the current recording or
  transcription finishes. Closing also stops audio.

This app version has on-demand dictation, not an always-listening wake-word loop.
It reuses the existing Google speech recognition service, which needs an internet
connection. It does not yet use a local wake model or local transcription.
Use `python voice_.py browser`, `desktop`, or `gmail` for the existing spoken-agent
loop. Microphone accuracy and permissions still require testing on your device.

## Gmail

Click **Connect Gmail** to choose the Google Desktop OAuth JSON on the UI thread.
Google sign-in runs in the browser while the app remains responsive. The same
development credentials are required as in the [Gmail guide](plugins/gmail/GMAIL_SETUP_.md).
Live account sign-in has not been verified without those credentials.

Ask to create or edit a draft. A send request shows the exact message for review;
**Send reviewed email** submits that reviewed version. The existing changed-draft
and duplicate-send checks remain in the Gmail plugin.

## Develop without rebuilding an installer

1. Install the dependencies once.
2. Run `python app_.py` directly from the checkout.
3. Edit the relevant Python file, close the app, and run it again.
4. Run the focused checks for the changed behavior.
5. Publish a new app release when changes are ready, not after every local edit.

The UI lives in `app_.py`. Settings, the task worker, and audio helpers live together
in `app_runtime_.py`. Services stay under `plugins/`; small helper functions do not
need separate files. The UI exchanges plain requests and results with its worker;
Tk widgets, Playwright objects, and Windows controls are never sent across it.

## Packaging and future updates

The Python package includes the GUI entry point. A standalone Windows installer,
signed releases, and an automatic updater are future work; they are not implemented.
Any future installer should preserve the user-data paths above. Packaging must be
checked on a clean Windows machine, including optional microphone dependencies.

An updater should check a trusted release manifest, verify the downloaded release,
and install it after tasks stop. It should support recovery from a failed update.
The amount downloaded depends on packaging; a small code edit does not guarantee
a tiny user download. Keeping service folders separate helps development, but does
not create an independent plugin-update system.

## Checks

```powershell
python -m unittest discover -s tests -p "test_*.py" -q
python -m compileall -q app_.py app_runtime_.py visual_.py plugins tests
```

The app tests use fake task and audio responses. Real Tk widgets check chat,
cancellation, layout, microphone input review, and clean shutdown. Windows token
encryption is tested locally. An idle production-worker smoke check verifies
startup and shutdown without opening personal apps or calling a model. These
checks do not establish live Gmail or microphone recognition accuracy.
