import json
import unittest

from chexsa_browser.context import ContextView, changes
from chexsa_browser.models import BrowserError, Element, Observation
from chexsa_browser.regions import group_regions


def snapshot(count=500, generation="o1"):
    elements = [Element("t", "f", "d", i, "button", f"Message {i}", capabilities=("click",), ref=f"e{i}") for i in range(count)]
    result = Observation(generation, "p", "http://local", "Inbox", [], elements, {})
    result.regions = group_regions(elements)
    return result


class ContextTests(unittest.TestCase):
    def test_compact_controls_keep_real_values_and_boolean_states(self):
        from chexsa_browser.context import record
        element = snapshot(1).elements[0]
        element.value = "saved value"
        element.states = {"disabled": False, "readonly": False, "checked": False, "selected": True}
        data = record(element)
        self.assertEqual(data["value"], "saved value")
        self.assertEqual(data["state"], {"checked": False, "selected": True})
        self.assertNotIn("context", data)
        element.states["disabled"] = True
        self.assertTrue(record(element)["state"]["disabled"])

    def test_editable_fields_outside_focused_region_have_current_refs(self):
        from chexsa_browser.models import Region
        observation = snapshot(2)
        button, field = observation.elements
        field.role, field.name, field.capabilities = "searchbox", "Search", ("type",)
        button.region, field.region = "navigation", "search"
        observation.regions = [Region("navigation", "navigation", [button], ref="nav"), Region("search", "search", [field], ref="search")]
        data = json.loads(ContextView(3000).render(observation))
        self.assertEqual(data["field_index"][0]["ref"], field.ref)
        self.assertEqual(data["field_index"][0]["actions"], ["type"])
        self.assertLessEqual(len(observation.context), 3000)

    def test_large_page_is_bounded_and_every_control_can_be_paged(self):
        observation = snapshot()
        view = ContextView(3000)
        rendered = json.loads(view.render(observation))
        self.assertLessEqual(len(observation.context), 3000)
        self.assertGreater(rendered["controls"]["omitted"], 0)
        seen, cursor = [], None
        while True:
            page = view.inspect(observation, cursor=cursor)
            seen.extend(e["ref"] for e in page["elements"])
            cursor = page["next_cursor"]
            if cursor is None:
                break
        self.assertEqual(len(seen), 500)
        self.assertEqual(len(set(seen)), 500)

    def test_search_finds_a_control_beyond_the_initial_budget(self):
        observation = snapshot()
        found = ContextView().find(observation, "Message 499")
        self.assertEqual(found["elements"][0]["ref"], "e499")

    def test_huge_names_and_values_still_advance_the_cursor(self):
        observation = snapshot(2)
        for element in observation.elements:
            element.name = "long " * 1000
            element.value = "value " * 1000
            element.context = ("context " * 1000,)
        page = ContextView(2000).page(observation, observation.elements, budget=650)
        self.assertGreater(len(page["elements"]), 0)
        self.assertNotEqual(page["next_cursor"], "o1:0")

    def test_old_cursors_are_rejected(self):
        with self.assertRaises(BrowserError):
            ContextView().inspect(snapshot(generation="o2"), cursor="o1:20")

    def test_cursor_cannot_be_reused_for_a_different_query_or_section(self):
        observation, view = snapshot(), ContextView(3000)
        first = view.find(observation, "Message")
        self.assertIsNotNone(first["next_cursor"])
        with self.assertRaises(BrowserError):
            view.find(observation, "Message 499", first["next_cursor"])
        with self.assertRaises(BrowserError):
            view.tabs(observation, first["next_cursor"])
        controls = json.loads(view.render(observation))["controls"]
        with self.assertRaises(BrowserError):
            view.find(observation, "Message", controls["next_cursor"])
        expanded = view.inspect(observation, "page", controls["next_cursor"])
        self.assertTrue(expanded["elements"])
        self.assertNotEqual(expanded["elements"][0]["ref"], controls["elements"][0]["ref"])

    def test_ref_refresh_does_not_create_false_changes(self):
        first, second = snapshot(2), snapshot(2, "o2")
        second.elements[0].ref = "e100"
        self.assertEqual(changes(first, second), ["No visible changes."])
        second.elements.pop()
        self.assertIn("Removed:", changes(first, second)[0])

    def test_late_confirmation_text_survives_large_page(self):
        first, second = snapshot(), snapshot(generation="o2")
        second.text["status"] = {"text": "Message sent", "region_path": ()}
        second.changes = changes(first, second)
        self.assertIn("Message sent", ContextView(3000).render(second))

    def test_explicit_region_inspection_overrides_automatic_focus(self):
        observation = snapshot(2)
        from chexsa_browser.models import Region
        first, second = observation.elements
        observation.regions = [Region("dialog", "dialog", [first], 1000, "dialog-ref"), Region("inbox", "inbox", [second], 0, "inbox-ref")]
        view = ContextView()
        view.render(observation)
        view.inspect(observation, "inbox-ref")
        rendered = json.loads(view.render(observation))
        self.assertEqual(rendered["focused_region"], "inbox-ref")

    def test_tab_discovery_and_escaped_fields_stay_inside_budget(self):
        observation = snapshot(2)
        observation.tabs = [{"index": i, "page_id": str(i), "title": "title " * 100, "url": "http://local/" + "path/" * 100} for i in range(500)]
        view = ContextView(3000)
        discovery = view.tabs(observation)
        self.assertGreater(discovery["omitted"], 0)
        self.assertLessEqual(len(view.render(observation, discovery)), 3000)
        observation.elements[0].value = "\x00\n\\\"" * 10000
        field = view.inspect(observation, observation.elements[0].ref)
        self.assertLessEqual(len(view.render(observation, field)), 3000)
