"""Check grouped action inputs without launching Chrome or calling a model."""

import unittest

from observations_ import validate_action_group, validate_wait


class BrowserActionInputTests(unittest.TestCase):
    def test_group_rejects_all_invalid_actions_before_execution(self):
        """Malformed, unknown, duplicate, or unsafe sequences cannot become a group."""
        type_action = {"action": "type", "backend_node_id": 1, "text": "Example"}
        click = {"action": "click", "backend_node_id": 2}
        invalid = [
            [],
            [type_action] * 6,
            [type_action, type_action],
            [click, type_action],
            [dict(type_action, backend_node_id=True)],
            [dict(type_action, backend_node_id=99)],
            [dict(type_action, text=12)],
            [dict(type_action, extra=True)],
            [{"action": "navigate", "url": "https://example.test"}],
            [None],
        ]
        for actions in invalid:
            with self.subTest(actions=actions), self.assertRaises(ValueError):
                validate_action_group(actions, {1, 2})
        self.assertEqual(
            validate_action_group([type_action, click], {1, 2}), [type_action, click]
        )

    def test_wait_rejects_unbounded_or_unknown_conditions(self):
        """The model cannot request endless polling or inspect an invented target."""
        for timeout in (0, -1, 6, True, float("inf"), float("nan"), "3"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                validate_wait(
                    {"action": "wait_for", "text": "Ready", "timeout": timeout}, {1}
                )
        for action in (
            {"action": "wait_for", "backend_node_id": 9, "state": "enabled"},
            {"action": "wait_for", "backend_node_id": True, "state": "enabled"},
            {"action": "wait_for", "backend_node_id": 1, "state": "guess"},
            {"action": "wait_for", "text": ""},
            {"action": "wait_for", "text": "Ready", "extra": True},
        ):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_wait(action, {1})
