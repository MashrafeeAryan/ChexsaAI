import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from chexsa_browser.model import BrowserModel, parse_object
from chexsa_browser.models import BrowserError, Observation, TaskSpec, TaskState


class ModelTests(unittest.TestCase):
    def test_missing_subject_gets_neutral_default_unless_explicitly_empty(self):
        model = BrowserModel(None)
        observation = Observation("o1", "p", "url", "title", [], [], {}, context="page")
        model._ask = lambda *args: {"inputs": {"recipient": "fixture@example.test", "body": "Hello", "subject": ""}, "subgoals": ["Send"], "completion": ["Sent"]}
        self.assertEqual(model.plan("Send hello to fixture@example.test", observation).inputs["subject"], "Hello")
        self.assertEqual(model.plan("Send hello to fixture@example.test without a subject", observation).inputs["subject"], "")

    def setUp(self):
        self.model = BrowserModel(None)
        self.observation = Observation("o1", "p", "url", "title", [], [], {}, context="page")

    def test_plan_preserves_the_users_literal_address(self):
        self.model._ask = lambda *args: {"inputs": {"recipient": "hallucinated@example.test"}, "subgoals": ["compose"], "completion": ["sent"], "intent": "act"}
        spec = self.model.plan("send hello to intended@example.test", self.observation)
        self.assertEqual(spec.inputs["recipient"], "intended@example.test")

    def test_invalid_action_and_malformed_plan_are_rejected(self):
        self.model._ask = lambda *args: {"action": "click", "arguments": {"selector": "button"}}
        with self.assertRaises(BrowserError):
            self.model.choose(TaskState("t", TaskSpec("goal")), self.observation)
        self.model._ask = lambda *args: {"subgoals": "not a list"}
        with self.assertRaises(BrowserError):
            self.model.plan("goal", self.observation)

    def test_non_object_json_is_rejected(self):
        for text in ('[]', 'null', '```json {} ```'):
            with self.assertRaises(BrowserError):
                parse_object(text)

    def test_incomplete_email_plan_cannot_bypass_preflight(self):
        self.model._ask = lambda *args: {"inputs": {}, "subgoals": ["compose"], "completion": ["draft exists"], "intent": "act"}
        spec = self.model.plan("draft an email to intended@example.test", self.observation)
        self.assertEqual(spec.intent, "draft")
        self.assertEqual(spec.inputs["recipient"], "intended@example.test")
        self.assertIn("body", spec.inputs)

    def test_provider_adapters_preserve_json_images_and_usage(self):
        for provider in ("gemini", "openai_compatible"):
            with self.subTest(provider=provider):
                client = MagicMock()
                model = BrowserModel(SimpleNamespace(provider=provider, model="configured-model", client=client, supports_vision=True))
                if provider == "gemini":
                    client.models.generate_content.return_value = SimpleNamespace(text='{"result":"ok"}', usage_metadata=SimpleNamespace(prompt_token_count=12, candidates_token_count=3))
                else:
                    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"result":"ok"}'))], usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3))
                self.assertEqual(model._ask("Return JSON", b"image bytes"), {"result": "ok"})
                self.assertEqual(model.usage, {"calls": 1, "input_tokens": 12, "output_tokens": 3})
                if provider == "gemini":
                    arguments = client.models.generate_content.call_args.kwargs
                    self.assertEqual(arguments["contents"][1].inline_data.mime_type, "image/png")
                else:
                    arguments = client.chat.completions.create.call_args.kwargs
                    self.assertTrue(arguments["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_text_only_provider_receives_string_content(self):
        client = MagicMock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))], usage=None)
        model = BrowserModel(SimpleNamespace(provider="openai_compatible", model="text-model", client=client, supports_vision=False))
        self.assertEqual(model._ask("Return JSON"), {"ok": True})
        self.assertEqual(client.chat.completions.create.call_args.kwargs["messages"][0]["content"], "Return JSON")
        with self.assertRaises(BrowserError):
            model._ask("Return JSON", b"image bytes")
        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_text_only_model_cannot_choose_visual_actions(self):
        from unittest.mock import Mock
        self.observation.screenshot = b"image bytes"
        state = TaskState("t", TaskSpec("Open a website"))
        for action in ("capture_screenshot", "click_coordinates", "type_focused"):
            self.model._ask = Mock(return_value={"action": action, "arguments": {}})
            with self.assertRaises(BrowserError):
                self.model.choose(state, self.observation)
            prompt, image = self.model._ask.call_args.args
            self.assertEqual(image, b"")
            import json
            actions = json.loads(prompt.split("ACTIONS:\n", 1)[1].split("\nTASK:", 1)[0])
            self.assertNotIn(action, actions)

    def test_text_only_verification_does_not_send_images(self):
        from unittest.mock import Mock
        self.observation.screenshot = b"image bytes"
        self.model._ask = Mock(return_value={"complete": False, "evidence": []})
        self.model.verify(TaskState("t", TaskSpec("goal")), None, self.observation)
        self.assertEqual(self.model._ask.call_args.args[1], b"")

    def test_invalid_provider_json_is_retried_once_without_browser_actions(self):
        from unittest.mock import Mock
        self.model._ask_once = Mock(side_effect=[BrowserError("invalid_model_output", "Bad JSON"), {"ok": True}])
        self.assertEqual(self.model._ask("Return JSON"), {"ok": True})
        self.assertEqual(self.model._ask_once.call_count, 2)
        self.model._ask_once = Mock(side_effect=BrowserError("invalid_model_output", "Bad JSON"))
        with self.assertRaises(BrowserError):
            self.model._ask("Return JSON")
        self.assertEqual(self.model._ask_once.call_count, 2)

    def test_short_rate_limit_wait_is_bounded_and_announced(self):
        import httpx
        from openai import RateLimitError
        from unittest.mock import Mock, patch
        error = RateLimitError("Limited", response=httpx.Response(429, headers={"retry-after": "2"}, request=httpx.Request("POST", "https://provider.example.test")), body=None)
        self.model._ask_once = Mock(side_effect=[error, {"ok": True}])
        with patch("chexsa_browser.model.time.sleep") as sleep, patch("builtins.print") as announce:
            self.assertEqual(self.model._ask("Return JSON"), {"ok": True})
            sleep.assert_called_once_with(3.1)
            announce.assert_called_once()
        self.model._ask_once = Mock(side_effect=error)
        with patch("chexsa_browser.model.time.sleep") as sleep, patch("builtins.print"):
            with self.assertRaises(BrowserError) as caught:
                self.model._ask("Return JSON")
            self.assertEqual(caught.exception.code, "rate_limited")
            self.assertEqual(sleep.call_count, 2)

    def test_json_and_quota_recovery_have_independent_budgets(self):
        import httpx
        from openai import RateLimitError
        from unittest.mock import Mock, patch
        limited = RateLimitError("Limited", response=httpx.Response(429, headers={"retry-after": "1"}, request=httpx.Request("POST", "https://provider.example.test")), body=None)
        self.model._ask_once = Mock(side_effect=[BrowserError("invalid_model_output", "Bad JSON"), limited, {"ok": True}])
        with patch("chexsa_browser.model.time.sleep"), patch("builtins.print"):
            self.assertEqual(self.model._ask("Return JSON"), {"ok": True})
        self.assertEqual(self.model._ask_once.call_count, 3)

    def test_planning_uses_overview_instead_of_all_controls(self):
        import json
        from unittest.mock import Mock
        self.observation.context = json.dumps({"url": "https://example.test", "title": "Example", "controls": {"elements": ["large control list"]}})
        self.model._ask = Mock(return_value={"inputs": {}, "subgoals": ["Open website"], "completion": ["Website visible"]})
        self.model.plan("Open website", self.observation)
        self.assertNotIn("large control list", self.model._ask.call_args.args[0])

    def test_rejected_batch_requires_individual_action_on_recovery(self):
        from unittest.mock import Mock
        import json
        state = TaskState("t", TaskSpec("Fill a form"))
        state.history.append({"action": "recovery", "code": "unsafe_batch", "message": "Action cannot be batched: click"})
        self.model._ask = Mock(return_value={"action": "type", "arguments": {"ref": "e1", "text": "Hello"}})
        self.assertEqual(self.model.choose(state, self.observation).action, "type")
        prompt = self.model._ask.call_args.args[0]
        actions = json.loads(prompt.split("ACTIONS:\n", 1)[1].split("\nTASK:", 1)[0])
        self.assertNotIn("batch", actions)
        self.model._ask.return_value = {"action": "batch", "arguments": {"actions": [{"action": "type", "arguments": {"ref": "e1", "text": "Hello"}}]}}
        with self.assertRaises(BrowserError):
            self.model.choose(state, self.observation)

    def test_malformed_batch_also_disables_batch_on_recovery(self):
        from unittest.mock import Mock
        self.model._ask = Mock(return_value={"action": "batch", "arguments": {"actions": [{"ref": "e1", "text": "Hello"}]}})
        with self.assertRaises(BrowserError) as caught:
            self.model.choose(TaskState("t", TaskSpec("Fill form")), self.observation)
        self.assertEqual(caught.exception.code, "unsafe_batch")
