"""Check app selection without opening windows or using API tokens."""

from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

import desktop_


def test_window_selection():
    "Checks that the correct app window is chosen and ambiguous matches are rejected."
    cases = ("direct", "loading", "handoff", "ambiguous", "missing")
    for case in cases:
        app, desktop = Mock(), Mock()
        app.process = 10
        app.is_process_running.return_value = case == "loading"
        target, other = Mock(), Mock()
        target.process_id.return_value = 20
        other.process_id.return_value = 30
        if case == "direct":
            desktop.windows.return_value = [target]
        elif case == "loading":
            desktop.windows.side_effect = [[], [target]]
        else:
            desktop.windows.side_effect = [[], [target, other]]

        with ExitStack() as patches:
            application = patches.enter_context(patch.object(desktop_, "Application"))
            application.return_value.start.return_value = app
            patches.enter_context(patch.object(desktop_, "Desktop", return_value=desktop))
            paths = {20: r"C:\Apps\NOTEPAD.EXE", 30: r"C:\Apps\other.exe"}
            if case == "ambiguous":
                paths[30] = r"C:\Second\notepad.exe"
            if case == "missing":
                paths[20] = r"C:\Apps\notepad-helper.exe"
            patches.enter_context(patch.object(desktop_, "process_module", side_effect=paths.__getitem__))
            patches.enter_context(patch.object(desktop_, "sleep"))
            patches.enter_context(patch.object(desktop_, "monotonic", side_effect=[0, 0, 16] if case == "missing" else [0, 0, 1]))
            if case in ("ambiguous", "missing"):
                expected = "More than one" if case == "ambiguous" else "within 15 seconds"
                with unittest.TestCase().assertRaisesRegex(RuntimeError, expected):
                    desktop_.open_app(r'"C:\Apps\notepad.exe" /new')
            else:
                assert desktop_.open_app(r'"C:\Apps\notepad.exe" /new') is target, case


def test_invalid_launches():
    "Checks that invalid app names and failed launches stop cleanly."
    with patch.object(desktop_, "Application") as application:
        for value in (None, 17, "", "   "):
            with unittest.TestCase().assertRaises(ValueError):
                desktop_.open_app(value)
        application.assert_not_called()
        application.return_value.start.side_effect = OSError("App not installed")
        with patch.object(desktop_, "Desktop") as desktop:
            with unittest.TestCase().assertRaises(OSError):
                desktop_.open_app("missing.exe")
            desktop.return_value.windows.assert_not_called()


def test_read_window_controls():
    "Checks that visible Windows controls keep separate IDs, including same-name buttons."
    window = Mock()
    window.element_info.runtime_id = (42, 1000)
    window.window_text.return_value = "Document - Example"
    controls = []
    for node_id, kind, name, visible, enabled in (
        ((42, 1), "Button", "Save", True, True),
        ((42, 2), "Button", "Save", True, False),
        ((42, 3), "Edit", "", True, True),
        ((42, 4), "Text", "Saved successfully", True, True),
        ((42, 5), "Button", "Hidden", False, True),
        ((42, 6), "Pane", "Layout", True, True),
    ):
        control = Mock()
        control.element_info = SimpleNamespace(runtime_id=node_id, control_type=kind, name=name)
        control.is_visible.return_value = visible
        control.is_enabled.return_value = enabled
        controls.append(control)
    window.descendants.return_value = controls
    view = desktop_.read_window(window)
    assert view["title"] == "Document - Example"
    assert view["controls"] == dict(zip(((42, 1), (42, 2), (42, 3), (42, 4)), controls[:4]))
    assert '[42, 1] Button "Save"' in view["elements"]
    assert '[42, 2] Button "Save" | disabled' in view["elements"]
    assert '[42, 3] Edit ""' in view["elements"]
    assert 'Text "Saved successfully"' in view["elements"]
    assert "Hidden" not in view["elements"] and "Layout" not in view["elements"]
    for control in controls:
        control.click_input.assert_not_called()
        control.set_focus.assert_not_called()


def test_read_window_unavailable():
    "Checks that missing controls and hidden windows are handled clearly."
    window, disappeared, missing_id = Mock(), Mock(), Mock()
    window.element_info.runtime_id = (42, 1001)
    disappeared.is_visible.side_effect = OSError("Control disappeared")
    disappeared.element_info.control_type = "Button"
    missing_id.element_info = SimpleNamespace(control_type="Edit", runtime_id=0)
    window.descendants.return_value = [disappeared, missing_id]
    view = desktop_.read_window(window)
    assert view["unavailable_controls"] == 2
    assert not view["controls"] and not view["elements"]
    window.is_visible.return_value = False
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "closed or hidden"):
        desktop_.read_window(window)


# Build a small fake reading so action checks never need a real desktop or API.
def _reading(kind="Edit"):
    window, control = Mock(), Mock()
    window.element_info.runtime_id = (42, 100)
    window.handle = 100
    window.window_text.return_value = "Test window"
    control.element_info = SimpleNamespace(runtime_id=(42, 1), control_type=kind, name="Target")
    control.top_level_parent.return_value = window
    control.iface_value.CurrentIsReadOnly = False
    window.descendants.return_value = [control]
    return desktop_.read_window(window), control


def test_click_exact_control_and_refresh():
    "Checks that clicking uses the exact chosen control and then requires a fresh reading."
    reading, first = _reading("Button")
    second = Mock()
    second.element_info = SimpleNamespace(runtime_id=(42, 2), control_type="Button", name="Target")
    second.top_level_parent.return_value = reading["window"]
    reading["window"].descendants.return_value = [first, second]
    current = desktop_.read_window(reading["window"])
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "old or already used"):
        desktop_.click_control(reading, [42, 1])
    desktop_.click_control(current, [42, 2])
    first.iface_invoke.Invoke.assert_not_called()
    second.iface_invoke.Invoke.assert_called_once()
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "old or already used"):
        desktop_.click_control(current, [42, 2])
    second.iface_invoke.Invoke.assert_called_once()


def test_action_target_guards():
    "Checks that old, missing, moved, hidden, and disabled controls cannot receive input."
    for case in ("invalid", "missing", "changed", "moved", "hidden", "disabled", "closed"):
        reading, control = _reading("Button")
        node_id = [42, 1]
        if case == "invalid":
            node_id = [True, 1]
        elif case == "missing":
            node_id = [42, 999]
        elif case == "changed":
            control.element_info.runtime_id = (42, 2)
        elif case == "moved":
            control.top_level_parent.return_value.element_info.runtime_id = (42, 999)
        elif case == "hidden":
            control.is_visible.return_value = False
        elif case == "disabled":
            control.is_enabled.return_value = False
        elif case == "closed":
            reading["window"].is_visible.return_value = False
        with unittest.TestCase().assertRaises((RuntimeError, ValueError)):
            desktop_.click_control(reading, node_id)
        control.iface_invoke.Invoke.assert_not_called()
        control.click_input.assert_not_called()


def test_click_failure_is_not_retried():
    "Checks that a failed click is not repeated automatically."
    reading, control = _reading("Button")
    control.iface_invoke.Invoke.side_effect = OSError("Connection lost")
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "uncertain"):
        desktop_.click_control(reading, [42, 1])
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "old or already used"):
        desktop_.click_control(reading, [42, 1])
    control.iface_invoke.Invoke.assert_called_once()


def test_type_field_verification():
    "Checks that a text field contains exactly what was requested after typing."
    reading, control = _reading()
    text = "AI + education: {ENTER} ^ % ~ (test)\nCafé"
    control.iface_value.CurrentValue = text
    assert "verified" in desktop_.type_text(reading, [42, 1], text)
    control.iface_value.SetValue.assert_called_once_with(text)
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "old or already used"):
        desktop_.type_text(reading, [42, 1], text)
    for case in ("readonly", "mismatch", "invalid", "not_editable"):
        reading, control = _reading("Button" if case == "not_editable" else "Edit")
        control.iface_value.CurrentIsReadOnly = case == "readonly"
        control.iface_value.CurrentValue = "Truncated"
        with unittest.TestCase().assertRaises((RuntimeError, ValueError)):
            desktop_.type_text(reading, [42, 1], None if case == "invalid" else "Hello")
        assert control.iface_value.SetValue.call_count == (1 if case == "mismatch" else 0)


def test_type_document_focus_and_verification():
    "Checks that document typing needs the correct focus and a matching text reading."
    for focus, foreground in ((True, 100), (False, 100), (True, 999)):
        reading, control = _reading("Document")
        control.has_keyboard_focus.return_value = focus
        control.iface_text.DocumentRange.GetAttributeValue.return_value = False
        control.iface_text.DocumentRange.GetText.return_value = "Hello {ENTER} + AI\r"
        with patch.object(type(control), "iface_value", new_callable=PropertyMock, create=True) as value:
            value.side_effect = desktop_.NoPatternInterfaceError
            with patch.object(control, "type_keys") as send, patch.object(desktop_.win32gui, "GetForegroundWindow", return_value=foreground), patch.object(desktop_.win32gui, "SetForegroundWindow"):
                if focus and foreground == 100:
                    assert "verified" in desktop_.type_text(reading, [42, 1], "Hello {ENTER} + AI")
                    assert send.call_count == 2
                    literal = send.call_args.args[0]
                    assert "{{}ENTER{}}" in literal and "{+}" in literal
                else:
                    with unittest.TestCase().assertRaisesRegex(RuntimeError, "could not be verified"):
                        desktop_.type_text(reading, [42, 1], "Hello")
                    send.assert_not_called()


def test_click_covered_target():
    "Checks that a mouse click stops if another control covers the target."
    reading, control = _reading("Edit")
    unrelated = Mock()
    unrelated.element_info.runtime_id = (99, 1)
    unrelated.parent.return_value = None
    with patch.object(type(control), "iface_invoke", new_callable=PropertyMock, create=True) as invoke:
        invoke.side_effect = desktop_.NoPatternInterfaceError
        with patch.object(desktop_, "Desktop") as desktop, patch.object(desktop_, "focus_window"):
            desktop.return_value.from_point.return_value = unrelated
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "uncertain"):
                desktop_.click_control(reading, [42, 1])
    control.click_input.assert_not_called()


def test_document_emoji_is_rejected_before_editing():
    "Checks that unsupported emoji are rejected before keyboard typing starts."
    reading, control = _reading("Document")
    with patch.object(type(control), "iface_value", new_callable=PropertyMock, create=True) as value:
        value.side_effect = desktop_.NoPatternInterfaceError
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "not supported"):
            desktop_.type_text(reading, [42, 1], "Hello 😀")
    control.set_focus.assert_not_called()
    control.type_keys.assert_not_called()


def test_transient_text_match_is_not_success():
    "Checks that a brief text match followed by different text is not reported as success."
    reading, control = _reading()
    values = iter(["Hello", "Changed later"])
    with patch.object(type(control.iface_value), "CurrentValue", new_callable=PropertyMock, create=True) as value:
        value.side_effect = lambda: next(values, "Changed later")
        with patch.object(desktop_, "monotonic", side_effect=[0, 0, 0.3, 3]), patch.object(desktop_, "sleep"):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "could not be verified"):
                desktop_.type_text(reading, [42, 1], "Hello")
    control.iface_value.SetValue.assert_called_once_with("Hello")


# Let the existing unittest command run these plain test functions without new classes.
def test_toggle_control_verifies_a_known_state():
    """UI Automation can set a Windows toggle without physical input."""
    reading, control = _reading()
    toggle = control.iface_toggle
    toggle.CurrentToggleState = 0
    toggle.Toggle.side_effect = lambda: setattr(toggle, "CurrentToggleState", 1)
    node = next(iter(reading["controls"]))
    assert desktop_.toggle_control(reading, node, False)["verified"]
    toggle.Toggle.assert_not_called()
    assert desktop_.toggle_control(reading, node, True)["verified"]
    toggle.Toggle.assert_called_once_with()
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "old or already used"):
        desktop_.toggle_control(reading, node, False)


def test_select_control_verifies_the_exact_item():
    """Selection is checked through the control, without another click."""
    reading, control = _reading("ListItem")
    selection = control.iface_selection_item
    selection.CurrentIsSelected = False
    selection.Select.side_effect = lambda: setattr(selection, "CurrentIsSelected", True)
    node = next(iter(reading["controls"]))
    assert desktop_.select_control(reading, node) == {"selected": True, "verified": True}
    selection.Select.assert_called_once_with()
    control.click_input.assert_not_called()


def test_expand_control_checks_the_pattern_state():
    """A leaf never gets input, and an expandable item can be opened."""
    reading, control = _reading("TreeItem")
    group = control.iface_expand_collapse
    group.CurrentExpandCollapseState = 3
    node = next(iter(reading["controls"]))
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "no expandable"):
        desktop_.expand_control(reading, node, True)
    group.Expand.assert_not_called()
    group.CurrentExpandCollapseState = 0
    group.Expand.side_effect = lambda: setattr(group, "CurrentExpandCollapseState", 1)
    assert desktop_.expand_control(reading, node, True)["verified"]


def test_inspect_disabled_control_without_sending_input():
    """A disabled control can be described, and grants no actions."""
    reading, control = _reading("CheckBox")
    control.is_enabled.return_value = False
    node = next(iter(reading["controls"]))
    details = desktop_.inspect_control(reading, node)
    assert details["target"] == list(node)
    assert details["role"] == "checkbox"
    assert details["state"] == {"disabled": True}
    assert details["actions"] == []
    control.click_input.assert_not_called()


def test_read_selection_keeps_password_fields_private():
    """Known selected text can be read without a click or clipboard access."""
    reading, control = _reading("Document")
    selection = control.iface_text.GetSelection.return_value
    selection.Length = 1
    selection.GetElement.return_value.GetText.return_value = "Only this text"
    node = next(iter(reading["controls"]))
    control.element_info.element = SimpleNamespace(CurrentIsPassword=True)
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "Password"):
        desktop_.read_selection(reading, node)
    control.iface_text.GetSelection.assert_not_called()
    control.element_info.element.CurrentIsPassword = False
    assert desktop_.read_selection(reading, node) == {"text": "Only this text", "more": False}


def test_focus_control_requires_the_exact_focused_id():
    """Another focused field cannot count as success."""
    reading, control = _reading()
    control.has_keyboard_focus.return_value = False
    node = next(iter(reading["controls"]))
    with patch.object(desktop_, "IUIA") as uia:
        uia.return_value.iuia.GetFocusedElement.return_value.GetRuntimeId.return_value = (99,)
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "verify focus"):
            desktop_.focus_control(reading, node)
    control.set_focus.assert_called_once_with()


def test_find_open_app_matches_full_program_path():
    """Same-named executables and duplicate windows cannot be guessed."""
    target, other = Mock(), Mock()
    target.process_id.return_value = 10
    other.process_id.return_value = 20
    windows = {10: r"C:\Apps\editor.exe", 20: r"C:\Elsewhere\editor.exe"}
    with patch.object(desktop_, "Desktop") as ui, patch.object(desktop_, "process_module", side_effect=windows.__getitem__):
        ui.return_value.windows.return_value = [target, other]
        assert desktop_.find_open_app(windows[10]) is target
        ui.return_value.windows.return_value = [target, target]
        with unittest.TestCase().assertRaises(RuntimeError):
            desktop_.find_open_app(windows[10])


def test_scroll_control_reads_the_native_scroll_position():
    """Scroll reports movement without assuming a mouse wheel went to the right window."""
    reading, control = _reading("List")
    node = next(iter(reading["controls"]))
    scrolling = control.iface_scroll
    scrolling.CurrentVerticallyScrollable = True
    scrolling.CurrentVerticalScrollPercent = 25
    scrolling.Scroll.side_effect = lambda *args: setattr(scrolling, "CurrentVerticalScrollPercent", 50)
    assert desktop_.scroll_control(reading, node, "down") == {"moved": True}
    scrolling.Scroll.assert_called_once_with(2, 3)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_window_selection, test_invalid_launches,
        test_read_window_controls, test_read_window_unavailable,
        test_toggle_control_verifies_a_known_state, test_select_control_verifies_the_exact_item,
        test_find_open_app_matches_full_program_path,
        test_expand_control_checks_the_pattern_state, test_inspect_disabled_control_without_sending_input,
        test_read_selection_keeps_password_fields_private, test_focus_control_requires_the_exact_focused_id,
        test_scroll_control_reads_the_native_scroll_position,
        test_click_exact_control_and_refresh, test_action_target_guards,
        test_click_failure_is_not_retried, test_type_field_verification,
        test_type_document_focus_and_verification, test_click_covered_target,
        test_document_emoji_is_rejected_before_editing, test_transient_text_match_is_not_success,
    ))
