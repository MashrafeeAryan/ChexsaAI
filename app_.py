"""Chexsa's Windows app. Run python app_.py while developing; no installer needed."""

from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from app_runtime_ import (
    load_settings,
    play_reply,
    record_message,
    run_worker,
    validate_settings,
)


def append_message(chat, speaker, text):
    """Add a readable chat entry without letting users edit earlier results."""
    chat.configure(state="normal")
    chat.insert("end", f"{speaker}\n", "speaker")
    chat.insert("end", text + "\n\n")
    chat.see("end")
    chat.configure(state="disabled")


def build_app(root=None, handlers=None, initial_settings=None):
    """Build the window and start one background worker.

    Input: optional Tk window and fake engines for tests.
    Output: widgets and controls that tests can exercise without real API calls.
    """
    root = root if root is not None else tk.Tk()
    root.title("ChexsaAI")
    root.geometry("920x740")
    root.minsize(720, 560)

    style = ttk.Style(root)
    style.configure("TButton", padding=(12, 7))
    style.configure("Title.TLabel", font=("Segoe UI", 23, "bold"))
    style.configure("TLabel", font=("Segoe UI", 10))

    outer = ttk.Frame(root, padding=20)
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="ChexsaAI", style="Title.TLabel").pack(anchor="w")
    ttk.Label(outer, text="Ask a task. Follow its progress. Check the result.").pack(
        anchor="w", pady=(2, 16)
    )

    toolbar = ttk.Frame(outer)
    toolbar.pack(fill="x", pady=(0, 12))
    ttk.Label(toolbar, text="Use").pack(side="left", padx=(0, 8))
    mode = tk.StringVar(root, value="desktop")
    modes = ttk.Combobox(
        toolbar,
        textvariable=mode,
        values=("desktop", "browser", "gmail"),
        state="readonly",
        width=13,
    )
    modes.pack(side="left")

    status = tk.StringVar(root, value="Starting agent worker…")
    chat = scrolledtext.ScrolledText(
        outer,
        wrap="word",
        font=("Segoe UI", 11),
        padx=14,
        pady=12,
        state="disabled",
        relief="flat",
    )
    chat.tag_configure("speaker", font=("Segoe UI", 10, "bold"), foreground="#176a72")
    chat.pack(fill="both", expand=True)

    ttk.Label(outer, textvariable=status).pack(anchor="w", pady=(12, 7))
    entry = tk.Text(
        outer, height=3, wrap="word", font=("Segoe UI", 11), padx=10, pady=8
    )
    entry.pack(fill="x")
    ttk.Label(
        outer,
        text="Enter sends • Shift+Enter starts a new line • Stop waits for the current operation",
    ).pack(anchor="w", pady=(5, 8))
    actions = ttk.Frame(outer)
    actions.pack(fill="x")

    jobs, events = Queue(), Queue()
    cancel, shutdown = Event(), Event()
    context = {
        "root": root,
        "jobs": jobs,
        "events": events,
        "cancel": cancel,
        "shutdown": shutdown,
        "ready": False,
        "busy": False,
        "closing": False,
        "review": False,
        "audio_busy": False,
        "audio_thread": None,
        "audio_cancel": Event(),
        "last_reply": "",
        "mode": mode,
        "status": status,
        "entry": entry,
        "chat": chat,
    }

    def controls():
        """Enable actions only when the worker can accept a new request."""
        available = (
            context["ready"]
            and not context["busy"]
            and not context["audio_busy"]
            and not context["closing"]
        )
        for button in (send, settings_button, connect_button, microphone_button):
            button.configure(state="normal" if available else "disabled")
        stop.configure(
            state=(
                "normal"
                if (context["busy"] or context["audio_busy"]) and not context["closing"]
                else "disabled"
            )
        )
        speak_button.configure(
            state="normal" if available and context["last_reply"] else "disabled"
        )
        modes.configure(state="readonly" if available else "disabled")
        review_button.configure(
            state=(
                "normal"
                if available and context["review"] and mode.get() == "gmail"
                else "disabled"
            )
        )

    def start_job(kind, **details):
        """Queue one operation. A busy app rejects additional requests instead of racing."""
        if (
            context["busy"]
            or context["audio_busy"]
            or not context["ready"]
            or context["closing"]
        ):
            return False
        cancel.clear()
        context["busy"] = True
        context["review"] = False
        status.set("Working — " + mode.get())
        controls()
        jobs.put({"kind": kind, "mode": mode.get(), **details})
        return True

    def connect():
        """Choose Google credentials on the UI thread, then sign in on the worker."""
        if context["busy"] or not context["ready"]:
            return
        path = filedialog.askopenfilename(
            parent=root,
            title="Choose Google Desktop app credentials",
            filetypes=[("Google credentials", "*.json")],
        )
        if path:
            mode.set("gmail")
            start_job("connect", path=path)

    def submit(text=None):
        """Send typed text to the selected engine; empty messages do nothing."""
        value = entry.get("1.0", "end").strip() if text is None else text.strip()
        if (
            not value
            or context["busy"]
            or context["audio_busy"]
            or not context["ready"]
            or context["closing"]
        ):
            return
        if mode.get() == "gmail" and value == "/connect":
            connect()
            return
        if start_job("task", text=value):
            append_message(chat, "You · " + mode.get(), value)
            entry.delete("1.0", "end")

    def stop_task():
        """Request cancellation. Already-sent clicks, files, or emails are not undone."""
        if context["busy"]:
            cancel.set()
            status.set("Stopping after the current operation…")
        if context["audio_busy"]:
            context["audio_cancel"].set()
            status.set("Stopping audio after the current recording or transcription…")

    def start_audio(kind):
        """Use the microphone or speaker without blocking the window or running a task."""
        if (
            context["busy"]
            or context["audio_busy"]
            or not context["ready"]
            or context["closing"]
        ):
            return
        context["audio_busy"] = True
        context["audio_cancel"].clear()
        status.set(
            "Listening — say one command, then review the input"
            if kind == "record"
            else "Reading the last reply — Stop cancels speech"
        )
        controls()

        # Pass plain data to audio; never let its thread own Tk widgets.
        audio_stop = context["audio_cancel"]
        spoken_text = context["last_reply"]

        def audio_work():
            """Send audio results through the queue; this thread never edits a widget."""
            try:
                if kind == "record":
                    text = record_message(audio_stop)
                else:
                    play_reply(spoken_text, audio_stop)
                    text = ""
                events.put({"kind": "audio_done", "operation": kind, "text": text})
            except (InterruptedError, RuntimeError) as error:
                events.put({"kind": "audio_error", "text": str(error)})
            except Exception:
                events.put(
                    {
                        "kind": "audio_error",
                        "text": "Could not use audio. Check microphone permissions, audio devices, and voice dependencies.",
                    }
                )

        audio = Thread(target=audio_work, name="Chexsa audio")
        context["audio_thread"] = audio
        audio.start()

    def settings_dialog():
        """Show model settings with a masked key; blank fields keep existing .env values."""
        if context["busy"] or not context["ready"]:
            return
        try:
            values = load_settings()
        except RuntimeError:
            values = {}

        window = tk.Toplevel(root)
        window.title("Chexsa settings")
        window.transient(root)
        window.grab_set()
        frame = ttk.Frame(window, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame, text="Blank fields use your existing .env or environment."
        ).grid(row=0, column=0, columnspan=2, pady=(0, 14))
        fields = {}
        for row, (key, label) in enumerate(
            (
                ("LLM_API_KEY", "API key"),
                ("LLM_BASE_URL", "API address"),
                ("LLM_MODEL", "Model"),
            ),
            start=1,
        ):
            ttk.Label(frame, text=label).grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=7
            )
            field = ttk.Entry(frame, width=48, show="*" if key == "LLM_API_KEY" else "")
            field.insert(0, values.get(key, ""))
            field.grid(row=row, column=1, sticky="ew", pady=7)
            fields[key] = field

        def save():
            """Validate first, then let the worker save and reset its API connections."""
            try:
                values = validate_settings(
                    {key: field.get() for key, field in fields.items()}
                )
            except ValueError as error:
                messagebox.showerror("Check settings", str(error), parent=window)
                return
            if start_job("settings", settings=values):
                window.destroy()

        ttk.Label(
            frame, text="Saved under your Windows user and encrypted by Windows."
        ).grid(row=4, column=0, columnspan=2, pady=12)
        ttk.Button(frame, text="Save settings", command=save).grid(
            row=5, column=1, sticky="e"
        )

    def on_enter(event):
        """Enter submits; Shift+Enter keeps the normal multiline editor behavior."""
        if not event.state & 0x0001:
            submit()
            return "break"

    def close():
        """Stop new work and wait for owned connections to close before destroying Tk."""
        context["closing"] = True
        shutdown.set()
        cancel.set()
        context["audio_cancel"].set()
        status.set("Closing after the current operation…")
        controls()

    def poll():
        """Read background messages on Tk's thread; workers never touch widgets."""
        try:
            while True:
                event = events.get_nowait()
                kind = event["kind"]
                if kind == "ready":
                    context["ready"] = True
                    status.set("Ready — choose a mode and ask a task")
                elif kind == "started":
                    status.set("Working — " + event["mode"])
                elif kind in ("result", "error", "cancelled", "fatal"):
                    context["busy"] = False
                    context["review"] = event.get("review", False)
                    append_message(chat, "Chexsa", event["text"])
                    context["last_reply"] = event["text"]
                    status.set(
                        {
                            "result": "Ready",
                            "error": "Request failed — check the message",
                            "cancelled": "Stopped",
                            "fatal": "Worker could not start — restart after checking installation",
                        }[kind]
                    )
                    if kind == "fatal":
                        context["ready"] = False
                elif kind == "closed":
                    context["ready"] = False
                elif kind in ("audio_done", "audio_error"):
                    context["audio_busy"] = False
                    if kind == "audio_error":
                        append_message(chat, "Audio", event["text"])
                        status.set("Audio stopped — check the message")
                    elif context["audio_cancel"].is_set():
                        status.set("Audio stopped")
                    elif event["operation"] == "record":
                        if event["text"]:
                            prefix = " " if entry.get("1.0", "end").strip() else ""
                            entry.insert("end", prefix + event["text"])
                            status.set(
                                "Review the recorded text, then choose Send request"
                            )
                        else:
                            status.set("No command heard — try the microphone again")
                    else:
                        status.set("Ready")
                controls()
        except Empty:
            pass

        audio = context["audio_thread"]
        if (
            context["closing"]
            and not worker.is_alive()
            and (audio is None or not audio.is_alive())
        ):
            context["closed"] = True
            root.destroy()
            return
        root.after(100, poll)

    send = ttk.Button(actions, text="Send request", command=submit)
    send.pack(side="left")
    stop = ttk.Button(actions, text="Stop", command=stop_task)
    stop.pack(side="left", padx=8)
    microphone_button = ttk.Button(
        actions, text="Microphone", command=lambda: start_audio("record")
    )
    microphone_button.pack(side="left")
    speak_button = ttk.Button(
        actions, text="Read reply", command=lambda: start_audio("speak")
    )
    speak_button.pack(side="left", padx=8)
    review_button = ttk.Button(
        actions, text="Send reviewed email", command=lambda: submit("/send")
    )
    review_button.pack(side="right")
    settings_button = ttk.Button(toolbar, text="Settings", command=settings_dialog)
    settings_button.pack(side="right")
    connect_button = ttk.Button(toolbar, text="Connect Gmail", command=connect)
    connect_button.pack(side="right", padx=8)

    entry.bind("<Return>", on_enter)
    modes.bind("<<ComboboxSelected>>", lambda event: controls())
    root.protocol("WM_DELETE_WINDOW", close)
    controls()
    append_message(
        chat,
        "Chexsa",
        "Choose desktop, browser, or Gmail mode. Nothing runs until you send a request.\nFor Gmail, connect your Google account first. API keys belong in Settings, not in chat.",
    )

    if initial_settings is None:
        try:
            initial_settings = load_settings()
        except RuntimeError as error:
            initial_settings = {}
            append_message(chat, "Settings", str(error))

    worker = Thread(
        target=run_worker,
        args=(jobs, events, cancel, shutdown),
        kwargs={"initial_settings": initial_settings, "handlers": handlers},
        name="Chexsa agent",
    )
    context.update(
        worker=worker,
        submit=submit,
        stop=stop_task,
        close=close,
        poll=poll,
        start_audio=start_audio,
    )
    worker.start()
    root.after(100, poll)
    entry.focus_set()
    return context


def main():
    """Open the desktop window; agent execution stays in its background worker."""
    context = build_app()
    context["root"].mainloop()


if __name__ == "__main__":
    main()
