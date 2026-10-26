"""Check app selection without opening windows or using API tokens."""

from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, PropertyMock, patch

import desktop_


# Check that we return the right app, wait for its window, and refuse guesses.
def test_window_selection():
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


# Invalid names and failed launches must stop before selecting a window.
def test_invalid_launches():
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


# Same-name buttons need separate IDs, while hidden and layout-only items stay out.
def test_read_window_controls():
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


# Missing controls are reported, and reading a hidden window fails clearly.
def test_read_window_unavailable():
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


# A click must use the chosen object once, even if another button has the same name.
def test_click_exact_control_and_refresh():
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


# Reject invalid, missing, moved, hidden, disabled, and detached targets before input.
def test_action_target_guards():
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


# Failed clicks remain uncertain and cannot be repeated with the same reading.
def test_click_failure_is_not_retried():
    reading, control = _reading("Button")
    control.iface_invoke.Invoke.side_effect = OSError("Connection lost")
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "uncertain"):
        desktop_.click_control(reading, [42, 1])
    with unittest.TestCase().assertRaisesRegex(RuntimeError, "old or already used"):
        desktop_.click_control(reading, [42, 1])
    control.iface_invoke.Invoke.assert_called_once()


# Ordinary fields must contain exactly the requested literal text after entry.
def test_type_field_verification():
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


# Documents need confirmed focus and literal typing, with no automatic retry.
def test_type_document_focus_and_verification():
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


# A mouse fallback must refuse a point covered by another control.
def test_click_covered_target():
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


# Unsupported document characters must be rejected before focus or text changes.
def test_document_emoji_is_rejected_before_editing():
    reading, control = _reading("Document")
    with patch.object(type(control), "iface_value", new_callable=PropertyMock, create=True) as value:
        value.side_effect = desktop_.NoPatternInterfaceError
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "not supported"):
            desktop_.type_text(reading, [42, 1], "Hello 😀")
    control.set_focus.assert_not_called()
    control.type_keys.assert_not_called()


# A brief match followed by different text must never count as verified entry.
def test_transient_text_match_is_not_success():
    reading, control = _reading()
    values = iter(["Hello", "Changed later"])
    with patch.object(type(control.iface_value), "CurrentValue", new_callable=PropertyMock, create=True) as value:
        value.side_effect = lambda: next(values, "Changed later")
        with patch.object(desktop_, "monotonic", side_effect=[0, 0, 0.3, 3]), patch.object(desktop_, "sleep"):
            with unittest.TestCase().assertRaisesRegex(RuntimeError, "could not be verified"):
                desktop_.type_text(reading, [42, 1], "Hello")
    control.iface_value.SetValue.assert_called_once_with("Hello")


# Let the existing unittest command run these plain test functions without new classes.
def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_window_selection, test_invalid_launches,
        test_read_window_controls, test_read_window_unavailable,
        test_click_exact_control_and_refresh, test_action_target_guards,
        test_click_failure_is_not_retried, test_type_field_verification,
        test_type_document_focus_and_verification, test_click_covered_target,
        test_document_emoji_is_rejected_before_editing, test_transient_text_match_is_not_success,
    ))
