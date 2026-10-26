"""Check that one Chrome tree supplies both controls and ordinary page text."""

from copy import deepcopy
import unittest
from unittest.mock import Mock, call

import browser_


def example_tree():
    return [
        {"nodeId": "1", "backendDOMNodeId": 1, "role": {"value": "RootWebArea"}},
        {"nodeId": "2", "parentId": "1", "role": {"value": "main"}, "name": {"value": "Inbox"}},
        {"nodeId": "3", "parentId": "2", "role": {"value": "heading"}, "name": {"value": "Inbox"}},
        {"nodeId": "4", "parentId": "3", "role": {"value": "StaticText"}, "name": {"value": "Inbox"}},
        {"nodeId": "5", "parentId": "4", "role": {"value": "InlineTextBox"}, "name": {"value": "Inbox"}},
        {"nodeId": "6", "parentId": "2", "backendDOMNodeId": 16, "role": {"value": "button"}, "name": {"value": "Send"}},
        {"nodeId": "7", "parentId": "6", "role": {"value": "StaticText"}, "name": {"value": "Send"}},
        {"nodeId": "8", "parentId": "1", "role": {"value": "dialog"}, "name": {"value": "New Message"}},
        {"nodeId": "9", "parentId": "8", "backendDOMNodeId": 19, "role": {"value": "button"}, "name": {"value": "Send"}},
        {"nodeId": "10", "parentId": "9", "role": {"value": "StaticText"}, "name": {"value": "Send"}},
        {"nodeId": "11", "ignored": True, "role": {"value": "StaticText"}, "name": {"value": "Hidden"}},
        {"nodeId": "12", "role": {"value": "StaticText"}, "name": {"value": "  "}},
        {"nodeId": "13", "parentId": "8", "backendDOMNodeId": 113, "role": {"value": "textbox"}, "name": {"value": "Subject"}, "value": {"value": "Old subject"}},
    ]


class BrowserObservationTests(unittest.TestCase):
    def setUp(self):
        browser_._observations.clear()
        self.addCleanup(browser_._observations.clear)
        self.page = Mock()
        self.page.url = "https://example.test/mail"
        self.page.title.return_value = "Inbox"
        self.session = self.page.context.new_cdp_session.return_value
        self.nodes = example_tree()
        self.session.send.side_effect = self.chrome_response

    def chrome_response(self, command, parameters=None):
        if command == "DOM.getDocument":
            return {"root": {"backendNodeId": 1}}
        if command == "Accessibility.getFullAXTree":
            return {"nodes": self.nodes}
        raise AssertionError(f"Unexpected Chrome command: {command}")

    def test_text_is_preserved_without_inline_or_hidden_duplicates(self):
        observation = browser_.read_page(self.page)
        self.assertEqual(observation["content"], "Inbox\nSend\nSend")
        self.assertEqual(observation["url"], self.page.url)
        self.assertEqual(observation["title"], "Inbox")
        self.page.locator.assert_not_called()
        self.assertEqual(self.session.send.call_args_list, [
            call("DOM.getDocument", {"depth": 0}), call("Accessibility.getFullAXTree"),
        ])

    def test_duplicate_controls_keep_their_native_ids_and_parent_context(self):
        observation = browser_.read_page(self.page)
        self.assertIn('[16] button "Send" | context: main "Inbox"', observation["elements"])
        self.assertIn('[19] button "Send" | context: dialog "New Message"', observation["elements"])
        self.assertIn('[113] textbox "Subject"', observation["elements"])
        self.assertNotIn("heading", observation["elements"])
        self.assertEqual(browser_._observations[self.page]["nodes"], {16, 19, 113})

    def test_full_original_tree_stays_local_including_values_and_hierarchy(self):
        original = deepcopy(self.nodes)
        observation = browser_.read_page(self.page)
        saved = browser_._observations[self.page]
        self.assertEqual(saved["tree"], original)
        self.assertIs(saved["session"], self.session)
        self.assertEqual(saved["document"], 1)
        self.assertNotIn("tree", observation)
        self.assertNotIn("session", observation)

    def test_empty_tree_returns_empty_strings(self):
        self.nodes = []
        observation = browser_.read_page(self.page)
        self.assertEqual(observation["elements"], "")
        self.assertEqual(observation["content"], "")

    def test_new_read_replaces_previous_text_and_disconnects_previous_session(self):
        browser_.read_page(self.page)
        self.nodes = [{"nodeId": "20", "role": {"value": "StaticText"}, "name": {"value": "Message sent"}}]
        observation = browser_.read_page(self.page)
        self.session.detach.assert_called_once()
        self.assertEqual(observation["content"], "Message sent")
        self.assertEqual(browser_._observations[self.page]["nodes"], set())


if __name__ == "__main__":
    unittest.main()
