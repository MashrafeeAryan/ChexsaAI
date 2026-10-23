import unittest

from chexsa_browser.collector import capabilities, parse_document


class CollectorTests(unittest.TestCase):
    def test_live_status_text_is_distinct_from_ordinary_message_text(self):
        strings = ["P", "#text"]
        doc = {"nodes": {"backendNodeId": [1, 2, 3], "nodeName": [0, 1, 1], "attributes": [[], [], []]}}
        ax = [{"nodeId": "status", "backendDOMNodeId": 1, "role": {"value": "status"}}, {"nodeId": "receipt", "parentId": "status", "backendDOMNodeId": 2, "role": {"value": "StaticText"}, "name": {"value": "Message sent"}}, {"nodeId": "body", "backendDOMNodeId": 3, "role": {"value": "StaticText"}, "name": {"value": "Message sent"}}]
        _, text = parse_document("t", "f", "d", doc, strings, ax)
        self.assertTrue(text["t/f/d/2"]["live"])
        self.assertFalse(text["t/f/d/3"]["live"])

    def test_capabilities_do_not_make_headings_clickable(self):
        self.assertEqual(capabilities("heading", "H1", {}, {}), ())
        self.assertIn("type", capabilities("textbox", "DIV", {"contenteditable": "true"}, {}))
        self.assertIn("upload_file", capabilities("", "INPUT", {"type": "file"}, {}))

    def test_names_states_and_duplicate_identity_are_preserved(self):
        strings = ["BUTTON", "INPUT", "type", "password", "secret"]
        doc = {"nodes": {"backendNodeId": [11, 12, 13], "nodeName": [0, 0, 1], "attributes": [[], [], [2, 3]], "inputValue": {"index": [2], "value": [4]}}, "layout": {"nodeIndex": [0, 1, 2], "bounds": [[0, 0, 10, 10]] * 3}}
        ax = [{"nodeId": str(i), "backendDOMNodeId": i, "role": {"value": role}, "name": {"value": name}, "properties": [{"name": "disabled", "value": {"value": i == 12}}]} for i, role, name in ((11, "button", 'Save "draft": C:\\notes'), (12, "button", 'Save "draft": C:\\notes'), (13, "textbox", "Password"))]
        elements, _ = parse_document("tab", "frame", "doc", doc, strings, ax)
        self.assertEqual(len(elements), 3)
        self.assertNotEqual(elements[0].identity, elements[1].identity)
        self.assertEqual(elements[0].name, 'Save "draft": C:\\notes')
        self.assertTrue(elements[1].states["disabled"])
        self.assertEqual(elements[2].value, "[redacted]")
