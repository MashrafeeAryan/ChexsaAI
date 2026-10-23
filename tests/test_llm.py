"""Keep provider settings and desktop decisions working after browser cleanup."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from chexsa_browser.model import BrowserModel
from llm import LLM


class LLMTests(unittest.TestCase):
    def test_per_run_model_does_not_change_saved_setting(self):
        settings = {"LLM_PROVIDER": "openai_compatible", "LLM_MODEL": "saved-model", "LLM_API_KEY": "fixture-key", "LLM_BASE_URL": "https://provider.example.test/v1"}
        with patch.dict("os.environ", settings, clear=True), patch("llm.OpenAI"):
            self.assertEqual(LLM(model="temporary-model").model, "temporary-model")
            self.assertEqual(LLM().model, "saved-model")
    def test_compatible_models_default_to_text_only_and_can_opt_into_vision(self):
        settings = {"LLM_PROVIDER": "openai_compatible", "LLM_API_KEY": "fixture-key", "LLM_BASE_URL": "https://provider.example.test/v1"}
        with patch.dict("os.environ", settings, clear=True), patch("llm.OpenAI"):
            self.assertFalse(LLM().supports_vision)
            with patch.dict("os.environ", {"LLM_SUPPORTS_VISION": "1"}):
                self.assertTrue(LLM().supports_vision)

    def test_chat_is_routed_and_answered_without_browser_tools(self):
        for provider in ("gemini", "openai_compatible"):
            with self.subTest(provider=provider):
                llm = LLM.__new__(LLM)
                llm.provider, llm.model, llm.client = provider, "saved-model", MagicMock()
                if provider == "gemini":
                    llm.client.models.generate_content.side_effect = [SimpleNamespace(text="chat"), SimpleNamespace(text="Hello")]
                else:
                    llm.client.chat.completions.create.side_effect = [SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))]) for text in ("chat", "Hello")]
                self.assertEqual(llm.choose_mode("Hi"), "chat")
                self.assertEqual(llm.reply("Hi"), "Hello")

    def test_invalid_routing_response_is_not_a_browser_request(self):
        llm = LLM.__new__(LLM)
        llm.provider, llm.model, llm.client = "gemini", "saved-model", MagicMock()
        llm.client.models.generate_content.return_value = SimpleNamespace(text="not a mode")
        with self.assertRaises(RuntimeError):
            llm.choose_mode("Hi")

    def test_saved_provider_settings_reach_browser_model(self):
        for provider in ("gemini", "openai_compatible"):
            with self.subTest(provider=provider):
                settings = {"LLM_PROVIDER": provider, "LLM_MODEL": "saved-model"}
                client = MagicMock()
                if provider == "gemini":
                    settings["GEMINI_API_KEY"] = "fixture-key"
                    constructor = "llm.genai.Client"
                    expected = {"api_key": "fixture-key"}
                    client.models.generate_content.return_value = SimpleNamespace(text='{"ok":true}', usage_metadata=None)
                else:
                    settings.update(LLM_API_KEY="fixture-key", LLM_BASE_URL="https://provider.example.test/v1")
                    constructor = "llm.OpenAI"
                    expected = {"api_key": "fixture-key", "base_url": settings["LLM_BASE_URL"], "timeout": 30, "max_retries": 0}
                    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))], usage=None)
                with patch.dict("os.environ", settings, clear=True), patch(constructor, return_value=client) as build:
                    llm = LLM()
                    build.assert_called_once_with(**expected)
                    self.assertEqual(BrowserModel(llm)._ask("Return JSON"), {"ok": True})
                send = client.models.generate_content if provider == "gemini" else client.chat.completions.create
                self.assertEqual(send.call_args.kwargs["model"], "saved-model")

    def test_voice_routing_and_desktop_decisions_keep_using_shared_client(self):
        for provider in ("gemini", "openai_compatible"):
            with self.subTest(provider=provider):
                llm = LLM.__new__(LLM)
                llm.provider, llm.model, llm.client = provider, "saved-model", MagicMock()
                payload = {"action": "type_text", "arguments": {"control_type": "Edit", "text": "Hello"}, "done": False, "response": ""}
                if provider == "gemini":
                    llm.client.models.generate_content.return_value = SimpleNamespace(text="desktop")
                    llm.client.interactions.create.return_value = SimpleNamespace(output_text=json.dumps(payload))
                    send = llm.client.interactions.create
                else:
                    llm.client.chat.completions.create.side_effect = [
                        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="desktop"))]),
                        SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]),
                    ]
                    send = llm.client.chat.completions.create
                self.assertEqual(llm.choose_mode("Write Hello in Word"), "desktop")
                state = SimpleNamespace(active_window="Word", windows=["Word"], controls=['Edit "Document"'])
                decision = llm.decide_desktop("Write Hello in Word", state, [])
                self.assertEqual(decision.action, "type_text")
                self.assertEqual(decision.arguments, payload["arguments"])
                arguments = send.call_args.kwargs
                self.assertEqual(arguments["model"], "saved-model")
                prompt = arguments["input"] if provider == "gemini" else arguments["messages"][0]["content"]
                self.assertIn("Write Hello in Word", prompt)
                self.assertIn('Edit', prompt)
