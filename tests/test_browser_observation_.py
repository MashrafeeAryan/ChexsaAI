"""Check that one Chrome tree supplies both controls and ordinary page text."""

from copy import deepcopy
import unittest
from unittest.mock import Mock, call

import browser_
import observations_


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


    def test_reordering_existing_nodes_does_not_create_changes(self):
        before = browser_.read_page(self.page)
        self.nodes.reverse()
        after = browser_.read_page(self.page)
        changes = observations_.get_changes(before, after)
        self.assertFalse(changes["full"])
        for key in ("added", "updated", "removed", "added_text", "removed_text"):
            self.assertEqual(changes[key], [])

    def test_values_states_names_and_text_changes_are_detected(self):
        before = browser_.read_page(self.page)
        self.nodes[8]["name"]["value"] = "Send now"
        self.nodes[12]["value"]["value"] = "New subject"
        self.nodes[12]["properties"] = [{"name": "disabled", "value": {"value": True}}]
        self.nodes[3]["name"]["value"] = "Message sent"
        after = browser_.read_page(self.page)
        changes = observations_.get_changes(before, after)
        self.assertEqual(changes["updated"], [19, 113])
        self.assertEqual(changes["added_text"], ["Message sent"])
        self.assertEqual(changes["removed_text"], ["Inbox"])
        self.assertEqual(changes["added"], [])

    def test_replaced_same_name_button_is_removed_and_added(self):
        before = browser_.read_page(self.page)
        self.nodes[8]["backendDOMNodeId"] = 119
        after = browser_.read_page(self.page)
        changes = observations_.get_changes(before, after)
        self.assertEqual(changes["removed"], [19])
        self.assertEqual(changes["added"], [119])
        self.assertEqual(changes["updated"], [])

    def test_new_document_tab_or_url_resets_the_view(self):
        before = browser_.read_page(self.page)
        for key, value in (("document_id", 999), ("page_id", 999), ("url", "https://example.test/other")):
            after = dict(before, **{key: value})
            self.assertTrue(observations_.get_changes(before, after)["full"])

    def test_large_unchanged_page_is_not_resent_for_one_changed_control(self):
        self.nodes.extend({
            "nodeId": str(1000 + number), "parentId": "1", "backendDOMNodeId": 1000 + number,
            "role": {"value": "button"}, "name": {"value": f"Archive {number}"},
        } for number in range(1000))
        before = browser_.read_page(self.page)
        self.nodes[8]["properties"] = [{"name": "disabled", "value": {"value": True}}]
        after = browser_.read_page(self.page)
        view = observations_.page_context(after, before, "Handle the message", [])
        self.assertEqual(view["mode"], "changes")
        self.assertEqual(view["changes"]["updated_ids"], [19])
        self.assertIn('[19] button "Send"', view["elements"])
        self.assertNotIn("Archive 500", view["elements"])
        self.assertGreater(view["omitted_controls"], 900)
        self.assertLessEqual(len(view["elements"].splitlines()), 40)
        self.assertNotIn("New subject", str(view))

    def test_search_finds_omitted_controls_and_supports_continuation(self):
        self.nodes.extend({
            "nodeId": str(1000 + number), "backendDOMNodeId": 1000 + number,
            "role": {"value": "button"}, "name": {"value": f"Archive {number}"},
        } for number in range(70))
        observation = browser_.read_page(self.page)
        first = observations_.find_elements(observation, "ARCHIVE")
        second = observations_.find_elements(observation, "archive", first["next_offset"])
        self.assertEqual(first["total_matches"], 70)
        self.assertEqual(first["next_offset"], 40)
        self.assertIsNone(second["next_offset"])
        self.assertEqual(len(first["elements"].splitlines()), 40)
        self.assertEqual(len(second["elements"].splitlines()), 30)
        self.assertIn("Archive 69", second["elements"])

    def test_field_values_stay_local_while_value_changes_are_reported(self):
        before = browser_.read_page(self.page)
        self.nodes[12]["value"]["value"] = "SENSITIVE VALUE"
        after = browser_.read_page(self.page)
        view = observations_.page_context(after, before, "Fill Subject", [])
        self.assertIn(113, view["changes"]["updated_ids"])
        self.assertNotIn("SENSITIVE VALUE", str(view))
        self.assertEqual(after["controls"][113]["value"], "SENSITIVE VALUE")


    def test_dialog_controls_are_not_crowded_out_by_many_goal_word_matches(self):
        unrelated = [{
            "nodeId": str(1000 + number), "backendDOMNodeId": 1000 + number,
            "role": {"value": "button"}, "name": {"value": f"Archive {number}"},
        } for number in range(1000)]
        self.nodes = self.nodes[:1] + unrelated + self.nodes[1:]
        current = browser_.read_page(self.page)
        view = observations_.page_context(current, None, "Fill Subject, then Archive 999", [])
        self.assertIn('[113] textbox "Subject"', view["elements"])
        self.assertIn('[19] button "Send"', view["elements"])
        self.assertLessEqual(len(view["elements"].splitlines()), 40)


    def test_text_children_of_fields_do_not_copy_values_into_page_text(self):
        self.nodes.append({"nodeId": "99", "parentId": "13", "backendDOMNodeId": 999,
                           "role": {"value": "StaticText"}, "name": {"value": "SENSITIVE VALUE"}})
        observation = browser_.read_page(self.page)
        self.assertNotIn("SENSITIVE VALUE", observation["content"])
        self.assertNotIn("SENSITIVE VALUE", str(observation["text_nodes"]))
        self.assertIn("SENSITIVE VALUE", str(browser_._observations[self.page]["tree"]))


if __name__ == "__main__":
    unittest.main()
