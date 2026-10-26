"""Exercise the rebuilt desktop actions on disposable windows, without an AI API."""

import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys

import win32api
import win32con
import win32gui

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pywinauto import Desktop
from pywinauto.timings import wait_until
from desktop_ import click_control, read_window, type_text


# Create a tiny real Windows app with duplicate buttons and ordinary text fields.
def fixture():
    counts = {101: 0, 102: 0}
    def events(handle, message, word, data):
        if message == win32con.WM_COMMAND and (word & 0xFFFF) in counts:
            number = word & 0xFFFF
            counts[number] += 1
            win32gui.SetWindowText(win32gui.GetDlgItem(handle, 301), f"{counts[101]},{counts[102]}")
            return 0
        if message == win32con.WM_APP + 1:
            win32gui.DestroyWindow(win32gui.GetDlgItem(handle, 101))
            return 0
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        return win32gui.DefWindowProc(handle, message, word, data)

    definition = win32gui.WNDCLASS()
    definition.hInstance = win32api.GetModuleHandle(None)
    definition.lpszClassName = "ChexsaDesktopFixture"
    definition.lpfnWndProc = events
    definition.hbrBackground = win32con.COLOR_WINDOW + 1
    win32gui.RegisterClass(definition)
    root = win32gui.CreateWindow(definition.lpszClassName, "Chexsa desktop fixture",
        win32con.WS_OVERLAPPEDWINDOW | win32con.WS_VISIBLE, 80, 80, 620, 360,
        0, 0, definition.hInstance, None)
    child = win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP
    for number, x in ((101, 20), (102, 180)):
        win32gui.CreateWindow("BUTTON", "Write", child, x, 20, 130, 35, root, number, definition.hInstance, None)
    for number, y, flags in ((201, 80, 0), (202, 180, win32con.ES_READONLY)):
        win32gui.CreateWindow("EDIT", "Old content", child | win32con.WS_BORDER | win32con.ES_MULTILINE | flags,
            20, y, 530, 70, root, number, definition.hInstance, None)
    win32gui.CreateWindow("STATIC", "0,0", win32con.WS_CHILD | win32con.WS_VISIBLE,
        20, 265, 200, 30, root, 301, definition.hInstance, None)
    print(root, flush=True)
    win32gui.PumpMessages()


# Cross-process edit text needs WM_GETTEXT; GetWindowText only reads its old caption.
def _edit_text(handle):
    buffer = ctypes.create_unicode_buffer(4096)
    send = ctypes.windll.user32.SendMessageW
    send.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    send(handle, win32con.WM_GETTEXT, len(buffer), ctypes.addressof(buffer))
    return buffer.value


def test_native_window(test_mouse=True):
    "Checks clicking and typing in a disposable Windows test app, including duplicate buttons."
    process = subprocess.Popen([sys.executable, __file__, "--fixture"], stdout=subprocess.PIPE,
                               text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    handle = int(process.stdout.readline())
    try:
        window = Desktop(backend="uia").window(handle=handle).wrapper_object()
        observation = read_window(window)
        buttons = [(node, control) for node, control in observation["controls"].items()
                   if control.element_info.control_type == "Button" and control.element_info.name == "Write"]
        assert len(buttons) == 2
        target = next(node for node, control in buttons if control.element_info.automation_id == "102")
        click_control(observation, target)
        wait_until(5, 0.1, lambda: win32gui.GetWindowText(win32gui.GetDlgItem(handle, 301)) == "0,1")
        try:
            click_control(observation, target)
            raise AssertionError("Old reading was accepted")
        except RuntimeError:
            pass
        observation = read_window(window)
        edit = next(node for node, control in observation["controls"].items() if control.element_info.automation_id == "201")
        if test_mouse:
            click_control(observation, edit)  # Exercise the guarded mouse fallback too.
            observation = read_window(window)
        else:
            print("SKIP: physical mouse fallback; this test process cannot move the cursor.", flush=True)
        literal = "AI + education ^ % ~ (test) {ENTER}\nCaf\u00e9 \U0001f600"
        type_text(observation, edit, literal)
        actual = _edit_text(win32gui.GetDlgItem(handle, 201)).replace("\r\n", "\n")
        assert actual == literal, (repr(actual), repr(literal))
        observation = read_window(window)
        type_text(observation, edit, "")
        assert _edit_text(win32gui.GetDlgItem(handle, 201)) == ""
        observation = read_window(window)
        readonly = next(node for node, control in observation["controls"].items() if control.element_info.automation_id == "202")
        try:
            type_text(observation, readonly, "Must not change")
            raise AssertionError("Readonly field was changed")
        except RuntimeError as error:
            assert "read-only" in str(error)
        assert _edit_text(win32gui.GetDlgItem(handle, 202)) == "Old content"
        removed = next(node for node, control in buttons if control.element_info.automation_id == "101")
        win32gui.SendMessage(handle, win32con.WM_APP + 1, 0, 0)
        try:
            click_control(observation, removed)
            raise AssertionError("Detached target was accepted")
        except RuntimeError:
            pass
        assert win32gui.GetWindowText(win32gui.GetDlgItem(handle, 301)) == "0,1"
        print("PASS: duplicate buttons, stale/detached IDs, literal text, clearing, readonly.", flush=True)
    finally:
        if win32gui.IsWindow(handle):
            win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()  # Only our disposable fixture process can be killed here.
            process.wait()


def test_connected_agent():
    "Checks the desktop loop on a real test window with fake model replies."
    import json
    import os
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    import desktop_agent_ as agent

    process = subprocess.Popen([sys.executable, __file__, "--fixture"], stdout=subprocess.PIPE,
                               text=True, creationflags=subprocess.CREATE_NO_WINDOW)
    handle = int(process.stdout.readline())
    try:
        window = Desktop(backend="uia").window(handle=handle).wrapper_object()
        initial = read_window(window)
        target = next(node for node, control in initial["controls"].items() if control.element_info.automation_id == "201")
        essay = " ".join(["learning"] * 300)
        payloads = []
        def choose(**kwargs):
            payload = json.loads(kwargs["messages"][-1]["content"])
            payloads.append(payload)
            count = len(payload["previous_actions"])
            if count == 0:
                name, arguments = "type_text", {"node_id": list(target), "text": "Too short"}
            elif count == 1:
                assert "Nothing typed" in payload["previous_actions"][-1]["result"]
                assert payload["previous_actions"][-1]["arguments"]["text"] == "Too short"
                name, arguments = "type_text", {"node_id": list(target), "text": essay}
            else:
                assert all("text" not in action["arguments"] for action in payload["previous_actions"])
                name, arguments = "reply", {"text": "Written and verified", "done": True}
            call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])
        client = Mock()
        client.chat.completions.create.side_effect = choose
        with patch.object(agent, "_client", client), patch.dict(os.environ, {"LLM_MODEL": "fake"}), \
             patch.object(agent, "type_text", wraps=agent.type_text) as entry:
            state = {"window": window, "process_id": process.pid}
            result = agent.run_desktop_agent("Write 300 words in the first field of this open test window", state)
        actual = _edit_text(win32gui.GetDlgItem(handle, 201))
        assert actual == essay and len(actual.split()) == 300
        assert result == "Written and verified"
        assert len(payloads) == 3 and entry.call_count == 1
        print("PASS: native tool calling, wrong-count rejection, real 300-word entry, fresh completion check. Zero API calls.", flush=True)
    finally:
        if win32gui.IsWindow(handle):
            win32gui.PostMessage(handle, win32con.WM_CLOSE, 0, 0)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def test_word():
    "Checks text entry in a new disposable Word document without editing personal documents."
    import win32com.client
    word = win32com.client.DispatchEx("Word.Application")
    existing_documents = word.Documents.Count
    word.Visible = True
    document = word.Documents.Add()
    try:
        document.Content.Text = "Old test content."
        document.Activate()
        word.Activate()
        window = Desktop(backend="uia").window(handle=document.ActiveWindow.Hwnd).wrapper_object()
        print("Word window class:", win32gui.GetClassName(window.handle), "root matches:", win32gui.GetAncestor(window.handle, 2) == win32gui.GetForegroundWindow(), flush=True)
        observation = read_window(window)
        targets = []
        for node, control in observation["controls"].items():
            if control.element_info.control_type == "Document":
                try:
                    if "Old test content." in control.iface_text.DocumentRange.GetText(-1):
                        targets.append(node)
                except Exception:
                    pass
        assert len(targets) == 1, "Could not identify one editable Word document"
        text = "AI impact on education\n\nAI can support learning and help teachers prepare lessons.\nLiteral symbols: + ^ % ~ (test) {ENTER}. Caf\u00e9"
        try:
            result = type_text(observation, targets[0], text)
        except RuntimeError:
            print("Word target foreground:", win32gui.GetForegroundWindow() == window.handle, "editor focused:", observation["controls"][targets[0]].has_keyboard_focus(), flush=True)
            print("Word fixture actual text:", ascii(document.Content.Text), flush=True)
            print("Word fixture expected:", ascii(text), flush=True)
            raise
        actual = document.Content.Text.replace("\r", "\n")
        assert actual in (text, text + "\n"), repr(actual)
        assert "verified" in result
        print("PASS: Word document replaced and independently verified, including literal symbols and Unicode.", flush=True)
    finally:
        document.Close(SaveChanges=0)  # Discard only the document created by this test.
        if not existing_documents:
            word.Quit(SaveChanges=0)


if __name__ == "__main__":
    if "--fixture" in sys.argv:
        fixture()
    else:
        test_native_window()
        test_connected_agent()
        test_word()
        print("Zero model calls. No personal documents used.")
