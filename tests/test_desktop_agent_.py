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


def test_native_tool_payload_and_validation():
    "Checks that desktop tool requests contain allowed arguments and keep Windows objects local."
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


def test_complete_desktop_flow():
    "Checks the open-app, new-document, type, and completion steps with fake tools."
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


def test_word_count_before_input():
    "Checks that a wrong word count is rejected before text is entered."
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


def test_unverified_completion_is_refused():
    "Checks that the model cannot claim writing is finished without matching saved evidence."
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


def test_failures_and_limits():
    "Checks that uncertain actions, repeated actions, and endless model calls stop."
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


def test_cli_modes_and_exit():
    "Checks that desktop and browser modes call the right agent and exit cleanly."
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


def test_app_lookup_and_shortcut_guards():
    "Checks app lookup and keyboard shortcuts without allowing shell arguments or old readings."
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


def test_startup_window_recovery():
    "Checks that a replaced startup window is found only inside the same app process."
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


def test_closed_app_allows_a_new_request():
    "Checks that closing an app does not prevent a later request from opening it again."
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["_observe"].side_effect = [RuntimeError("Closed"), {"title": "New app", "elements": ""}]
        tools["get_desktop_action"].side_effect = [
            {"tool": "open_app", "arguments": {"executable": "winword.exe"}},
            {"tool": "reply", "arguments": {"text": "Opened", "done": True}},
        ]
        assert agent.run_desktop_agent("Open Word", {"window": Mock(), "process_id": 99}) == "Opened"
        tools["open_app"].assert_called_once()


def test_direct_file_task():
    "Checks file creation, existing-file protection, final completion, multiple files, and failed saves without an editor."
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


def test_direct_word_document():
    "Checks that Word files can be created and verified without opening Word."
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
def test_busy_window_keeps_changes_and_can_find_hidden_duplicates():
    """Find both Save buttons without sending the whole window or reusing old IDs."""
    clutter = [f'[{i}] Edit "Field {i}"' for i in range(1, 81)]
    buttons = ['[91] Button "Save" | in "Draft"', '[92] Button "Save" | in "Copy"']
    previous = {"title": "Editor", "window_id": (1,), "elements": "\n".join(clutter + buttons)}
    current = {**previous, "elements": previous["elements"] + '\n[93] Edit "File name"', "focused": (93,)}
    view = agent._window_view(current, previous, "Write a note")
    assert view["elements"].splitlines()[0] == '[93] Edit "File name"'
    assert view["view"]["added_or_changed"] == 1
    assert "[92]" not in view["elements"]

    found = agent._window_view(current, previous, "Write a note", {"query": "Save", "offset": 0})
    assert found["elements"].splitlines() == buttons
    assert found["view"]["matches"] == 2
    assert found["view"]["next_offset"] is None
    page = agent._window_view(current, previous, "Write a note", {"query": "", "offset": 30})
    assert page["elements"].splitlines()[0] == clutter[30]
    assert page["view"]["next_offset"] == 60


def test_compact_view_rejects_ids_it_did_not_show():
    """An omitted or replaced control must be found before the model can use it."""
    client = Mock()
    lines = [f'[{i}] Edit "Field {i}"' for i in range(1, 81)]
    observation = {"title": "Editor", "elements": "\n".join(lines), "unavailable_controls": 0}
    view = agent._window_view(observation, None, "Fill a field")
    with patch.dict(os.environ, {"LLM_MODEL": "fake"}), patch.object(agent, "_client", client):
        for name, arguments in (
            ("click_control", {"node_id": [80]}),
            ("find_controls", {"query": "", "offset": True}),
            ("find_controls", {"query": "", "offset": -1}),
        ):
            client.chat.completions.create.return_value = _response(name, arguments)
            with unittest.TestCase().assertRaises(RuntimeError):
                agent.get_desktop_action("Fill a field", view)
        client.chat.completions.create.return_value = _response("click_control", {"node_id": [80]})
        found = agent._window_view(observation, None, "Fill a field", {"query": "Field 80", "offset": 0})
        assert agent.get_desktop_action("Fill a field", found)["arguments"]["node_id"] == [80]


def test_desktop_search_executes_on_the_full_fresh_reading():
    """Search exposes a replacement ID and the executor receives the real snapshot."""
    lines = [f'[{i}] Edit "Field {i}"' for i in range(1, 81)]
    before = {"title": "Editor", "elements": "\n".join(lines + ['[91] Button "Save"'])}
    after = {**before, "elements": "\n".join(lines + ['[92] Button "Save"'])}
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["_observe"].side_effect = [before, after, after]
        def choose(request, view, history):
            if not history:
                return {"tool": "find_controls", "arguments": {"query": "Save", "offset": 0}}
            if len(history) == 1:
                assert view["elements"] == '[92] Button "Save"'
                return {"tool": "click_control", "arguments": {"node_id": [92]}}
            return {"tool": "reply", "arguments": {"text": "Done", "done": True}}
        tools["get_desktop_action"].side_effect = choose
        assert agent.run_desktop_agent("Save the form", {"window": object()}) == "Done"
        tools["click_control"].assert_called_once_with(after, [92])


def test_file_save_keeps_the_previous_window_reading():
    """A non-final save keeps the previous reading after another desktop action."""
    lines = [f'[{i}] Edit "Field {i}"' for i in range(1, 41)]
    before = {"title": "Editor", "elements": "\n".join(lines), "window_id": (7,)}
    after = {**before, "elements": before["elements"] + '\n[91] Button "Apply"'}
    with ExitStack() as stack:
        tools = _tools(stack)
        tools["_observe"].side_effect = [before, after, after]
        stack.enter_context(patch.object(agent, "write_file", return_value="example.txt"))
        tools["get_desktop_action"].side_effect = [
            {"tool": "observe", "arguments": {}},
            {"tool": "write_file", "arguments": {
                "path": "example.txt", "content": "Hello", "done": False,
            }},
            {"tool": "click_control", "arguments": {"node_id": [91]}},
            {"tool": "reply", "arguments": {"text": "Done", "done": False}},
        ]
        assert agent.run_desktop_agent("Save a note and apply", {"window": object()}) == "Done"
        view = tools["get_desktop_action"].call_args_list[2].args[1]
        assert view["view"]["added_or_changed"] == 1
        tools["click_control"].assert_called_once_with(after, [91])


def test_tools_require_a_window_reading():
    """Before opening an app, offer only tools that can run without a window."""
    client = Mock()
    create = client.chat.completions.create
    with patch.dict(os.environ, {"LLM_MODEL": "fake"}), patch.object(agent, "_client", client):
        create.return_value = _response("open_app", {"executable": "notepad.exe"})
        assert agent.get_desktop_action("Open Notepad")["tool"] == "open_app"
        names = {tool["function"]["name"] for tool in create.call_args.kwargs["tools"]}
        assert names == {"open_app", "write_file", "reply"}

        create.return_value = _response("press_key", {"keys": ["ENTER"]})
        with unittest.TestCase().assertRaises(RuntimeError):
            agent.get_desktop_action("Open Notepad")

        window = {"title": "Editor", "elements": '[1] Edit "Text"', "unavailable_controls": 0}
        assert agent.get_desktop_action("Press Enter", window)["tool"] == "press_key"


def test_remember_only_verified_file_paths():
    """A later request can refer to the files that actually saved."""
    state = {}
    with patch.object(agent, "get_desktop_action", return_value={
        "tool": "write_file", "arguments": {"path": "note.txt", "content": "Hi", "done": True},
    }), patch.object(agent, "write_file", return_value=r"C:\\Fixture\\note.txt") as save:
        agent.run_desktop_agent("Create note.txt", state)
        assert state["recent_files"] == [r"C:\\Fixture\\note.txt"]
        save.side_effect = FileExistsError
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "already exists"):
            agent.run_desktop_agent("Create note.txt", state)
        assert state["recent_files"] == [r"C:\\Fixture\\note.txt"]


def test_create_then_edit_the_same_file_through_the_model_tools():
    """Both Python and Word follow-up edits use the remembered path and a short excerpt."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    for filename, source, query, old, new in (
        ("fib.py", "def fib(n):\n    return n\n\ndef other():\n    return 7\n",
         "fib", "return n", "return max(0, n)"),
        ("report.docx", "Introduction\nKeep the introduction\nConclusion\nLong ending",
         "Conclusion", "Long ending", "Short ending"),
    ):
        with TemporaryDirectory() as directory:
            client = Mock()
            create = client.chat.completions.create
            state = {}
            path = Path(directory) / filename

            def choose(**kwargs):
                """Use the actual menu and excerpt to choose a fixture action."""
                payload = json.loads(kwargs["messages"][-1]["content"])
                names = {tool["function"]["name"] for tool in kwargs["tools"]}
                if payload["request"].startswith("Create"):
                    assert "edit_file" not in names
                    return _response("write_file", {"path": str(path), "content": source, "done": True})
                assert "read_file_section" in names and "edit_file" in names
                assert payload["recent_files"] == [str(path.resolve())]
                if not payload["previous_actions"]:
                    return _response("read_file_section", {"path": "", "query": query})
                excerpt = payload["previous_actions"][-1]["result"]
                assert old in excerpt["text"] and "version" not in excerpt
                assert "def other" not in excerpt["text"] and "Keep the introduction" not in excerpt["text"]
                return _response("edit_file", {"path": "", "old": old, "new": new, "done": True})

            create.side_effect = choose
            with patch.dict(os.environ, {"LLM_MODEL": "fake"}), patch.object(agent, "_client", client), \
                 patch.object(agent, "open_app") as launch:
                agent.run_desktop_agent("Create " + filename, state)
                answer = agent.run_desktop_agent("Edit that same file", state)
                assert answer.startswith("Updated and verified:")
                assert create.call_count == 3
                launch.assert_not_called()
            assert agent.read_file(path) == source.replace(old, new, 1)


def test_explicit_file_replacement_and_ambiguous_targets():
    """An exact quoted change can run in one call, while an ambiguous path is refused."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory, patch.object(agent.files_, "OUTPUT_DIR", Path(directory)):
        path = Path(directory) / "note.txt"
        path.write_text("Hello", encoding="utf-8")
        client = Mock()
        client.chat.completions.create.return_value = _response("edit_file", {
            "path": "note.txt", "old": "Hello", "new": "Hi", "done": True,
        })
        with patch.dict(os.environ, {"LLM_MODEL": "fake"}), patch.object(agent, "_client", client):
            agent.run_desktop_agent('In note.txt: replace "Hello" with "Hi"', {})
        assert path.read_text(encoding="utf-8") == "Hi"
        assert client.chat.completions.create.call_count == 1
        with unittest.TestCase().assertRaisesRegex(ValueError, "More than one"):
            agent._file_target("", "Edit that file", [str(path), str(path.with_name("other.txt"))])
        with unittest.TestCase().assertRaisesRegex(ValueError, "exact file"):
            agent._file_target("", "Edit folder/note.txt", [str(path.resolve())])


def test_reading_a_file_cannot_count_as_a_saved_edit():
    """An unrelated window reading cannot verify a file change."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as directory, ExitStack() as stack:
        path = Path(directory) / "note.txt"
        path.write_text("Original", encoding="utf-8")
        tools = _tools(stack)
        tools["get_desktop_action"].side_effect = [
            {"tool": "read_file_section", "arguments": {"path": "", "query": ""}},
            {"tool": "reply", "arguments": {"text": "Updated", "done": True}},
        ]
        state = {"window": object(), "recent_files": [str(path.resolve())]}
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "no file edit was saved"):
            agent.run_desktop_agent("Shorten that file", state)
        assert path.read_text(encoding="utf-8") == "Original"


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_busy_window_keeps_changes_and_can_find_hidden_duplicates,
        test_compact_view_rejects_ids_it_did_not_show,
        test_desktop_search_executes_on_the_full_fresh_reading,
        test_file_save_keeps_the_previous_window_reading,
        test_tools_require_a_window_reading,
        test_remember_only_verified_file_paths,
        test_create_then_edit_the_same_file_through_the_model_tools,
        test_explicit_file_replacement_and_ambiguous_targets,
        test_reading_a_file_cannot_count_as_a_saved_edit,
        test_native_tool_payload_and_validation, test_complete_desktop_flow,
        test_word_count_before_input, test_unverified_completion_is_refused,
        test_failures_and_limits, test_cli_modes_and_exit,
        test_app_lookup_and_shortcut_guards, test_startup_window_recovery,
        test_closed_app_allows_a_new_request, test_direct_file_task,
        test_direct_word_document,
    ))
