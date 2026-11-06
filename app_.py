"""Chexsa's Windows app. Run python app_.py while developing; no installer needed."""

from queue import Empty, Queue
from threading import Event, Thread
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, simpledialog, ttk

from app_runtime_ import (
    MASCOTS,
    chats_path,
    delete_chat,
    load_chats,
    save_chat,
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

# Friendly labels stay in the window; engines still receive simple lowercase names.
MODE_LABELS = {
    "desktop": "🖥︎ Desktop",
    "browser": "🌐︎ Browser",
    "gmail": "✉︎ Gmail",
}


def enable_display_scaling():
    """Choose Windows scaling before Tk opens, so desktop tools cannot change it later."""
    from sys import platform

    if platform == "win32":
        from ctypes import c_void_p, windll

        # -4 means sharp text with Windows' per-monitor scaling.
        # An already configured process keeps its existing setting.
        try:
            windll.user32.SetProcessDpiAwarenessContext(c_void_p(-4))
        except AttributeError:
            pass  # Older Windows versions keep their normal display behavior.


def round_outline(canvas, shape, width, height, radius=18):
    """Resize a rounded border; the real input or button sits inside it."""
    from math import cos, radians, sin

    width, height = max(2, width - 1), max(2, height - 1)
    radius = min(radius, (width - 2) / 2, (height - 2) / 2)
    points = []
    for center_x, center_y, start in (
        (width - radius, radius + 1, -90),
        (width - radius, height - radius, 0),
        (radius + 1, height - radius, 90),
        (radius + 1, radius + 1, 180),
    ):
        for step in range(9):
            angle = radians(start + step * 90 / 8)
            points.extend(
                (center_x + radius * cos(angle), center_y + radius * sin(angle))
            )
    canvas.coords(shape, *points)


def rounded_panel(parent, height=160):
    """Draw the message box while keeping a normal, accessible text editor inside."""
    canvas = tk.Canvas(
        parent, height=height, bg=parent.cget("bg"), highlightthickness=0
    )
    shape = canvas.create_polygon(
        0, 0, 1, 1, fill="white", outline="#dcdedb", smooth=True, splinesteps=24
    )
    inner = tk.Frame(canvas, bg="white")
    item = canvas.create_window(20, 14, anchor="nw", window=inner)

    def resize(event):
        """Keep the editor inside its border when the window gets narrower."""
        round_outline(canvas, shape, event.width, event.height, radius=28)
        canvas.itemconfigure(
            item, width=max(1, event.width - 40), height=max(1, event.height - 28)
        )

    canvas.bind("<Configure>", resize)
    return canvas, inner


def rounded_button(parent, text, command, primary=False, outlined=False):
    """Put a real keyboard-accessible button inside a rounded background.

    Example: button.master.pack() shows it; button.invoke() runs its command.
    Tk still exposes the text and disabled state to Windows accessibility.
    """
    scale = parent.winfo_fpixels("1i") / 96
    background = TEAL if primary else ("white" if outlined else parent.cget("bg"))
    hover = "#226e72" if primary else "#e8eeeb"
    edge = "#dfe3df" if outlined else background
    panel = tk.Canvas(parent, bg=parent.cget("bg"), highlightthickness=0)
    shape = panel.create_polygon(
        0, 0, 1, 1, fill=background, outline=edge, smooth=True, splinesteps=24
    )
    button = tk.Button(
        panel,
        text=text,
        command=command,
        bg=background,
        fg="white" if primary else INK,
        activebackground=hover,
        activeforeground="white" if primary else INK,
        disabledforeground="#a6afac",
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=2,
        pady=8,
        font=("Segoe UI", 12),
        cursor="hand2",
        takefocus=True,
    )
    button.pack(fill="both", expand=True, padx=round(12 * scale), pady=round(3 * scale))

    def repaint(event=None):
        """Show hover, keyboard focus, and disabled state on the rounded border too."""
        disabled = str(button.cget("state")) == "disabled"
        pointer_x, pointer_y = panel.winfo_pointerxy()
        inside = (
            panel.winfo_rootx() <= pointer_x < panel.winfo_rootx() + panel.winfo_width()
            and panel.winfo_rooty()
            <= pointer_y
            < panel.winfo_rooty() + panel.winfo_height()
        )
        fill = "#e8ebe8" if disabled and primary else background
        if inside and not disabled:
            fill = hover
        border = TEAL if button.focus_get() is button else edge
        button.configure(bg=fill)
        panel.itemconfigure(shape, fill=fill, outline=border)

    def activate(event):
        """The rounded edge works like the button center, including disabled checks."""
        if str(button.cget("state")) != "disabled":
            button.focus_set()
            button.invoke()

    panel.bind(
        "<Configure>",
        lambda event: round_outline(
            panel, shape, event.width, event.height, radius=round(26 * scale)
        ),
    )
    panel.bind("<Button-1>", activate)
    for widget in (panel, button):
        for event in (
            "<Enter>",
            "<Leave>",
            "<FocusIn>",
            "<FocusOut>",
            "<<RefreshStyle>>",
        ):
            widget.bind(event, repaint, add="+")
    return button


def add_tooltip(widget, text):
    """Explain an icon when someone hovers over it or reaches it with Tab."""
    state = {"timer": None, "window": None}

    def hide(event=None):
        """Remove the hint and cancel any hint that has not appeared yet."""
        if state["timer"] is not None:
            widget.after_cancel(state["timer"])
            state["timer"] = None
        if state["window"] is not None:
            state["window"].destroy()
            state["window"] = None

    def show():
        """Show a small label above the button without taking keyboard focus."""
        state["timer"] = None
        if str(widget.cget("state")) == "disabled":
            return
        hint = tk.Toplevel(widget)
        hint.overrideredirect(True)
        tk.Label(
            hint, text=text, bg=INK, fg="white", font=("Segoe UI", 10), padx=10, pady=6
        ).pack()
        hint.update_idletasks()
        x = min(
            widget.winfo_rootx(), widget.winfo_screenwidth() - hint.winfo_reqwidth() - 8
        )
        y = max(0, widget.winfo_rooty() - hint.winfo_reqheight() - 8)
        hint.geometry(f"+{max(0, x)}+{y}")
        state["window"] = hint

    def schedule(event=None):
        """Wait briefly so hints do not flash while the pointer crosses the window."""
        hide()
        state["timer"] = widget.after(450, show)

    for event in ("<Enter>", "<FocusIn>"):
        widget.bind(event, schedule, add="+")
    for event in ("<Leave>", "<FocusOut>", "<ButtonPress>", "<Destroy>"):
        widget.bind(event, hide, add="+")


def load_mascots(root, selected="Foxy", scale=1):
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
                max(
                    1, ceil(max(original.width(), original.height()) / (pixels * scale))
                )
            )
            for size, pixels in (("small", 48), ("large", 164), ("compact", 72))
        }
    return images


def apply_appearance(context, values):
    """Update the chosen name and mascot locally, without changing model instructions."""
    name = values.get("DISPLAY_NAME", "Mashrafee") or "there"
    mascot = values.get("MASCOT", "Foxy")
    if mascot not in context["images"]:
        context["images"].update(
            load_mascots(context["root"], mascot, context["scale"])
        )
    images = context["images"][mascot]
    context["profile_name"].set(name)
    context["avatar"].itemconfigure(context["avatar_letter"], text=name[:1].upper())
    context["greeting"].set("Hi " + name + ".")
    context["mascot_name"].set(mascot)
    context["brand_icon"].configure(image=images["small"])
    context["hero_icon"].configure(
        image=images["compact" if context.get("compact") else "large"]
    )
    context["root"].iconphoto(True, images["small"])


def append_message(chat, speaker, text):
    """Add a readable chat entry without letting users edit earlier results."""
    chat.configure(state="normal")
    user = speaker.startswith("You")
    chat.insert("end", f"{speaker}\n", "user_name" if user else "speaker")
    chat.insert("end", text + "\n\n", "user_text" if user else "assistant_text")
    chat.see("end")
    chat.configure(state="disabled")


def build_app(root=None, handlers=None, initial_settings=None, history_path=None):
    """Build the window and start one background worker.

    Input: optional Tk window and fake engines for tests.
    Output: widgets and controls that tests can exercise without real API calls.
    """
    if root is None:
        enable_display_scaling()
        root = tk.Tk()
    scale = root.winfo_fpixels("1i") / 96

    def pixels(value):
        """Scale fixed sizes along with the text. At 125%, 100 becomes 125 pixels."""
        return round(value * scale)

    root.title("ChexsaAI")
    root.geometry(f"{pixels(1120)}x{pixels(780)}")
    root.minsize(pixels(720), pixels(560))
    root.configure(bg=BG)
    warning = ""
    if initial_settings is None:
        try:
            initial_settings = load_settings()
        except RuntimeError as error:
            initial_settings = {}
            warning = str(error)

    # Fake engines keep chats in memory unless a test supplies its own temporary path.
    history_path = history_path or (chats_path() if handlers is None else None)
    saved_chats = []
    if history_path is not None:
        try:
            saved_chats = load_chats(history_path)
        except Exception:
            warning = (
                "Saved chats could not be read. New messages will not replace them."
            )
            history_path = None

    style = ttk.Style(root)
    # Windows' default dropdown was tiny and bright blue next to the chat.
    style.theme_use("clam")
    style.configure("TCombobox", padding=6, font=("Segoe UI", 12))
    style.configure(
        "Engine.TCombobox",
        padding=(10, 7),
        arrowsize=14,
        borderwidth=0,
        relief="flat",
        background="#f0f3f1",
        foreground=INK,
    )
    style.map(
        "Engine.TCombobox",
        fieldbackground=[("readonly", "#f0f3f1")],
        selectbackground=[("readonly", "#f0f3f1")],
        selectforeground=[("readonly", INK)],
        bordercolor=[("focus", TEAL), ("!focus", "#f0f3f1")],
    )
    root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 12))
    profile_name = tk.StringVar(root)
    greeting = tk.StringVar(root)
    mascot_name = tk.StringVar(root)
    chat_title = tk.StringVar(root, value="New chat")
    images = load_mascots(root, initial_settings.get("MASCOT", "Foxy"), scale)

    # Navigation lives beside the chat; the engine stays on its existing worker.
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=1)
    sidebar = tk.Frame(root, bg=SIDEBAR, width=pixels(244), padx=18, pady=24)
    sidebar.grid(row=0, column=0, sticky="nsew")
    sidebar.pack_propagate(False)
    brand = tk.Frame(sidebar, bg=SIDEBAR)
    brand.pack(fill="x", pady=(0, 22))
    brand_icon = tk.Label(brand, bg=SIDEBAR)
    brand_icon.pack(side="left")
    brand_label = tk.Label(
        brand, text="ChexsaAI", font=("Segoe UI", 19, "bold"), bg=SIDEBAR, fg=INK
    )
    brand_label.pack(side="left", padx=(8, 0))
    new_chat_slot = tk.Frame(sidebar, bg=SIDEBAR)
    new_chat_slot.pack(fill="x", pady=(0, 24))
    tk.Label(
        sidebar,
        text="Chats",
        font=("Segoe UI", 12, "bold"),
        bg=SIDEBAR,
        fg=MUTED,
        anchor="w",
    ).pack(fill="x", pady=(0, 12))
    tk.Label(
        sidebar,
        text="Saved on this laptop",
        bg=SIDEBAR,
        fg=MUTED,
        font=("Segoe UI", 12),
        anchor="w",
    ).pack(fill="x", pady=(0, 8))
    # Saved chats are display history, not saved automation sessions.
    history_box = tk.Listbox(
        sidebar,
        height=5,
        bg=SIDEBAR,
        fg=INK,
        selectbackground="#dde8e3",
        selectforeground=INK,
        font=("Segoe UI", 12),
        relief="flat",
        highlightthickness=0,
        exportselection=False,
        activestyle="none",
    )
    # Mouse wheel and arrow keys scroll this list without stealing the chat selection.

    chat_options = ttk.Menubutton(sidebar, text="Chat options")
    chat_menu = tk.Menu(chat_options, tearoff=False)
    chat_options.configure(menu=chat_menu)

    sidebar_bottom = tk.Frame(sidebar, bg=SIDEBAR)
    sidebar_bottom.pack(side="bottom", fill="x")
    profile = tk.Frame(sidebar_bottom, bg=SIDEBAR)
    profile.pack(side="bottom", fill="x", pady=(14, 0))
    avatar = tk.Canvas(profile, width=40, height=40, bg=SIDEBAR, highlightthickness=0)
    avatar.create_oval(1, 1, 39, 39, fill=TEAL, outline=TEAL)
    avatar_letter = avatar.create_text(
        20, 20, text="M", fill="white", font=("Segoe UI", 13, "bold")
    )
    avatar.pack(side="left", padx=(0, 10))
    profile_text = tk.Frame(profile, bg=SIDEBAR)
    profile_text.pack(side="left", fill="x", expand=True)
    tk.Label(
        profile_text,
        textvariable=profile_name,
        bg=SIDEBAR,
        fg=INK,
        font=("Segoe UI", 12, "bold"),
        anchor="w",
        wraplength=125,
    ).pack(fill="x")
    tk.Label(
        profile_text,
        textvariable=mascot_name,
        bg=SIDEBAR,
        fg=MUTED,
        font=("Segoe UI", 10),
        anchor="w",
    ).pack(fill="x", pady=(2, 0))
    tk.Frame(sidebar_bottom, bg="#dddfda", height=1).pack(side="bottom", fill="x")
    toolbar = tk.Frame(sidebar_bottom, bg=SIDEBAR)
    toolbar.pack(side="bottom", fill="x", pady=12)
    # Reserve Settings and Gmail first. The history list uses the space left over.
    chat_options.pack(side="bottom", fill="x", pady=(0, 8))
    history_box.pack(fill="both", expand=True, pady=(0, 10))

    main = tk.Frame(root, bg=BG)
    main.grid(row=0, column=1, sticky="nsew")
    header = tk.Frame(main, bg=BG, padx=30, pady=20)
    header.pack(fill="x")
    tk.Label(
        header, textvariable=chat_title, bg=BG, fg=INK, font=("Segoe UI", 14, "bold")
    ).pack(side="left")
    tk.Frame(main, bg="#e6e5e1", height=1).pack(fill="x")

    # Reserve the composer before the chat so input stays visible at small sizes.
    composer_area = tk.Frame(main, bg=BG, padx=26, pady=16)
    composer_area.pack(side="bottom", fill="x")
    status = tk.StringVar(root, value="Starting agent worker…")
    tk.Label(
        composer_area,
        textvariable=status,
        bg=BG,
        fg=MUTED,
        font=("Segoe UI", 10),
        anchor="w",
        wraplength=430,
    ).pack(side="bottom", fill="x", pady=(8, 0))
    composer, footer = rounded_panel(composer_area, height=pixels(164))
    composer.pack(fill="x")
    entry = tk.Text(
        footer,
        height=2,
        wrap="word",
        font=("Segoe UI", 14),
        bg="white",
        fg=INK,
        insertbackground=TEAL,
        relief="flat",
        highlightthickness=0,
        padx=6,
        pady=6,
    )
    footer.grid_columnconfigure(0, weight=1)
    footer.grid_rowconfigure(0, weight=1)
    entry.grid(row=0, column=0, sticky="nsew")
    placeholder = tk.Label(
        entry, text="Ask Chexsa anything…", bg="white", fg=MUTED, font=("Segoe UI", 14)
    )
    placeholder.place(x=6, y=6)
    placeholder.bind("<Button-1>", lambda event: entry.focus_set())
    actions = tk.Frame(footer, bg="white")
    actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
    tk.Frame(footer, bg="#edf0ec", height=1).grid(
        row=1, column=0, sticky="ew", pady=(4, 0)
    )
    mode = tk.StringVar(root, value="desktop")
    mode_label = tk.StringVar(root, value=MODE_LABELS[mode.get()])

    def sync_mode_label(*args):
        """A suggestion can change the engine too; keep its visible icon in sync."""
        mode_label.set(MODE_LABELS[mode.get()])

    mode.trace_add("write", sync_mode_label)
    modes = ttk.Combobox(
        actions,
        textvariable=mode_label,
        values=tuple(MODE_LABELS.values()),
        state="readonly",
        width=14,
        font=("Segoe UI", 12),
        style="Engine.TCombobox",
        takefocus=True,
    )
    modes.pack(side="left")
    review_actions = tk.Frame(composer_area, bg=BG)

    chat_host = tk.Frame(main, bg=BG)
    chat_host.pack(fill="both", expand=True, padx=22, pady=6)
    chat = scrolledtext.ScrolledText(
        chat_host,
        wrap="word",
        height=4,
        font=("Segoe UI", 13),
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
    welcome.place(relx=0.5, rely=0.5, anchor="center")
    hero_icon = tk.Label(welcome, bg=BG)
    hero_icon.pack(pady=(0, 12))
    greeting_label = tk.Label(
        welcome, textvariable=greeting, bg=BG, fg=INK, font=("Segoe UI", 30, "bold")
    )
    greeting_label.pack()
    subtitle = tk.Label(
        welcome, text="What can I help with?", bg=BG, fg=MUTED, font=("Segoe UI", 17)
    )
    subtitle.pack(pady=(5, 22))
    suggestions = tk.Frame(welcome, bg=BG)
    suggestions.pack()

    jobs, events = Queue(), Queue()
    cancel, shutdown = Event(), Event()
    context = {
        "root": root,
        "saved_chats": {item["id"]: item for item in saved_chats},
        "active_chat": None,
        "chat_order": [item["id"] for item in saved_chats],
        "history_box": history_box,
        "history_path": history_path,
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
        "mode_selector": modes,
        "status": status,
        "entry": entry,
        "chat": chat,
        "images": images,
        "profile_name": profile_name,
        "greeting": greeting,
        "mascot_name": mascot_name,
        "avatar": avatar,
        "avatar_letter": avatar_letter,
        "brand_icon": brand_icon,
        "hero_icon": hero_icon,
        "welcome": welcome,
        "suggestions": suggestions,
        "operation": None,
        "compact": False,
        "scale": scale,
    }

    def remember(speaker, text):
        """Save display messages only. These messages never replay tool calls."""
        from uuid import uuid4

        if context["active_chat"] is None:
            context["active_chat"] = uuid4().hex
            context["saved_chats"][context["active_chat"]] = {
                "id": context["active_chat"],
                "title": chat_title.get(),
                "mode": mode.get(),
                "messages": [],
            }
        item = context["saved_chats"][context["active_chat"]]
        item["mode"] = mode.get()
        item["messages"].append({"speaker": speaker, "text": text})
        persist_chat(item)
        if item["id"] in context["chat_order"]:
            context["chat_order"].remove(item["id"])
        context["chat_order"].insert(0, item["id"])
        refresh_history()

    def refresh_history():
        """Show saved titles while keeping the current conversation highlighted."""
        history_box.delete(0, "end")
        for index, chat_id in enumerate(context["chat_order"]):
            history_box.insert("end", context["saved_chats"][chat_id]["title"])
            if chat_id == context["active_chat"]:
                history_box.selection_set(index)
                history_box.see(index)

    def open_chat(chat_id):
        """Reopen messages only; fresh tasks must observe the app again.

        Input: a saved chat ID. Effect: display its messages without running any tools.
        """
        if chat_id == context["active_chat"] or chat_id not in context["saved_chats"]:
            return
        if not start_job("reset"):
            return
        item = context["saved_chats"][chat_id]
        context["active_chat"] = chat_id
        context["last_reply"] = ""
        chat_title.set(item["title"])
        mode.set(item["mode"])
        context["review"] = False
        entry.delete("1.0", "end")
        chat.configure(state="normal")
        chat.delete("1.0", "end")
        chat.configure(state="disabled")
        for message in item["messages"]:
            append_message(chat, message["speaker"], message["text"])
            if message["speaker"] == "Chexsa":
                context["last_reply"] = message["text"]
        welcome.place_forget()
        chat.pack(fill="both", expand=True)
        refresh_history()

    def select_chat(event=None):
        """Open the selected sidebar row with a double-click or Enter key."""
        selection = history_box.curselection()
        if selection:
            open_chat(context["chat_order"][selection[0]])

    def selected_chat():
        """Return the highlighted conversation, or the one currently on screen."""
        selection = history_box.curselection()
        return (
            context["chat_order"][selection[0]] if selection else context["active_chat"]
        )

    def rename_chat(title=None):
        """Give the selected chat a short title; this does not change any task."""
        chat_id = selected_chat()
        if (
            context["busy"]
            or context["audio_busy"]
            or context["closing"]
            or not chat_id
        ):
            return
        item = context["saved_chats"][chat_id]
        if title is None:
            title = simpledialog.askstring(
                "Rename chat", "New name:", initialvalue=item["title"], parent=root
            )
        if title is None:
            return
        title = title.strip()
        if not title or len(title) > 80:
            messagebox.showwarning(
                "Chat name", "Use a name with 1 to 80 characters.", parent=root
            )
            return
        item["title"] = title
        if chat_id == context["active_chat"]:
            chat_title.set(title)
        persist_chat(item)
        refresh_history()

    def remove_chat():
        """Delete a selected conversation after asking. Created files are never deleted."""
        chat_id = selected_chat()
        if (
            context["busy"]
            or context["audio_busy"]
            or context["closing"]
            or not chat_id
        ):
            return
        if not messagebox.askyesno(
            "Delete chat?",
            "Delete this saved conversation? Files it created will stay on your laptop.",
            parent=root,
        ):
            return
        if context["history_path"] is not None:
            try:
                delete_chat(chat_id, context["history_path"])
            except Exception:
                messagebox.showwarning(
                    "Chat not deleted",
                    "Could not delete the saved chat. Try again later.",
                    parent=root,
                )
                return
        context["saved_chats"].pop(chat_id)
        context["chat_order"].remove(chat_id)
        if context["active_chat"] == chat_id:
            new_chat()
        refresh_history()

    def persist_chat(item):
        """A disk error warns the user without breaking an already running task."""
        if context["history_path"] is not None:
            try:
                save_chat(item, context["history_path"])
            except Exception:
                messagebox.showwarning(
                    "Chat not saved",
                    "This conversation is still visible, but could not be saved on this laptop.",
                    parent=root,
                )

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
            chat_options,
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
            send.master.pack_forget()
            stop.master.pack(side="right", padx=(8, 0))
        else:
            stop.master.pack_forget()
            send.master.pack(side="right", padx=(8, 0))
        if context["last_reply"]:
            speak_button.master.pack(side="right", padx=4)
        else:
            speak_button.master.pack_forget()
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
        for button in (
            send,
            stop,
            settings_button,
            connect_button,
            microphone_button,
            new_chat_button,
            speak_button,
            review_button,
        ):
            button.event_generate("<<RefreshStyle>>")

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
            if context["active_chat"] is None:
                chat_title.set(value[:28] + ("…" if len(value) > 28 else ""))
            append_message(chat, "You · " + mode.get(), value)
            remember("You · " + mode.get(), value)
            entry.delete("1.0", "end")

    def new_chat():
        """Clear this chat's display and selected targets while keeping connections."""
        if start_job("reset"):
            chat.configure(state="normal")
            chat.delete("1.0", "end")
            chat.configure(state="disabled")
            chat.pack_forget()
            welcome.place(relx=0.5, rely=0.5, anchor="center")
            chat_title.set("New chat")
            context["active_chat"] = None
            context["last_reply"] = ""
            entry.delete("1.0", "end")
            refresh_history()

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
        mascot_field.set(values.get("MASCOT", "Foxy"))
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
                        remember("Chexsa", event["text"])
                        context["last_reply"] = event["text"]
                    if event.get("operation") == "settings" and kind == "result":
                        try:
                            apply_appearance(context, load_settings())
                        except (RuntimeError, tk.TclError):
                            append_message(
                                chat,
                                "Settings",
                                "Settings were saved, but appearance could not refresh. Reopen Settings to check them.",
                            )
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

    send = rounded_button(actions, "↑", submit, primary=True)
    send.configure(font=("Segoe UI", 19, "bold"), padx=4, pady=0)
    send.pack_configure(padx=pixels(10), pady=pixels(8))
    send.master.pack(side="right", padx=(8, 0))
    stop = rounded_button(actions, "Stop", stop_task, primary=True)
    microphone_button = rounded_button(
        actions, "\ue720", lambda: start_audio("record"), outlined=True
    )
    # This Windows icon is one character, so it does not create an oversized emoji button.
    microphone_button.configure(font=("Segoe MDL2 Assets", 17), padx=2, pady=6)
    microphone_button.master.pack(side="right", padx=4)
    add_tooltip(microphone_button, "Record a message")
    speak_button = rounded_button(actions, "Read aloud", lambda: start_audio("speak"))
    review_button = rounded_button(
        review_actions, "Send reviewed email", lambda: submit("/send"), primary=True
    )
    review_button.master.pack(side="right")
    settings_button = rounded_button(toolbar, "⚙  Settings", settings_dialog)
    settings_button.configure(anchor="w")
    settings_button.master.pack(fill="x", pady=3)
    connect_button = rounded_button(toolbar, "Connect Gmail", connect)
    connect_button.configure(anchor="w")
    connect_button.master.pack(fill="x", pady=3)
    new_chat_button = rounded_button(
        new_chat_slot, "+  New chat", new_chat, primary=True
    )
    new_chat_button.configure(font=("Segoe UI", 12, "bold"))
    new_chat_button.master.pack(fill="x")
    chips = []
    for label, selected_mode, prompt in (
        ("✉  Check email", "gmail", "What work do I need to do from my emails?"),
        ("🌐︎  Browse the web", "browser", "Search the web for "),
        ("▤  Create a file", "desktop", "Create a file with "),
    ):
        chip = rounded_button(
            suggestions,
            label,
            lambda selected_mode=selected_mode, prompt=prompt: suggest(
                selected_mode, prompt
            ),
            outlined=True,
        )
        chip.master.grid(row=0, column=len(chips), padx=4, pady=4)
        chips.append(chip)

    def resize_sidebar(event):
        """Keep the welcome readable and inside the available space on small windows."""
        if event.widget is not root:
            return
        compact = event.width < pixels(950) or event.height < pixels(680)
        sidebar_width = pixels(188 if event.width < pixels(950) else 244)
        if sidebar.cget("width") != sidebar_width:
            sidebar.configure(width=sidebar_width)
        if context.get("layout_size") == (compact, event.width < pixels(950)):
            return
        context["layout_size"] = (compact, event.width < pixels(950))
        context["compact"] = compact
        art = images[mascot_name.get()]
        hero_icon.configure(image=art["compact" if compact else "large"])
        greeting_label.configure(font=("Segoe UI", 24 if compact else 30, "bold"))
        brand_label.configure(
            font=("Segoe UI", 15 if event.width < pixels(950) else 19, "bold")
        )
        subtitle.pack_configure(pady=(4, 12) if compact else (5, 22))
        hero_icon.pack_configure(pady=(0, 6) if compact else (0, 12))
        # Keep the three cards in one row, with slightly less padding on small screens.
        for chip in chips:
            chip.configure(
                font=("Segoe UI", 11 if compact else 12), pady=4 if compact else 8
            )

    root.bind("<Configure>", resize_sidebar, add="+")
    apply_appearance(context, initial_settings)
    entry.bind("<Return>", on_enter)
    entry.bind("<KeyPress>", lambda event: placeholder.place_forget())
    entry.bind("<KeyRelease>", show_placeholder)

    def choose_mode(event):
        """Keep the chosen engine readable rather than highlighting it like typed text."""
        # Example: the label "🌐 Browser" selects the engine named "browser".
        selected = modes.current()
        if selected >= 0:
            mode.set(tuple(MODE_LABELS)[selected])
        modes.selection_clear()
        entry.focus_set()
        controls()

    modes.bind("<<ComboboxSelected>>", choose_mode)
    # A readonly chooser should not highlight its label like an editable text field.
    for event in ("<FocusIn>", "<ButtonRelease-1>"):
        modes.bind(
            event, lambda event: modes.after_idle(modes.selection_clear), add="+"
        )
    modes.bind("<FocusOut>", lambda event: modes.selection_clear(), add="+")
    chat_menu.add_command(label="Rename", command=rename_chat)
    chat_menu.add_command(label="Delete", command=remove_chat)
    history_box.bind("<F2>", lambda event: rename_chat())
    history_box.bind("<Delete>", lambda event: remove_chat())
    history_box.bind("<Double-Button-1>", select_chat)
    history_box.bind("<Return>", select_chat)
    refresh_history()
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
        open_chat=open_chat,
        rename_chat=rename_chat,
        remove_chat=remove_chat,
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
