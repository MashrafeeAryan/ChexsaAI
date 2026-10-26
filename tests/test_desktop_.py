"""Check app selection without opening windows or using API tokens."""

from contextlib import ExitStack
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

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


# Let the existing unittest command run these plain test functions without new classes.
def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_window_selection, test_invalid_launches,
        test_read_window_controls, test_read_window_unavailable,
    ))
