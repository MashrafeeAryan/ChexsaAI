"""Check the new agent loop without opening Chrome or calling a model."""

from copy import deepcopy
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import DEFAULT, Mock, patch

import agent_
import llm_


class AgentLoopTests(unittest.TestCase):
    def setUp(self):
        replacements = patch.multiple(
            agent_, get_reply=DEFAULT, open_browser=DEFAULT, read_page=DEFAULT,
            click_node=DEFAULT, type_node=DEFAULT,
        )
        self.tools = replacements.start()
        self.addCleanup(replacements.stop)
        self.page = Mock()
        self.page.is_closed.return_value = False
        self.connection = Mock()
        self.tools["open_browser"].return_value = (self.connection, self.page)
        self.observation = {"url": "https://example.test", "title": "Form", "elements": '[12] textbox "Subject"'}
        self.tools["read_page"].return_value = self.observation

    def test_chat_does_not_open_chrome(self):
        "Checks that saying hello does not open Chrome."
        self.tools["get_reply"].return_value = {"action": "reply", "text": "Hello"}
        self.assertEqual(agent_.run_agent("Hi", {}), "Hello")
        self.tools["open_browser"].assert_not_called()
        self.tools["read_page"].assert_not_called()

    def test_original_request_history_and_fresh_observations_reach_each_decision(self):
        "Checks that the browser agent keeps your request and reads the page after each action."
        request = "Set the subject to Hello and click Continue"
        observations = [dict(self.observation, title=f"State {step}") for step in range(3)]
        self.tools["read_page"].side_effect = observations
        actions = iter([
            {"action": "observe"},
            {"action": "type", "backend_node_id": 12, "text": "Hello"},
            {"action": "click", "backend_node_id": 18},
            {"action": "reply", "text": "Finished"},
        ])
        decisions = []
        def choose(message, observation, history, previous=None):
            decisions.append((message, deepcopy(observation), deepcopy(history)))
            return next(actions)
        self.tools["get_reply"].side_effect = choose
        browser = {}
        self.assertEqual(agent_.run_agent(request, browser), "Finished")
        self.assertTrue(all(message == request for message, _, _ in decisions))
        self.assertEqual([item[1] for item in decisions], [None] + observations)
        self.assertEqual([len(item[2]) for item in decisions], [0, 1, 2, 3])
        self.assertIn("verified", decisions[-1][2][1]["result"])
        self.assertIn("Check the new observation", decisions[-1][2][2]["result"])
        self.tools["type_node"].assert_called_once_with(self.page, 12, "Hello")
        self.tools["click_node"].assert_called_once_with(self.page, 18)
        self.assertIs(browser["page"], self.page)

    def test_existing_tab_is_reused(self):
        "Checks that the agent reuses the open browser tab."
        self.tools["get_reply"].return_value = {"action": "reply", "text": "Need a subject"}
        result = agent_.run_agent("Fill the subject", {"playwright": self.connection, "page": self.page})
        self.assertEqual(result, "Need a subject")
        self.tools["read_page"].assert_called_once_with(self.page)
        self.tools["open_browser"].assert_not_called()

    def test_closed_tab_is_replaced_only_when_browser_is_requested(self):
        "Checks that a closed tab is replaced only when a browser task needs it."
        self.page.is_closed.return_value = True
        replacement = Mock()
        self.page.context.new_page.return_value = replacement
        self.tools["get_reply"].side_effect = [{"action": "observe"}, {"action": "reply", "text": "Ready"}]
        browser = {"playwright": self.connection, "page": self.page}
        self.assertEqual(agent_.run_agent("Look at Chrome", browser), "Ready")
        self.assertIs(browser["page"], replacement)
        self.tools["read_page"].assert_called_once_with(replacement)
        self.tools["open_browser"].assert_not_called()

    def test_model_calls_stop_at_ten(self):
        "Checks that a task stops after ten model calls instead of looping forever."
        self.tools["get_reply"].side_effect = [
            {"action": "navigate", "url": f"https://example.test/{step}"} for step in range(10)
        ]
        result = agent_.run_agent("Keep going", {})
        self.assertIn("10 model decisions", result)
        self.assertIn("unfinished", result)
        self.assertEqual(self.tools["get_reply"].call_count, 10)
        self.assertEqual(self.page.goto.call_count, 10)
        self.assertEqual(self.tools["read_page"].call_count, 10)

    def test_repeated_click_without_page_change_is_not_executed_twice(self):
        "Checks that the same click is not repeated when the page has not changed."
        self.tools["get_reply"].return_value = {"action": "click", "backend_node_id": 18}
        result = agent_.run_agent("Continue", {"playwright": self.connection, "page": self.page})
        self.assertIn("without a page change", result)
        self.tools["click_node"].assert_called_once()
        self.assertEqual(self.tools["get_reply"].call_count, 2)

    def test_same_control_can_be_clicked_again_after_page_progress(self):
        "Checks that clicking again is allowed when the page has made progress."
        self.tools["read_page"].side_effect = [dict(self.observation, title=str(step)) for step in range(3)]
        self.tools["get_reply"].side_effect = [
            {"action": "click", "backend_node_id": 18},
            {"action": "click", "backend_node_id": 18},
            {"action": "reply", "text": "Finished"},
        ]
        self.assertEqual(agent_.run_agent("Go through two pages", {"playwright": self.connection, "page": self.page}), "Finished")
        self.assertEqual(self.tools["click_node"].call_count, 2)

    def test_uncertain_click_stops_without_retry_or_another_model_call(self):
        "Checks that an uncertain click stops the task without clicking again."
        self.tools["get_reply"].side_effect = [{"action": "observe"}, {"action": "click", "backend_node_id": 18}]
        self.tools["click_node"].side_effect = RuntimeError("Click outcome is uncertain")
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            agent_.run_agent("Send", {})
        self.tools["click_node"].assert_called_once()
        self.assertEqual(self.tools["get_reply"].call_count, 2)
        self.assertEqual(self.tools["read_page"].call_count, 1)

    def test_failed_text_verification_stops_without_retry(self):
        "Checks that typing stops if the entered text cannot be confirmed."
        self.tools["get_reply"].return_value = {"action": "type", "backend_node_id": 12, "text": "Hello"}
        self.tools["type_node"].side_effect = RuntimeError("Text entry could not be verified")
        with self.assertRaisesRegex(RuntimeError, "verified"):
            agent_.run_agent("Set subject", {"playwright": self.connection, "page": self.page})
        self.assertEqual(self.tools["get_reply"].call_count, 1)
        self.tools["type_node"].assert_called_once()

    def test_keyboard_interrupt_is_not_swallowed_or_retried(self):
        "Checks that Ctrl+C cancels the browser task without retrying it."
        self.tools["get_reply"].side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            agent_.run_agent("Stop", {})
        self.assertEqual(self.tools["get_reply"].call_count, 1)

    def test_failed_observation_after_click_does_not_repeat_the_click(self):
        "Checks that a failed page reading does not cause a duplicate click."
        self.tools["read_page"].side_effect = [self.observation, RuntimeError("Tab closed")]
        self.tools["get_reply"].return_value = {"action": "click", "backend_node_id": 18}
        with self.assertRaisesRegex(RuntimeError, "Tab closed"):
            agent_.run_agent("Continue", {"playwright": self.connection, "page": self.page})
        self.tools["click_node"].assert_called_once()
        self.assertEqual(self.tools["get_reply"].call_count, 1)


    def test_previous_snapshot_is_passed_to_the_next_decision(self):
        "Checks that the previous page reading is available for finding changes."
        snapshots = [dict(self.observation, title=str(step)) for step in range(2)]
        self.tools["read_page"].side_effect = snapshots
        actions = iter([{"action": "observe"}, {"action": "type", "backend_node_id": 12, "text": "Hello"}, {"action": "reply", "text": "Finished"}])
        previous_readings = []
        def choose(message, observation, history, previous):
            previous_readings.append(deepcopy(previous))
            return next(actions)
        self.tools["get_reply"].side_effect = choose
        self.assertEqual(agent_.run_agent("Fill subject", {}), "Finished")
        self.assertEqual(previous_readings, [None, None, snapshots[0]])

    def test_local_search_does_not_click_or_type(self):
        "Checks that searching collected controls does not send clicks or text."
        self.tools["get_reply"].side_effect = [
            {"action": "find_elements", "query": "Send", "offset": 0},
            {"action": "reply", "text": "Found it"},
        ]
        self.assertEqual(agent_.run_agent("Find Send", {"playwright": self.connection, "page": self.page}), "Found it")
        self.tools["click_node"].assert_not_called()
        self.tools["type_node"].assert_not_called()
        self.assertEqual(self.tools["read_page"].call_count, 2)


class AgentModelPayloadTests(unittest.TestCase):
    def test_request_and_results_are_sent_without_duplicate_page_content(self):
        "Checks that the model gets the goal and results without repeated whole-page readings."
        environment = {"LLM_API_KEY": "fake-key", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "fake-model"}
        history = [{"action": {"action": "type", "backend_node_id": 12, "text": "Hello"}, "result": "Value verified"}]
        observation = {"url": "https://example.test", "title": "Form", "elements": '[12] textbox "Subject"', "content": "LOCAL ONLY"}
        with patch.dict(os.environ, environment, clear=True), patch.object(llm_, "_client", None), patch.object(llm_, "OpenAI") as client:
            client.return_value.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"reply","text":"Finished"}'))])
            llm_.get_reply("Original request", observation, history)
            messages = client.return_value.chat.completions.create.call_args.kwargs["messages"]
        payload = json.loads(messages[-1]["content"])
        self.assertEqual(payload["request"], "Original request")
        self.assertEqual(payload["previous_actions"], history)
        self.assertNotIn("content", payload["page"])
        self.assertNotIn("LOCAL ONLY", messages[-1]["content"])


    def test_unseen_target_is_rejected_until_local_search_exposes_it(self):
        "Checks that the model cannot click a control it has not been shown."
        observation = {
            "url": "https://example.test", "title": "Controls", "page_id": 1, "document_id": 1,
            "controls": {number: {"line": f'[{number}] button "Target {number}"', "role": "button", "name": f"Target {number}", "context": [], "value": "", "states": {}} for number in range(1, 101)},
            "text_nodes": {},
        }
        environment = {"LLM_API_KEY": "fake-key", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "fake-model"}
        with patch.dict(os.environ, environment, clear=True), patch.object(llm_, "_client", None), patch.object(llm_, "OpenAI") as client:
            client.return_value.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"click","backend_node_id":99}'))])
            with self.assertRaises(RuntimeError):
                llm_.get_reply("Continue", observation)
            history = [{"action": {"action": "find_elements", "query": "Target 99", "offset": 0}, "result": "Search requested"}]
            action = llm_.get_reply("Continue", observation, history, observation)
            self.assertEqual(action["backend_node_id"], 99)
            payload = json.loads(client.return_value.chat.completions.create.call_args.kwargs["messages"][-1]["content"])
            self.assertIn('[99] button "Target 99"', payload["page"]["search"]["elements"])
            self.assertNotIn("controls", payload["page"])

    def test_search_action_requires_valid_query_offset_and_observation(self):
        "Checks that page-search requests have valid details and a current page reading."
        observation = {"url": "https://example.test", "title": "Page", "elements": '[12] button "Send"'}
        environment = {"LLM_API_KEY": "fake-key", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "fake-model"}
        with patch.dict(os.environ, environment, clear=True), patch.object(llm_, "_client", None), patch.object(llm_, "OpenAI") as client:
            create = client.return_value.chat.completions.create
            for query, offset, valid in (("Send", 0, True), ("", 40, True), ("Send", -1, False), ("Send", True, False), (12, 0, False)):
                create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({"action": "find_elements", "query": query, "offset": offset})))])
                if valid:
                    self.assertEqual(llm_.get_reply("Find", observation)["action"], "find_elements")
                else:
                    with self.assertRaises(RuntimeError):
                        llm_.get_reply("Find", observation)
            create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"find_elements","query":"Send"}'))])
            with self.assertRaises(RuntimeError):
                llm_.get_reply("Find")


if __name__ == "__main__":
    unittest.main()
