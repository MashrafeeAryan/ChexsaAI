import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from chexsa_browser import structured
from chexsa_browser.model import BrowserModel
from chexsa_browser.models import BrowserError, Observation, TaskSpec, TaskState


class StructuredTests(unittest.TestCase):
    def model(self, payload, endpoint="https://api.groq.com/openai/v1/"):
        client = MagicMock()
        client.base_url = endpoint
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))], usage=None)
        return BrowserModel(SimpleNamespace(provider="openai_compatible", model="openai/gpt-oss-20b", client=client))

    def test_strict_plan_retains_arbitrary_flat_inputs_and_rejects_duplicate_keys(self):
        payload = {"inputs": [{"name": "query", "value": "jazz"}], "subgoals": ["Search"], "completion": ["Results"], "intent": "act"}
        model = self.model(payload)
        observation = Observation("o", "p", "url", "title", [], [], {}, context="{}")
        self.assertEqual(model.plan("Search jazz", observation).inputs, {"query": "jazz"})
        options = model.llm.client.chat.completions.create.call_args.kwargs
        self.assertTrue(options["response_format"]["json_schema"]["strict"])
        payload["inputs"].append({"name": "query", "value": "other"})
        with self.assertRaises(BrowserError):
            self.model(payload).plan("Search jazz", observation)

    def test_strict_schema_does_not_bypass_action_validation(self):
        model = self.model({"action": "click", "arguments": {"ref": "e1", "text": "wrong", "url": None}, "effect": {"kind": None}})
        with self.assertRaises(BrowserError):
            model.choose(TaskState("t", TaskSpec("Click")), Observation("o", "p", "url", "title", [], [], {}, context="{}"))

    def test_valid_error_payload_can_omit_only_nullable_fields(self):
        import httpx
        from openai import BadRequestError
        from unittest.mock import Mock
        payload = {"action": "type", "arguments": {"ref": "e1", "text": "hello", "press_enter": False}, "effect": {"kind": "value"}}
        error = BadRequestError("Rejected nullable fields", response=httpx.Response(400, request=httpx.Request("POST", "https://api.groq.com")), body={"code": "json_validate_failed", "failed_generation": json.dumps(payload)})
        model = self.model({})
        model._ask_once = Mock(side_effect=error)
        schema = structured.obj({"action": {"type": "string", "enum": ["type"]}, "arguments": structured.obj({"ref": structured.STRING, "text": structured.STRING, "press_enter": {"type": ["boolean", "null"]}}), "effect": structured.obj({"kind": structured.STRING, "text": {"type": ["string", "null"]}})})
        self.assertEqual(model._ask("Choose", b"", schema), payload)
        model._ask_once.assert_called_once()
        for invalid in ({**payload, "action": "delete_everything"}, {**payload, "arguments": None}, {**payload, "arguments": {"selector": "button"}}, {"action": "type", "arguments": {}}):
            self.assertFalse(structured.conforms(invalid, schema))
        self.assertFalse(structured.conforms({"ready": True}, structured.PREFLIGHT))

    def test_nulls_are_omitted_but_false_zero_and_empty_are_preserved(self):
        self.assertEqual(structured.without_nulls({"a": None, "b": False, "c": 0, "d": "", "e": [{"ref": "e1", "text": None}]}), {"b": False, "c": 0, "d": "", "e": [{"ref": "e1"}]})

    def test_unrecognized_endpoint_uses_existing_json_mode(self):
        model = self.model({"ok": True}, "https://other.example.test/v1")
        model._structured_ask("JSON", b"", structured.PLAN)
        self.assertEqual(model.llm.client.chat.completions.create.call_args.kwargs["response_format"], {"type": "json_object"})

    def test_every_strict_object_is_closed_and_every_property_required(self):
        def visit(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertIs(node["additionalProperties"], False)
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)
        for schema in (structured.PLAN, structured.PREFLIGHT, structured.VERIFY):
            visit(schema)
