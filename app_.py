"""Chexsa's Windows app. Run python app_.py while developing; no installer needed."""

from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

from app_runtime_ import (
    MASCOTS,
    load_settings,
    play_reply,
    record_message,
    run_worker,
    validate_settings,
)

BG = "#fbfaf8"
SIDEBAR = "#f0efeb"
INK = "#172731"
MUTED = "#6d787f"
TEAL = "#277f83"


def rounded_panel(parent, height=140):
    """Draw a rounded outline with a normal Tk frame inside for accessible inputs."""
    canvas = tk.Canvas(
        parent, height=height, bg=parent.cget("bg"), highlightthickness=0
    )
    shape = canvas.create_polygon(
        0, 0, 1, 1, fill="white", outline="#dedfdd", smooth=True
    )
    inner = tk.Frame(canvas, bg="white")
    item = canvas.create_window(14, 12, anchor="nw", window=inner)

    def resize(event):
        """Keep the border and its contents together as the window changes size."""
        width, height, radius = event.width - 1, event.height - 1, 20
        canvas.coords(
            shape,
            radius,
            1,
            width - radius,
            1,
            width,
            1,
            width,
            radius,
            width,
            height - radius,
            width,
            height,
            width - radius,
            height,
            radius,
            height,
            1,
            height,
            1,
            height - radius,
            1,
            radius,
            1,
            1,
        )
        canvas.itemconfigure(item, width=max(1, width - 28), height=max(1, height - 24))

    canvas.bind("<Configure>", resize)
    return canvas, inner


def load_mascots(root, selected="Foxxy"):
    """Load the packaged PNGs with Tk itself; terminal users need no image library."""
    from importlib.resources import files
    from math import ceil

    images = {}
    for name in (selected,):
        original = tk.PhotoImage(
            master=root, file=str(files("chexsa_assets") / (name.lower() + "_.png"))
        )
        images[name] = {
            size: original.subsample(
                max(1, ceil(max(original.width(), original.height()) / pixels))
            )
            for size, pixels in (("small", 38), ("large", 128))
        }
    return images


def apply_appearance(context, values):
    """Update the chosen name and mascot locally, without changing model instructions."""
    name = values.get("DISPLAY_NAME", "Mashrafee") or "there"
    mascot = values.get("MASCOT", "Foxxy")
    if mascot not in context["images"]:
        context["images"].update(load_mascots(context["root"], mascot))
    images = context["images"][mascot]
    context["profile_name"].set(name)
    context["greeting"].set("Hi " + name + ".")
    context["mascot_name"].set(mascot)
    context["brand_icon"].configure(image=images["small"])
    context["hero_icon"].configure(image=images["large"])
    context["root"].iconphoto(True, images["small"])


def append_message(chat, speaker, text):
    """Add a readable chat entry without letting users edit earlier results."""
    chat.configure(state="normal")
    user = speaker.startswith("You")
    chat.insert("end", f"{speaker}\n", "user_name" if user else "speaker")
    chat.insert("end", text + "\n\n", "user_text" if user else "assistant_text")
    chat.see("end")
    chat.configure(state="disabled")


def build_app(root=None, handlers=None, initial_settings=None):
    """Build the window and start one background worker.

    Input: optional Tk window and fake engines for tests.
    Output: widgets and controls that tests can exercise without real API calls.
    """
    root = root if root is not None else tk.Tk()
    root.title("ChexsaAI")
    root.geometry("1080x780")
    root.minsize(720, 560)
    root.configure(bg=BG)
    warning = ""
    if initial_settings is None:
        try:
            initial_settings = load_settings()
        except RuntimeError as error:
            initial_settings = {}
            warning = str(error)

    style = ttk.Style(root)
    style.configure("TCombobox", padding=4)
    profile_name = tk.StringVar(root)
    greeting = tk.StringVar(root)
    mascot_name = tk.StringVar(root)
    chat_title = tk.StringVar(root, value="New chat")
    images = load_mascots(root, initial_settings.get("MASCOT", "Foxxy"))

    # Navigation lives beside the chat; the engine stays on its existing worker.
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=1)
    sidebar = tk.Frame(root, bg=SIDEBAR, width=228, padx=16, pady=22)
    sidebar.grid(row=0, column=0, sticky="nsew")
    sidebar.pack_propagate(False)
    brand = tk.Frame(sidebar, bg=SIDEBAR)
    brand.pack(fill="x", pady=(0, 22))
    brand_icon = tk.Label(brand, bg=SIDEBAR)
    brand_icon.pack(side="left")
    tk.Label(
        brand, text="ChexsaAI", font=("Segoe UI", 16, "bold"), bg=SIDEBAR, fg=INK
    ).pack(side="left", padx=(8, 0))
    new_chat_slot = tk.Frame(sidebar, bg=SIDEBAR)
    new_chat_slot.pack(fill="x", pady=(0, 24))
    tk.Label(
        sidebar,
        text="CHATS",
        font=("Segoe UI", 9, "bold"),
        bg=SIDEBAR,
        fg=MUTED,
        anchor="w",
    ).pack(fill="x", pady=(0, 12))
    tk.Label(
        sidebar, text="Today", bg=SIDEBAR, fg=MUTED, font=("Segoe UI", 10), anchor="w"
    ).pack(fill="x", pady=(0, 8))
    tk.Label(
        sidebar,
        textvariable=chat_title,
        bg="#e6e5e1",
        fg=INK,
        font=("Segoe UI", 10),
        anchor="w",
        padx=10,
        pady=12,
        wraplength=160,
    ).pack(fill="x")

    sidebar_bottom = tk.Frame(sidebar, bg=SIDEBAR)
    sidebar_bottom.pack(side="bottom", fill="x")
    tk.Label(
        sidebar_bottom,
        textvariable=profile_name,
        bg=SIDEBAR,
        fg=INK,
        font=("Segoe UI", 11, "bold"),
        anchor="w",
        pady=10,
    ).pack(side="bottom", fill="x")
    tk.Label(
        sidebar_bottom,
        textvariable=mascot_name,
        bg=SIDEBAR,
        fg=MUTED,
        font=("Segoe UI", 9),
        anchor="w",
    ).pack(side="bottom", fill="x")
    toolbar = tk.Frame(sidebar_bottom, bg=SIDEBAR)
    toolbar.pack(side="bottom", fill="x", pady=12)

    main = tk.Frame(root, bg=BG)
    main.grid(row=0, column=1, sticky="nsew")
    header = tk.Frame(main, bg=BG, padx=28, pady=16)
    header.pack(fill="x")
    tk.Label(
        header, textvariable=chat_title, bg=BG, fg=INK, font=("Segoe UI", 12, "bold")
    ).pack(side="left")
    tk.Frame(main, bg="#e6e5e1", height=1).pack(fill="x")

    # Reserve the composer before the chat so input stays visible at small sizes.
    composer_area = tk.Frame(main, bg=BG, padx=22, pady=14)
    composer_area.pack(side="bottom", fill="x")
    status = tk.StringVar(root, value="Starting agent worker…")
    tk.Label(
        composer_area,
        textvariable=status,
        bg=BG,
        fg=MUTED,
        font=("Segoe UI", 9),
        anchor="w",
        wraplength=430,
    ).pack(side="bottom", fill="x", pady=(8, 0))
    composer, footer = rounded_panel(composer_area, height=154)
    composer.pack(fill="x")
    entry = tk.Text(
        footer,
        height=2,
        wrap="word",
        font=("Segoe UI", 12),
        bg="white",
        fg=INK,
        insertbackground=TEAL,
        relief="flat",
        highlightthickness=0,
        padx=6,
        pady=6,
    )
    entry.pack(fill="both", expand=True)
    placeholder = tk.Label(
        entry, text="Ask Chexsa anything…", bg="white", fg=MUTED, font=("Segoe UI", 12)
    )
    placeholder.place(x=6, y=6)
    placeholder.bind("<Button-1>", lambda event: entry.focus_set())
    actions = tk.Frame(footer, bg="white")
    actions.pack(fill="x", pady=(8, 0))
    mode = tk.StringVar(root, value="desktop")
    modes = ttk.Combobox(
        actions,
        textvariable=mode,
        values=("desktop", "browser", "gmail"),
        state="readonly",
        width=10,
    )
    modes.pack(side="left")
    review_actions = tk.Frame(composer_area, bg=BG)

    chat_host = tk.Frame(main, bg=BG)
    chat_host.pack(fill="both", expand=True, padx=22, pady=6)
    chat = scrolledtext.ScrolledText(
        chat_host,
        wrap="word",
        height=4,
        font=("Segoe UI", 11),
        bg=BG,
        fg=INK,
        padx=18,
        pady=18,
        state="disabled",
        relief="flat",
        highlightthickness=0,
    )
    chat.tag_configure(
        "speaker",
        font=("Segoe UI", 10, "bold"),
        foreground=TEAL,
        spacing1=14,
        spacing3=6,
    )
    chat.tag_configure("assistant_text", spacing3=14)
    chat.tag_configure(
        "user_name", foreground=MUTED, justify="right", spacing1=14, spacing3=6
    )
    chat.tag_configure(
        "user_text",
        background="#efeeea",
        justify="right",
        lmargin1=70,
        lmargin2=70,
        rmargin=8,
        spacing1=8,
        spacing3=16,
    )

    welcome = tk.Frame(chat_host, bg=BG)
    welcome.place(relx=0.5, rely=0.46, anchor="center")
    hero_icon = tk.Label(welcome, bg=BG)
    hero_icon.pack(pady=(0, 12))
    tk.Label(
        welcome, textvariable=greeting, bg=BG, fg=INK, font=("Segoe UI", 24, "bold")
    ).pack()
    tk.Label(
        welcome, text="What can I help with?", bg=BG, fg=MUTED, font=("Segoe UI", 15)
    ).pack(pady=(5, 22))
    suggestions = tk.Frame(welcome, bg=BG)
    suggestions.pack()

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
        "images": images,
        "profile_name": profile_name,
        "greeting": greeting,
        "mascot_name": mascot_name,
        "brand_icon": brand_icon,
        "hero_icon": hero_icon,
        "operation": None,
    }

    def show_placeholder(event=None):
        """Show a hint only when the real message editor is empty."""
        if entry.get("1.0", "end").strip():
            placeholder.place_forget()
        else:
            placeholder.place(x=6, y=6)

    def controls():
        """Enable actions only when the worker can accept a new request."""
        show_placeholder()
        available = (
            context["ready"]
            and not context["busy"]
            and not context["audio_busy"]
            and not context["closing"]
        )
        for button in (
            send,
            settings_button,
            connect_button,
            microphone_button,
            new_chat_button,
        ):
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
        if context["busy"] or context["audio_busy"]:
            send.pack_forget()
            stop.pack(side="right", padx=(8, 0))
        else:
            stop.pack_forget()
            send.pack(side="right", padx=(8, 0))
        if context["last_reply"]:
            speak_button.pack(side="right", padx=4)
        else:
            speak_button.pack_forget()
        if context["review"] and mode.get() == "gmail":
            review_actions.pack(fill="x", before=composer, pady=(0, 8))
        else:
            review_actions.pack_forget()
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
        context["operation"] = kind
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
            welcome.place_forget()
            chat.pack(fill="both", expand=True)
            if chat_title.get() == "New chat":
                chat_title.set(value[:28] + ("…" if len(value) > 28 else ""))
            append_message(chat, "You · " + mode.get(), value)
            entry.delete("1.0", "end")

    def new_chat():
        """Clear this chat's display and selected targets while keeping connections."""
        if start_job("reset"):
            chat.configure(state="normal")
            chat.delete("1.0", "end")
            chat.configure(state="disabled")
            chat.pack_forget()
            welcome.place(relx=0.5, rely=0.46, anchor="center")
            chat_title.set("New chat")
            context["last_reply"] = ""
            entry.delete("1.0", "end")

    def suggest(selected_mode, prompt):
        """Prepare a starting message for review; suggestion buttons never run it."""
        if context["busy"] or context["audio_busy"] or context["closing"]:
            return
        mode.set(selected_mode)
        entry.delete("1.0", "end")
        entry.insert("1.0", prompt)
        entry.focus_set()
        controls()

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

        ttk.Label(frame, text="Display name").grid(
            row=4, column=0, sticky="w", padx=(0, 12), pady=7
        )
        name_field = ttk.Entry(frame, width=48)
        name_field.insert(0, values.get("DISPLAY_NAME", "Mashrafee"))
        name_field.grid(row=4, column=1, sticky="ew", pady=7)
        ttk.Label(frame, text="Mascot").grid(
            row=5, column=0, sticky="w", padx=(0, 12), pady=7
        )
        mascot_field = ttk.Combobox(frame, values=MASCOTS, state="readonly", width=46)
        mascot_field.set(values.get("MASCOT", "Foxxy"))
        mascot_field.grid(row=5, column=1, sticky="ew", pady=7)

        def save():
            """Validate first, then let the worker save and reset its API connections."""
            try:
                values = validate_settings(
                    {
                        **{key: field.get() for key, field in fields.items()},
                        "DISPLAY_NAME": name_field.get(),
                        "MASCOT": mascot_field.get(),
                    }
                )
            except ValueError as error:
                messagebox.showerror("Check settings", str(error), parent=window)
                return
            if start_job("settings", settings=values):
                window.destroy()

        ttk.Label(
            frame, text="Saved under your Windows user and encrypted by Windows."
        ).grid(row=6, column=0, columnspan=2, pady=12)
        ttk.Button(frame, text="Save settings", command=save).grid(
            row=7, column=1, sticky="e"
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
                    if event.get("operation") != "reset":
                        welcome.place_forget()
                        chat.pack(fill="both", expand=True)
                        append_message(chat, "Chexsa", event["text"])
                        context["last_reply"] = event["text"]
                    if event.get("operation") == "settings" and kind == "result":
                        apply_appearance(context, load_settings())
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

    def button(parent, text, command, primary=False):
        """Use one flat button style with normal keyboard and accessibility behavior."""
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=TEAL if primary else parent.cget("bg"),
            fg="white" if primary else INK,
            activebackground="#226c70" if primary else "#e5e7e4",
            activeforeground="white" if primary else INK,
            relief="flat",
            bd=0,
            highlightthickness=0,
            padx=12,
            pady=8,
            font=("Segoe UI", 10),
            cursor="hand2",
        )

    send = button(actions, "↑", submit, primary=True)
    send.configure(font=("Segoe UI", 16, "bold"), padx=13, pady=0)
    send.pack(side="right", padx=(8, 0))
    stop = button(actions, "Stop", stop_task, primary=True)
    microphone_button = button(actions, "Mic", lambda: start_audio("record"))
    microphone_button.pack(side="right", padx=4)
    speak_button = button(actions, "Read aloud", lambda: start_audio("speak"))
    review_button = button(
        review_actions, "Send reviewed email", lambda: submit("/send"), primary=True
    )
    review_button.pack(side="right")
    settings_button = button(toolbar, "Settings", settings_dialog)
    settings_button.pack(fill="x", pady=3)
    connect_button = button(toolbar, "Connect Gmail", connect)
    connect_button.pack(fill="x", pady=3)
    new_chat_button = button(new_chat_slot, "+  New chat", new_chat, primary=True)
    new_chat_button.pack(fill="x")
    for label, selected_mode, prompt in (
        ("Check email", "gmail", "What work do I need to do from my emails?"),
        ("Browse the web", "browser", "Search the web for "),
        ("Create a file", "desktop", "Create a file with "),
    ):
        chip = button(
            suggestions,
            label,
            lambda selected_mode=selected_mode, prompt=prompt: suggest(
                selected_mode, prompt
            ),
        )
        chip.configure(
            font=("Segoe UI", 9),
            padx=8,
            highlightthickness=1,
            highlightbackground="#e0e1de",
        )
        chip.pack(side="left", padx=4)

    def resize_sidebar(event):
        """Keep space for chat and input on narrower windows."""
        if event.widget is root:
            width = 190 if event.width < 950 else 228
            if sidebar.cget("width") != width:
                sidebar.configure(width=width)

    root.bind("<Configure>", resize_sidebar, add="+")
    apply_appearance(context, initial_settings)
    entry.bind("<Return>", on_enter)
    entry.bind("<KeyPress>", lambda event: placeholder.place_forget())
    entry.bind("<KeyRelease>", show_placeholder)
    modes.bind("<<ComboboxSelected>>", lambda event: controls())
    root.protocol("WM_DELETE_WINDOW", close)
    controls()
    if warning:
        welcome.place_forget()
        chat.pack(fill="both", expand=True)
        append_message(chat, "Settings", warning)

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
        new_chat=new_chat,
        suggest=suggest,
        send_button=send,
        review_button=review_button,
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
