"""Test desktop tool calling and CLI wiring without API usage or real input."""

from contextlib import ExitStack
from copy import deepcopy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cli_
import desktop_
import desktop_agent_ as agent


# Make a native tool-call reply like the API returns, without calling the API.
def _response(name, arguments):
    call = SimpleNamespace(function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(tool_calls=[call]))])


# Windows objects must stay local, and the model sees only the selected window view.
def test_native_tool_payload_and_validation():
    client = Mock()
    client.chat.completions.create.return_value = _response("reply", {"text": "Hello", "done": False})
    observation = {"title": "Test", "elements": '[42, 1] Edit "Body"', "unavailable_controls": 0,
                   "window": object(), "controls": {(42, 1): object()}}
    with patch.dict(os.environ, {"LLM_MODEL": "fake"}), patch.object(agent, "_client", client):
        assert agent.get_desktop_action("Hi", observation)["tool"] == "reply"
        sent = client.chat.completions.create.call_args.kwargs
        payload = json.loads(sent["messages"][-1]["content"])
        assert set(payload["window"]) == {"title", "elements", "unavailable_controls"}
        assert sent["tool_choice"] == "required" and sent["parallel_tool_calls"] is False
        for name, arguments in (("unknown", {}), ("click_control", {"node_id": [True]}),
                                ("reply", {"text": "Hi", "done": "yes"}),
                                ("observe", {"extra": 1})):
            client.chat.completions.create.return_value = _response(name, arguments)
            with unittest.TestCase().assertRaises(RuntimeError):
                agent.get_desktop_action("Test", observation)
        client.chat.completions.create.return_value.choices[0].message.tool_calls = []
        with unittest.TestCase().assertRaises(RuntimeError):
            agent.get_desktop_action("Test", observation)


# Supply fake desktop tools so the complete controller can run safely in unit tests.
def _tools(stack):
    names = ("find_app", "open_app", "press_key", "click_control", "type_text", "read_text", "_observe", "get_desktop_action")
    tools = {name: stack.enter_context(patch.object(agent, name)) for name in names}
    tools["find_app"].return_value = r"C:\Apps\example.exe"
    tools["open_app"].return_value.process_id.return_value = 12
    tools["_observe"].return_value = {"title": "Test", "elements": '[42, 1] Document "Body"'}
    tools["type_text"].return_value = "Text entered and verified."
    tools["press_key"].return_value = "Keys sent."
    return tools


# Opening, creating, writing 300 words, and finishing must retain the original goal.
def test_complete_desktop_flow():
    text = " ".join(["word"] * 300)
    request = "Open Word and write an essay in 300 words"
    actions = iter([
        {"tool": "open_app", "arguments": {"executable": "winword.exe"}},
        {"tool": "press_key", "arguments": {"keys": ["CTRL", "N"]}},
        {"tool": "type_text", "arguments": {"node_id": [42, 1], "text": text}},
        {"tool": "reply", "arguments": {"text": "Written and verified.", "done": True}},
    ])
    decisions = []
    with ExitStack() as stack:
        tools = _tools(stack)
        def choose(goal, observation, history):
            decisions.append((goal, deepcopy(history)))
            return next(actions)
        tools["get_desktop_action"].side_effect = choose
        tools["read_text"].return_value = text + "\n"
        assert agent.run_desktop_agent(request, {}) == "Written and verified."
        assert all(goal == request for goal, _ in decisions)
        assert [len(history) for _, history in decisions] == [0, 1, 2, 3]
        assert "text" not in decisions[-1][1][-1]["arguments"]
        tools["type_text"].assert_called_once()
        tools["read_text"].assert_called_once()
        assert tools["_observe"].call_count == 3


# Wrong-length writing must be revised before any text reaches the app.
def test_word_count_before_input():
    correct = " ".join(["word"] * 300)
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["read_text"].return_value = correct
        tools["get_desktop_action"].side_effect = [
            {"tool": "type_text", "arguments": {"node_id": [42, 1], "text": "Too short"}},
            {"tool": "type_text", "arguments": {"node_id": [42, 1], "text": correct}},
            {"tool": "reply", "arguments": {"text": "Finished", "done": True}},
        ]
        assert agent.run_desktop_agent("Write 300 words", {"window": Mock()}) == "Finished"
        tools["type_text"].assert_called_once_with(tools["_observe"].return_value, [42, 1], correct)


# A model completion claim cannot replace verified writing and a fresh text check.
def test_unverified_completion_is_refused():
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["get_desktop_action"].return_value = {"tool": "reply", "arguments": {"text": "Done", "done": True}}
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "not been entered"):
            agent.run_desktop_agent("Write 300 words", {"window": Mock()})
        tools["type_text"].assert_not_called()
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["get_desktop_action"].side_effect = [
            {"tool": "type_text", "arguments": {"node_id": [42, 1], "text": "Hello"}},
            {"tool": "reply", "arguments": {"text": "Done", "done": True}},
        ]
        tools["read_text"].return_value = "Changed later"
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "changed after typing"):
            agent.run_desktop_agent("Write Hello", {"window": Mock()})


# Uncertain input stops immediately; repeated actions and model calls are bounded.
def test_failures_and_limits():
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["get_desktop_action"].return_value = {"tool": "click_control", "arguments": {"node_id": [42, 1]}}
        tools["click_control"].side_effect = RuntimeError("Uncertain click")
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "Uncertain"):
            agent.run_desktop_agent("Click", {"window": Mock()})
        tools["get_desktop_action"].assert_called_once()
        tools["click_control"].assert_called_once()
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["get_desktop_action"].return_value = {"tool": "observe", "arguments": {}}
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "repeated"):
            agent.run_desktop_agent("Observe", {"window": Mock()})
        assert tools["get_desktop_action"].call_count == 2
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["get_desktop_action"].side_effect = [
            {"tool": "open_app", "arguments": {"executable": f"app{number}.exe"}} for number in range(10)
        ]
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "10 model decisions"):
            agent.run_desktop_agent("Open apps", {})
        assert tools["get_desktop_action"].call_count == 10


# Desktop is the default; browser mode still calls the original browser engine.
def test_cli_modes_and_exit():
    for mode in ("desktop", "browser"):
        with patch("builtins.input", side_effect=["Hi", "exit"]), patch("builtins.print"), \
             patch.object(cli_, "run_desktop_agent", return_value="Hello") as desktop, \
             patch.object(cli_, "run_agent", return_value="Hello") as browser:
            with patch.object(cli_.sys, "argv", ["chexsa", mode]):
                cli_.main()
            assert desktop.call_count == (1 if mode == "desktop" else 0)
            assert browser.call_count == (1 if mode == "browser" else 0)
    with patch.object(cli_.sys, "argv", ["chexsa"]), patch("builtins.input", return_value="exit"), patch("builtins.print"), \
         patch.object(cli_, "run_desktop_agent") as desktop, patch.object(cli_, "run_agent") as browser:
        cli_.main()
        desktop.assert_not_called()
        browser.assert_not_called()


# App names cannot contain shell arguments, and shortcuts consume their reading once.
def test_app_lookup_and_shortcut_guards():
    for name in ("winword.exe /x", "cmd.exe & other.exe", "C:\\Apps\\word.exe", "word"):
        with unittest.TestCase().assertRaises(ValueError):
            desktop_.find_app(name)
    with patch.object(desktop_, "which", return_value=None), patch.object(desktop_.winreg, "OpenKey"), \
         patch.object(desktop_.winreg, "QueryValueEx", return_value=(r"C:\Apps\winword.exe", 1)), \
         patch.object(desktop_.Path, "is_file", return_value=True):
        assert desktop_.find_app("winword.exe") == r"C:\Apps\winword.exe"
    window = Mock()
    window.element_info.runtime_id = (42, 10)
    window.descendants.return_value = []
    observation = desktop_.read_window(window)
    with patch.object(desktop_, "focus_window"):
        desktop_.press_key(observation, ["CTRL", "N"])
    window.type_keys.assert_called_once_with("^n", set_foreground=False, pause=0, turn_off_numlock=False)
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "Read the window again"):
        desktop_.press_key(observation, ["ENTER"])


# A disappearing startup window may be replaced only by one window in its own process.
def test_startup_window_recovery():
    old, replacement, native = Mock(), Mock(), Mock()
    old.is_visible.return_value = False
    native.handle = 123
    with patch.object(agent, "Desktop") as desktop, patch.object(agent, "read_window", return_value={"title": "Ready"}), \
         patch.object(agent, "sleep"):
        desktop.return_value.windows.return_value = [native]
        desktop.return_value.window.return_value.wrapper_object.return_value = replacement
        state = {"window": old, "process_id": 12}
        assert agent._observe(state) == {"title": "Ready"}
        assert state["window"] is replacement
        desktop.return_value.windows.assert_called_once_with(process=12)


# Closing an app between requests must not leave the CLI permanently stuck.
def test_closed_app_allows_a_new_request():
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["_observe"].side_effect = [RuntimeError("Closed"), {"title": "New app", "elements": ""}]
        tools["get_desktop_action"].side_effect = [
            {"tool": "open_app", "arguments": {"executable": "winword.exe"}},
            {"tool": "reply", "arguments": {"text": "Opened", "done": True}},
        ]
        assert agent.run_desktop_agent("Open Word", {"window": Mock(), "process_id": 99}) == "Opened"
        tools["open_app"].assert_called_once()


# A file task must work without an app, and completion must read the real saved file.
def test_direct_file_task():
    from pathlib import Path
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as directory:
        path = Path(directory) / "hello.py"
        actions = [
            {"tool": "write_file", "arguments": {"path": str(path), "content": "print('hello')\n", "done": False}},
            {"tool": "reply", "arguments": {"text": str(path), "done": True}},
        ]
        with patch.object(agent, "get_desktop_action", side_effect=actions), patch.object(agent, "open_app") as launch, \
             patch.object(agent, "_observe") as observe:
            assert agent.run_desktop_agent("Create hello.py", {}) == str(path)
            assert path.read_text() == "print('hello')\n"
            launch.assert_not_called()
            observe.assert_not_called()
        with patch.object(agent, "get_desktop_action", return_value=actions[0]):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "already exists"):
                agent.run_desktop_agent("Create hello.py", {})
        with patch.object(agent, "get_desktop_action", return_value=actions[1]):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "not been created"):
                agent.run_desktop_agent("Create hello.py", {})
        def choose(request, observation, history):
            if not history:
                return actions[0]
            path.write_text("print('changed')\n")
            return actions[1]
        text_path = Path(directory) / "notes.txt"
        with patch.object(agent, "get_desktop_action", side_effect=[
            {"tool": "write_file", "arguments": {"path": str(text_path), "content": "Hello Mashrafee", "done": False}},
            {"tool": "reply", "arguments": {"text": "Saved", "done": True}},
        ]), patch.object(agent, "open_app") as launch:
            assert agent.run_desktop_agent("Create notes.txt containing Hello Mashrafee", {}) == "Saved"
            assert text_path.read_text() == "Hello Mashrafee"
            launch.assert_not_called()
        path.unlink()
        with patch.object(agent, "get_desktop_action", side_effect=choose):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "file changed"):
                agent.run_desktop_agent("Create hello.py", {})


        # One request can save two files and finish immediately after the last save.
        paths = [Path(directory) / name for name in ("first.txt", "second.txt")]
        saves = [{"tool": "write_file", "arguments": {
            "path": str(target), "content": "Hello", "done": index == 1,
        }} for index, target in enumerate(paths)]
        with patch.object(agent, "get_desktop_action", side_effect=saves) as choose:
            result = agent.run_desktop_agent("Create first.txt and second.txt", {})
            assert choose.call_count == 2
            assert result.startswith("Created and saved:\n"), result
            assert {Path(line).resolve() for line in result.splitlines()[1:]} == {target.resolve() for target in paths}, result
            assert all(target.read_text() == "Hello" for target in paths)
        with patch.object(agent, "get_desktop_action", return_value=saves[-1]), \
             patch.object(agent, "write_file", side_effect=RuntimeError("File read-back failed")):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "read-back failed"):
                agent.run_desktop_agent("Create second.txt", {})


# Both immediate and later completion must verify Word packages without opening Word.
def test_direct_word_document():
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from docx import Document
    for final_save in (True, False):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "essay.docx"
            content = "AI in education\n\nAI can help teachers and students."
            actions = [{"tool": "write_file", "arguments": {
                "path": str(path), "content": content, "done": final_save,
            }}]
            if not final_save:
                actions.append({"tool": "reply", "arguments": {"text": "Saved", "done": True}})
            with patch.object(agent, "get_desktop_action", side_effect=actions) as choose, \
                 patch.object(agent, "open_app") as launch, patch.object(agent, "_observe") as observe:
                result = agent.run_desktop_agent("Create a Word document called essay.docx", {})
                assert result
                assert choose.call_count == (1 if final_save else 2)
                launch.assert_not_called()
                observe.assert_not_called()
            assert "\n".join(p.text for p in Document(path).paragraphs) == content


# Let unittest run these functions without adding application or test classes.
def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_native_tool_payload_and_validation, test_complete_desktop_flow,
        test_word_count_before_input, test_unverified_completion_is_refused,
        test_failures_and_limits, test_cli_modes_and_exit,
        test_app_lookup_and_shortcut_guards, test_startup_window_recovery,
        test_closed_app_allows_a_new_request, test_direct_file_task,
        test_direct_word_document,
    ))
