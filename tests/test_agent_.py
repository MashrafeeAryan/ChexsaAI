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
            agent_,
            get_reply=DEFAULT,
            open_browser=DEFAULT,
            read_page=DEFAULT,
            click_node=DEFAULT,
            type_node=DEFAULT,
            run_action_group=DEFAULT,
            wait_for_page=DEFAULT,
        )
        self.tools = replacements.start()
        self.addCleanup(replacements.stop)
        self.page = Mock()
        self.page.is_closed.return_value = False
        self.connection = Mock()
        self.tools["open_browser"].return_value = (self.connection, self.page)
        self.observation = {
            "url": "https://example.test",
            "title": "Form",
            "elements": '[12] textbox "Subject"',
        }
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
        observations = [
            dict(self.observation, title=f"State {step}") for step in range(3)
        ]
        self.tools["read_page"].side_effect = observations
        actions = iter(
            [
                {"action": "observe"},
                {"action": "type", "backend_node_id": 12, "text": "Hello"},
                {"action": "click", "backend_node_id": 18},
                {"action": "reply", "text": "Finished"},
            ]
        )
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
        self.tools["get_reply"].return_value = {
            "action": "reply",
            "text": "Need a subject",
        }
        result = agent_.run_agent(
            "Fill the subject", {"playwright": self.connection, "page": self.page}
        )
        self.assertEqual(result, "Need a subject")
        self.tools["read_page"].assert_called_once_with(self.page)
        self.tools["open_browser"].assert_not_called()

    def test_closed_tab_is_replaced_only_when_browser_is_requested(self):
        "Checks that a closed tab is replaced only when a browser task needs it."
        self.page.is_closed.return_value = True
        replacement = Mock()
        self.page.context.new_page.return_value = replacement
        self.tools["get_reply"].side_effect = [
            {"action": "observe"},
            {"action": "reply", "text": "Ready"},
        ]
        browser = {"playwright": self.connection, "page": self.page}
        self.assertEqual(agent_.run_agent("Look at Chrome", browser), "Ready")
        self.assertIs(browser["page"], replacement)
        self.tools["read_page"].assert_called_once_with(replacement)
        self.tools["open_browser"].assert_not_called()

    def test_model_calls_stop_at_ten(self):
        "Checks that a task stops after ten model calls instead of looping forever."
        self.tools["get_reply"].side_effect = [
            {"action": "navigate", "url": f"https://example.test/{step}"}
            for step in range(10)
        ]
        result = agent_.run_agent("Keep going", {})
        self.assertIn("10 model decisions", result)
        self.assertIn("unfinished", result)
        self.assertEqual(self.tools["get_reply"].call_count, 10)
        self.assertEqual(self.page.goto.call_count, 10)
        self.assertEqual(self.tools["read_page"].call_count, 10)

    def test_repeated_click_without_page_change_is_not_executed_twice(self):
        "Checks that the same click is not repeated when the page has not changed."
        self.tools["get_reply"].return_value = {
            "action": "click",
            "backend_node_id": 18,
        }
        browser = {"playwright": self.connection, "page": self.page}
        result = agent_.run_agent("Continue", browser)
        self.assertTrue(browser["_browser_task"]["review_only"])
        self.assertIn("no new input", agent_.run_agent("/continue", browser))
        self.assertIn("without a page change", result)
        self.tools["click_node"].assert_called_once()
        self.assertEqual(self.tools["get_reply"].call_count, 3)

    def test_same_control_can_be_clicked_again_after_page_progress(self):
        "Checks that clicking again is allowed when the page has made progress."
        self.tools["read_page"].side_effect = [
            dict(self.observation, title=str(step)) for step in range(3)
        ]
        self.tools["get_reply"].side_effect = [
            {"action": "click", "backend_node_id": 18},
            {"action": "click", "backend_node_id": 18},
            {"action": "reply", "text": "Finished"},
        ]
        self.assertEqual(
            agent_.run_agent(
                "Go through two pages",
                {"playwright": self.connection, "page": self.page},
            ),
            "Finished",
        )
        self.assertEqual(self.tools["click_node"].call_count, 2)

    def test_uncertain_click_stops_without_retry_or_another_model_call(self):
        "Checks that an uncertain click stops the task without clicking again."
        self.tools["get_reply"].side_effect = [
            {"action": "observe"},
            {"action": "click", "backend_node_id": 18},
        ]
        self.tools["click_node"].side_effect = RuntimeError(
            "Click outcome is uncertain"
        )
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            agent_.run_agent("Send", {})
        self.tools["click_node"].assert_called_once()
        self.assertEqual(self.tools["get_reply"].call_count, 2)
        self.assertEqual(self.tools["read_page"].call_count, 1)

    def test_failed_text_verification_stops_without_retry(self):
        "Checks that typing stops if the entered text cannot be confirmed."
        self.tools["get_reply"].return_value = {
            "action": "type",
            "backend_node_id": 12,
            "text": "Hello",
        }
        self.tools["type_node"].side_effect = RuntimeError(
            "Text entry could not be verified"
        )
        with self.assertRaisesRegex(RuntimeError, "verified"):
            agent_.run_agent(
                "Set subject", {"playwright": self.connection, "page": self.page}
            )
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
        self.tools["read_page"].side_effect = [
            self.observation,
            RuntimeError("Tab closed"),
        ]
        self.tools["get_reply"].return_value = {
            "action": "click",
            "backend_node_id": 18,
        }
        with self.assertRaisesRegex(RuntimeError, "Tab closed"):
            agent_.run_agent(
                "Continue", {"playwright": self.connection, "page": self.page}
            )
        self.tools["click_node"].assert_called_once()
        self.assertEqual(self.tools["get_reply"].call_count, 1)

    def test_previous_snapshot_is_passed_to_the_next_decision(self):
        "Checks that the previous page reading is available for finding changes."
        snapshots = [dict(self.observation, title=str(step)) for step in range(2)]
        self.tools["read_page"].side_effect = snapshots
        actions = iter(
            [
                {"action": "observe"},
                {"action": "type", "backend_node_id": 12, "text": "Hello"},
                {"action": "reply", "text": "Finished"},
            ]
        )
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
        self.assertEqual(
            agent_.run_agent(
                "Find Send", {"playwright": self.connection, "page": self.page}
            ),
            "Found it",
        )
        self.tools["click_node"].assert_not_called()
        self.tools["type_node"].assert_not_called()
        self.assertEqual(self.tools["read_page"].call_count, 2)

    def test_group_uses_one_decision_and_returns_partial_progress(self):
        """A stopped group supplies exact progress and a fresh page for replanning."""
        actions = [
            {"action": "type", "backend_node_id": 12, "text": "Hello"},
            {"action": "click", "backend_node_id": 18},
        ]
        after = dict(self.observation, title="Changed")
        self.tools["get_reply"].side_effect = [
            {"action": "batch", "actions": actions},
            {"action": "reply", "text": "Need another choice"},
        ]
        self.tools["run_action_group"].return_value = {
            "completed": actions[:1],
            "remaining": 1,
            "stopped": "Control changed",
            "error": None,
            "observation": after,
        }
        result = agent_.run_agent(
            "Fill and continue", {"playwright": self.connection, "page": self.page}
        )
        self.assertEqual(result, "Need another choice")
        self.assertEqual(self.tools["read_page"].call_count, 1)
        next_call = self.tools["get_reply"].call_args.args
        self.assertEqual(next_call[1], after)
        self.assertEqual(next_call[2][-1]["result"]["completed"], 1)
        self.assertEqual(next_call[2][-1]["result"]["remaining"], 1)

    def test_uncertain_group_stops_without_another_model_call(self):
        """Partial progress cannot cause an uncertain final click to be repeated."""
        actions = [{"action": "click", "backend_node_id": 18}]
        self.tools["get_reply"].return_value = {"action": "batch", "actions": actions}
        self.tools["run_action_group"].return_value = {
            "completed": [],
            "remaining": 1,
            "stopped": "Uncertain",
            "error": "Click outcome uncertain",
            "observation": self.observation,
        }
        with self.assertRaisesRegex(RuntimeError, "uncertain"):
            agent_.run_agent(
                "Continue", {"playwright": self.connection, "page": self.page}
            )
        self.assertEqual(self.tools["get_reply"].call_count, 1)
        self.assertEqual(self.tools["run_action_group"].call_count, 1)

    def test_wait_returns_its_last_reading_without_a_duplicate_capture(self):
        """Polling stays inside the tool; the next model decision gets its final reading."""
        after = dict(self.observation, title="Ready")
        self.tools["get_reply"].side_effect = [
            {"action": "wait_for", "text": "Ready"},
            {"action": "reply", "text": "Ready now"},
        ]
        self.tools["wait_for_page"].return_value = {
            "matched": True,
            "reason": None,
            "observation": after,
        }
        self.assertEqual(
            agent_.run_agent(
                "Wait for Ready", {"playwright": self.connection, "page": self.page}
            ),
            "Ready now",
        )
        self.assertEqual(self.tools["read_page"].call_count, 1)
        self.assertEqual(self.tools["get_reply"].call_args.args[1], after)

    def test_continue_keeps_partial_progress_but_reads_new_targets(self):
        """Stop keeps the request and result; continuation gets a fresh node ID."""
        actions = [
            {"action": "type", "backend_node_id": 12, "text": "Hello"},
            {"action": "click", "backend_node_id": 18},
        ]
        browser = {"playwright": self.connection, "page": self.page}
        self.tools["get_reply"].return_value = {"action": "batch", "actions": actions}

        def interrupted(page, planned, observation, cancel, remember):
            """Simulate Stop after one verified field, without sending the click."""
            remember(
                {
                    "completed": actions[:1],
                    "remaining": 1,
                    "stopped": None,
                    "attempting": None,
                }
            )
            raise InterruptedError("Stop")

        self.tools["run_action_group"].side_effect = interrupted
        with self.assertRaises(InterruptedError):
            agent_.run_agent("Fill and save Hello", browser)
        self.assertEqual(browser["_browser_task"]["status"], "paused")
        self.assertEqual(
            browser["_browser_task"]["history"][0]["result"]["completed"], 1
        )
        fresh = dict(self.observation, elements='[42] button "Continue"')
        self.tools["read_page"].return_value = fresh
        self.tools["get_reply"].side_effect = [
            {"action": "click", "backend_node_id": 42},
            {"action": "reply", "text": "Finished"},
        ]
        self.assertEqual(agent_.run_agent("continue", browser), "Finished")
        decision = self.tools["get_reply"].call_args_list[-2].args
        self.assertEqual(decision[0], "Fill and save Hello")
        self.assertIs(decision[1], fresh)
        self.assertIs(
            decision[3], self.observation
        )  # Comparison only, not executable targets.
        self.tools["type_node"].assert_not_called()
        self.tools["click_node"].assert_called_once_with(self.page, 42)
        self.assertEqual(browser["_browser_task"]["status"], "finished")

    def test_new_request_does_not_inherit_old_progress(self):
        """A different request starts clean; continuation needs an unfinished task."""
        browser = {}
        self.assertIn("No unfinished", agent_.run_agent("/resume", browser))
        self.tools["get_reply"].assert_not_called()
        self.tools["get_reply"].return_value = {"action": "reply", "text": "Hello"}
        agent_.run_agent("Hi", browser)
        old = browser["_browser_task"]
        self.assertIn("No unfinished", agent_.run_agent("/continue", browser))
        agent_.run_agent("Another question", browser)
        self.assertIsNot(browser["_browser_task"], old)
        self.assertEqual(self.tools["get_reply"].call_args.args[2], [])

    def test_api_failure_keeps_verified_progress_for_continue(self):
        """An API error cannot erase fields already verified locally."""
        browser = {"playwright": self.connection, "page": self.page}
        self.tools["get_reply"].side_effect = [
            {"action": "type", "backend_node_id": 12, "text": "Hello"},
            RuntimeError("API unavailable"),
        ]
        with self.assertRaisesRegex(RuntimeError, "API unavailable"):
            agent_.run_agent("Fill subject", browser)
        self.assertEqual(len(browser["_browser_task"]["history"]), 1)
        self.assertIsNone(browser["_browser_task"]["in_flight"])
        self.tools["get_reply"].side_effect = [{"action": "reply", "text": "Verified"}]
        self.assertEqual(agent_.run_agent("resume", browser), "Verified")
        self.tools["type_node"].assert_called_once()

    def test_uncertain_resume_allows_inspection_but_rejects_new_input(self):
        """Even a model that asks to click again cannot repeat uncertain input."""
        browser = {"playwright": self.connection, "page": self.page}
        self.tools["get_reply"].return_value = {
            "action": "click",
            "backend_node_id": 18,
        }
        self.tools["click_node"].side_effect = RuntimeError("Uncertain click")
        with self.assertRaisesRegex(RuntimeError, "Uncertain"):
            agent_.run_agent("Save once", browser)
        self.assertTrue(browser["_browser_task"]["review_only"])
        calls = self.tools["get_reply"].call_count
        self.assertIn("/continue", agent_.run_agent("Save once", browser))
        self.assertEqual(self.tools["get_reply"].call_count, calls)
        self.tools["get_reply"].side_effect = [
            {"action": "wait_for", "text": "Saved"},
            {"action": "click", "backend_node_id": 18},
        ]
        self.tools["wait_for_page"].return_value = {
            "matched": False,
            "reason": "Timeout",
            "observation": self.observation,
        }
        self.assertIn("no new input", agent_.run_agent("/continue", browser))
        self.tools["click_node"].assert_called_once()
        self.tools["wait_for_page"].assert_called_once()
        self.assertEqual(self.tools["read_page"].call_count, 2)

    def test_cancelled_read_after_sent_click_keeps_inspection_only(self):
        """A successful input call is not evidence that submission failed."""
        browser = {"playwright": self.connection, "page": self.page}
        self.tools["get_reply"].return_value = {
            "action": "click",
            "backend_node_id": 18,
        }
        self.tools["read_page"].side_effect = [self.observation, KeyboardInterrupt()]
        with self.assertRaises(KeyboardInterrupt):
            agent_.run_agent("Save", browser)
        self.assertTrue(browser["_browser_task"]["review_only"])
        self.tools["read_page"].side_effect = None
        self.tools["get_reply"].return_value = {
            "action": "reply",
            "text": "Saved evidence reviewed",
        }
        self.assertEqual(
            agent_.run_agent("/continue", browser), "Saved evidence reviewed"
        )
        self.tools["click_node"].assert_called_once()

    def test_continue_cannot_open_a_replacement_tab_or_write_a_changed_document(self):
        """Old progress cannot authorize writes into a new page or replacement tab."""
        browser = {"playwright": self.connection, "page": self.page}
        self.tools["get_reply"].side_effect = RuntimeError("API unavailable")
        with self.assertRaises(RuntimeError):
            agent_.run_agent("Fill subject", browser)
        self.page.is_closed.return_value = True
        self.assertIn("tab is closed", agent_.run_agent("/continue", browser))
        self.tools["open_browser"].assert_not_called()
        self.page.context.new_page.assert_not_called()
        self.page.is_closed.return_value = False
        self.tools["read_page"].return_value = dict(
            self.observation, url="https://example.test/another"
        )
        self.tools["get_reply"].side_effect = None
        self.tools["get_reply"].return_value = {
            "action": "type",
            "backend_node_id": 12,
            "text": "Hello",
        }
        self.assertIn("no new input", agent_.run_agent("/continue", browser))
        self.tools["type_node"].assert_not_called()


class AgentModelPayloadTests(unittest.TestCase):
    def test_long_request_text_is_referenced_without_losing_generated_text(self):
        """Repeated text stays recoverable from the request; new content stays in history."""
        from observations_ import compact_history

        supplied = "Example information for the requested document. " * 6
        generated = "New generated content that was not supplied. " * 6
        request = "Enter these notes: " + supplied
        history = [
            {
                "action": {
                    "action": "batch",
                    "actions": [
                        {"action": "type", "backend_node_id": 1, "text": supplied},
                        {"action": "type", "backend_node_id": 2, "text": generated},
                    ],
                },
                "result": {"completed": 1, "remaining": 1, "stopped": "Changed"},
            }
        ]
        original = deepcopy(history)
        compact = compact_history(request, history)
        first = compact[0]["action"]["actions"][0]
        second = compact[0]["remaining_generated"][0]
        start, end = first["text_from_request"]
        self.assertEqual(request[start:end], supplied)
        self.assertEqual(second["text"], generated)
        self.assertEqual(compact[0]["result"], history[0]["result"])
        self.assertEqual(history, original)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(history)))

    def test_partial_history_omits_unsent_supplied_values_without_claiming_success(
        self,
    ):
        """Only the completed prefix is progress; local plans and errors stay intact."""
        from observations_ import compact_history

        actions = [
            {"action": "type", "backend_node_id": number, "text": "Supplied value"}
            for number in range(1, 5)
        ] + [{"action": "click", "backend_node_id": 5}]
        history = [
            {
                "action": {"action": "batch", "actions": actions},
                "result": {"completed": 1, "remaining": 4, "stopped": "Target changed"},
            }
        ]
        original = deepcopy(history)
        compact = compact_history("Use Supplied value in all fields", history)
        self.assertEqual(compact[0]["action"]["actions"], actions[:1])
        self.assertEqual(compact[0]["result"], history[0]["result"])
        self.assertNotIn("remaining_generated", compact[0])
        self.assertEqual(history, original)
        self.assertLess(len(json.dumps(compact)), len(json.dumps(history)))

    def test_partial_history_does_not_explain_offsets_when_none_are_used(self):
        """A short completed value does not need the long text-offset instruction."""
        history = [
            {
                "action": {
                    "action": "batch",
                    "actions": [
                        {"action": "type", "backend_node_id": 12, "text": "Hello"},
                        {"action": "click", "backend_node_id": 18},
                    ],
                },
                "result": {"completed": 1, "remaining": 1, "stopped": "Changed"},
            }
        ]
        environment = {
            "LLM_API_KEY": "fixture",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "fixture",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(llm_, "_client", None),
            patch.object(llm_, "OpenAI") as client,
        ):
            client.return_value.chat.completions.create.return_value = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"reply","text":"Paused"}'
                        )
                    )
                ]
            )
            llm_.get_reply("Type Hello and save", history=history)
            payload = json.loads(
                client.return_value.chat.completions.create.call_args.kwargs[
                    "messages"
                ][-1]["content"]
            )
        self.assertIn("completed actions", payload["history_note"])
        self.assertNotIn("character offsets", payload["history_note"])
        self.assertEqual(len(payload["previous_actions"][0]["action"]["actions"]), 1)

    def test_group_and_wait_only_accept_targets_shown_to_the_model(self):
        """Every grouped target is checked before the executor can write to any field."""
        observation = {
            "url": "https://example.test",
            "title": "Page",
            "elements": '[12] textbox "Subject"\n[18] button "Continue"',
        }
        environment = {
            "LLM_API_KEY": "fixture",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "fixture",
        }
        good = {
            "action": "batch",
            "actions": [
                {"action": "type", "backend_node_id": 12, "text": "Hello"},
                {"action": "click", "backend_node_id": 18},
            ],
        }
        bad = {
            "action": "batch",
            "actions": [good["actions"][0], {"action": "click", "backend_node_id": 99}],
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(llm_, "_client", None),
            patch.object(llm_, "OpenAI") as client,
        ):
            create = client.return_value.chat.completions.create
            for action, valid in (
                (good, True),
                (bad, False),
                ({"action": "wait_for", "text": "Ready"}, True),
                (
                    {"action": "wait_for", "backend_node_id": 99, "state": "enabled"},
                    False,
                ),
            ):
                create.return_value = SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=json.dumps(action))
                        )
                    ]
                )
                if valid:
                    self.assertEqual(llm_.get_reply("Continue", observation), action)
                else:
                    with self.assertRaises(RuntimeError):
                        llm_.get_reply("Continue", observation)


    def test_start_prompt_only_lists_actions_available_without_a_page(self):
        """Show page tools once the model has a page it can act on."""
        environment = {
            "LLM_API_KEY": "fixture",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "fixture",
        }
        observation = {"url": "https://example.test", "title": "Page", "elements": ""}
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(llm_, "_client", None),
            patch.object(llm_, "OpenAI") as client,
        ):
            create = client.return_value.chat.completions.create
            create.return_value = SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"action":"observe"}'))
            ])
            self.assertEqual(llm_.get_reply("Read my open page"), {"action": "observe"})
            first = create.call_args.kwargs["messages"][0]["content"]
            self.assertIn('"action":"observe"', first)
            self.assertNotIn("backend_node_id", first)

            create.return_value = SimpleNamespace(choices=[
                SimpleNamespace(message=SimpleNamespace(content='{"action":"reply","text":"Ready"}'))
            ])
            llm_.get_reply("Read my open page", observation)
            second = create.call_args.kwargs["messages"][0]["content"]
            self.assertIn("backend_node_id", second)

    def test_request_and_results_are_sent_without_duplicate_page_content(self):
        "Checks that the model gets the goal and results without repeated whole-page readings."
        environment = {
            "LLM_API_KEY": "fake-key",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "fake-model",
        }
        history = [
            {
                "action": {"action": "type", "backend_node_id": 12, "text": "Hello"},
                "result": "Value verified",
            }
        ]
        observation = {
            "url": "https://example.test",
            "title": "Form",
            "elements": '[12] textbox "Subject"',
            "content": "LOCAL ONLY",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(llm_, "_client", None),
            patch.object(llm_, "OpenAI") as client,
        ):
            client.return_value.chat.completions.create.return_value = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"reply","text":"Finished"}'
                        )
                    )
                ]
            )
            llm_.get_reply("Original request", observation, history)
            messages = client.return_value.chat.completions.create.call_args.kwargs[
                "messages"
            ]
        payload = json.loads(messages[-1]["content"])
        self.assertEqual(payload["request"], "Original request")
        self.assertEqual(payload["previous_actions"], history)
        self.assertNotIn("content", payload["page"])
        self.assertNotIn("LOCAL ONLY", messages[-1]["content"])

    def test_unseen_target_is_rejected_until_local_search_exposes_it(self):
        "Checks that the model cannot click a control it has not been shown."
        observation = {
            "url": "https://example.test",
            "title": "Controls",
            "page_id": 1,
            "document_id": 1,
            "controls": {
                number: {
                    "line": f'[{number}] button "Target {number}"',
                    "role": "button",
                    "name": f"Target {number}",
                    "context": [],
                    "value": "",
                    "states": {},
                }
                for number in range(1, 101)
            },
            "text_nodes": {},
        }
        environment = {
            "LLM_API_KEY": "fake-key",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "fake-model",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(llm_, "_client", None),
            patch.object(llm_, "OpenAI") as client,
        ):
            client.return_value.chat.completions.create.return_value = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"click","backend_node_id":99}'
                        )
                    )
                ]
            )
            with self.assertRaises(RuntimeError):
                llm_.get_reply("Continue", observation)
            history = [
                {
                    "action": {
                        "action": "find_elements",
                        "query": "Target 99",
                        "offset": 0,
                    },
                    "result": "Search requested",
                }
            ]
            action = llm_.get_reply("Continue", observation, history, observation)
            self.assertEqual(action["backend_node_id"], 99)
            payload = json.loads(
                client.return_value.chat.completions.create.call_args.kwargs[
                    "messages"
                ][-1]["content"]
            )
            self.assertIn(
                '[99] button "Target 99"', payload["page"]["search"]["elements"]
            )
            self.assertNotIn("controls", payload["page"])

    def test_search_action_requires_valid_query_offset_and_observation(self):
        "Checks that page-search requests have valid details and a current page reading."
        observation = {
            "url": "https://example.test",
            "title": "Page",
            "elements": '[12] button "Send"',
        }
        environment = {
            "LLM_API_KEY": "fake-key",
            "LLM_BASE_URL": "https://example.invalid/v1",
            "LLM_MODEL": "fake-model",
        }
        with (
            patch.dict(os.environ, environment, clear=True),
            patch.object(llm_, "_client", None),
            patch.object(llm_, "OpenAI") as client,
        ):
            create = client.return_value.chat.completions.create
            for query, offset, valid in (
                ("Send", 0, True),
                ("", 40, True),
                ("Send", -1, False),
                ("Send", True, False),
                (12, 0, False),
            ):
                create.return_value = SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=json.dumps(
                                    {
                                        "action": "find_elements",
                                        "query": query,
                                        "offset": offset,
                                    }
                                )
                            )
                        )
                    ]
                )
                if valid:
                    self.assertEqual(
                        llm_.get_reply("Find", observation)["action"], "find_elements"
                    )
                else:
                    with self.assertRaises(RuntimeError):
                        llm_.get_reply("Find", observation)
            create.return_value = SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='{"action":"find_elements","query":"Send"}'
                        )
                    )
                ]
            )
            with self.assertRaises(RuntimeError):
                llm_.get_reply("Find")


if __name__ == "__main__":
    unittest.main()
