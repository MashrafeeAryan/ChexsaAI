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

- Choose **desktop**, **browser**, or **gmail**. Modes are explicit for now.
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
while keeping connections. The sidebar shows the current conversation only;
there is no saved chat archive yet. Stop and email-send review appear when needed.

The terminal launch commands are independent of this interface and keep their
existing behavior. The UI uses Tk's PNG support, so terminal users do not need a
new image library.

## Settings and files survive app updates

Open **Settings** to enter an API key, API address, and model name. The key is
masked. Blank fields use your existing `.env` or environment settings. Saving
settings resets API clients so later tasks use the changed account or model.

The app stores settings at `%LOCALAPPDATA%\Chexsa\settings.dpapi`. Windows encrypts
them for this Windows user. Gmail tokens stay in `%LOCALAPPDATA%\Chexsa\gmail`.

Files created by the desktop app with relative filenames go under
`%LOCALAPPDATA%\Chexsa\output`. An explicitly requested absolute path still works.
The terminal keeps its existing repository `output/` default.

Chat stays in memory and is not automatically saved. Requested task and email
contents still go to your configured model provider; encryption of local settings
does not make those model requests local.

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
python -m compileall -q app_.py app_runtime_.py plugins tests
```

The app tests use fake task and audio responses. Real Tk widgets check chat,
cancellation, layout, microphone input review, and clean shutdown. Windows token
encryption is tested locally. An idle production-worker smoke check verifies
startup and shutdown without opening personal apps or calling a model. These
checks do not establish live Gmail or microphone recognition accuracy.
