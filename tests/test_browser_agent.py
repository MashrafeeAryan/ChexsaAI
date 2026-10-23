import unittest
from types import SimpleNamespace

from chexsa_browser.agent import BrowserAgent
from chexsa_browser.models import ActionRequest, ActionResult, Observation, TaskSpec, TaskState
from chexsa_browser.verification import completion_is_supported, failure_is_supported


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.observation = Observation("o1", "p", "url", "title", [], [], {"status": {"text": "Ready", "region_path": ()}}, context="Ready", fingerprint="same")

    def observe(self):
        return self.observation

    def execute(self, action):
        self.calls.append(action)
        return ActionResult(action.action, "ok", executed=True)

    def wait_for_change(self, *args):
        pass


class FakeModel:
    def plan(self, request, observation, state=None):
        return TaskSpec(request, subgoals=["work"], completion=["done"])

    def choose(self, state, observation):
        return ActionRequest("finish", {"response": "Done"})

    def verify(self, *args):
        return {"complete": True, "evidence": ["invented"], "progress": "", "reason": ""}


class BrowserAgentTests(unittest.TestCase):
    def test_live_receipt_is_bound_to_checked_dispatch_and_its_page_frame(self):
        from chexsa_browser.verification import submission_confirmation
        def fresh():
            state = TaskState("t", TaskSpec("Send email", inputs={"recipient": "fixture@example.test"}))
            state.email_checked, state.submission = True, "uncertain"
            state.commit_page_id, state.commit_frame_id = "p", "f"
            state.commit_baseline = "Ready"
            observation = Observation("o2", "p", "url", "title", [], [], {"t/f/d/1": {"text": "Message sent", "region_path": (), "live": True}})
            return state, observation
        self.assertEqual(submission_confirmation(*fresh()), "Message sent")
        for change in ("old", "body", "page", "frame", "unchecked", "not_dispatched", "failure"):
            with self.subTest(change=change):
                state, observation = fresh()
                if change == "old": state.commit_baseline = "Message sent"
                elif change == "body": observation.text["t/f/d/1"]["live"] = False
                elif change == "page": observation.page_id = "another"
                elif change == "frame": state.commit_frame_id = "another"
                elif change == "unchecked": state.email_checked = False
                elif change == "not_dispatched": state.submission = "none"
                else: observation.text["t/f/d/1"]["text"] = "Message could not be sent"
                self.assertEqual(submission_confirmation(state, observation), "")

    def test_receipt_does_not_finish_other_unverified_task_outcomes(self):
        backend, model = FakeBackend(), FakeModel()
        state = TaskState("t", TaskSpec("Send email and download a file", completion=["Sent", "Downloaded"]))
        state.email_checked, state.submission = True, "uncertain"
        state.commit_page_id, state.commit_frame_id = "p", "f"
        backend.observation.text = {"t/f/d/1": {"text": "Message sent", "region_path": (), "live": True}}
        model.verify = lambda *args: {"complete": False, "evidence": [], "reason": "Download not done"}
        result = BrowserAgent(backend, model, emit=lambda text: None).run_task(state=state)
        self.assertEqual(result.status, "blocked")
        self.assertIn("confirmed the email was sent", result.message)
        self.assertEqual(state.submission, "confirmed")
        self.assertIn("Verified application receipt: Message sent", state.progress)

    def test_equal_subject_and_body_cannot_verify_the_same_control_twice(self):
        from unittest.mock import Mock
        from chexsa_browser.verification import preflight_email
        from chexsa_browser.models import BrowserError
        state = TaskState("t", TaskSpec("Send email", inputs={"recipient": "fixture@example.test", "subject": "Hello", "body": "Hello"}))
        backend, model = Mock(), Mock()
        model.preflight.return_value = {"ready": True, "subject_ref": "e1", "body_ref": "e1", "recipient_ref": "e2"}
        with self.assertRaises(BrowserError):
            preflight_email(state, FakeBackend().observation, backend, model)
        backend.registry.resolve.assert_not_called()
        self.assertFalse(state.email_checked)
    def test_model_submission_hint_cannot_turn_compose_or_search_into_send(self):
        from chexsa_browser.verification import is_submission
        from chexsa_browser.models import Element
        observation = FakeBackend().observation
        element = Element("t", "f", "d", 1, "button", "Compose", ref="e1")
        observation.elements = [element]
        self.assertFalse(is_submission(ActionRequest("click", {"ref": "e1"}, {"kind": "submission"}), observation))
        element.name = "Send"
        self.assertTrue(is_submission(ActionRequest("click", {"ref": "e1"}, {"kind": "change"}), observation))
        element.name, element.role = "Search", "searchbox"
        self.assertFalse(is_submission(ActionRequest("type", {"ref": "e1", "text": "query", "press_enter": True}, {"kind": "submission"}), observation))
        element.name = "Message body"
        self.assertFalse(is_submission(ActionRequest("type", {"ref": "e1", "text": "message"}, {"kind": "submission"}), observation))
    def test_clarification_survives_provider_failure(self):
        backend, model = FakeBackend(), FakeModel()
        agent = BrowserAgent(backend, model, emit=lambda text: None)
        agent.state = TaskState("t", TaskSpec("Send email to fixture@example.test"), status="blocked", question="What message?")
        model.plan = lambda *args: (_ for _ in ()).throw(RuntimeError("Model unavailable"))
        agent.run("Hello, how are you?")
        self.assertEqual(agent.state.question, "What message?")
        self.assertIn("fixture@example.test", agent.state.spec.goal)
        self.assertIn("Hello, how are you?", agent.state.spec.goal)
        self.assertEqual(agent.last_result.status, "blocked")

    def test_schema_placeholder_is_not_shown_as_success_message(self):
        backend, model = FakeBackend(), FakeModel()
        model.verify = lambda *args: {"complete": True, "evidence": ["Ready"], "progress": "verified fact"}
        result = BrowserAgent(backend, model, emit=lambda text: None).run_task("task")
        self.assertEqual(result.status, "success")
        self.assertEqual(result.message, "The requested outcome was verified.")

    def test_email_without_body_asks_before_any_action(self):
        backend, model = FakeBackend(), FakeModel()
        model.plan = lambda *args: TaskSpec("Send email", inputs={"recipient": "fixture@example.test", "subject": "Hello", "body": ""})
        agent = BrowserAgent(backend, model, emit=lambda text: None)
        result = agent.run_task("Send email to fixture@example.test")
        self.assertEqual(result.status, "blocked")
        self.assertEqual(agent.state.question, "What message should I send?")
        self.assertFalse(backend.calls)

    def test_model_wait_cannot_execute_an_action_after_deadline(self):
        from unittest.mock import patch
        backend, model = FakeBackend(), FakeModel()
        clock = [0]
        def choose(*args):
            clock[0] = 2
            return ActionRequest("click", {"ref": "e1"}, {"kind": "submission"})
        model.choose = choose
        with patch("chexsa_browser.agent.time.monotonic", side_effect=lambda: clock[0]):
            result = BrowserAgent(backend, model, timeout=1, emit=lambda text: None).run_task("Work")
        self.assertEqual(result.status, "blocked")
        self.assertFalse(backend.calls)

    def test_navigation_can_be_verified_by_actual_url_and_title(self):
        state = TaskState("t", TaskSpec("Open example.test"))
        observation = Observation("o1", "p", "https://example.test/", "Example website", [], [], {})
        self.assertTrue(completion_is_supported(state, observation, {"complete": True, "evidence": ["https://example.test/", "Example website"]}))
        self.assertFalse(completion_is_supported(state, observation, {"complete": True, "evidence": ["Title: Example website"]}))

    def test_startup_failure_is_available_to_cli(self):
        backend = FakeBackend()
        backend.observe = lambda: (_ for _ in ()).throw(RuntimeError("Cannot observe"))
        agent = BrowserAgent(backend, FakeModel(), emit=lambda text: None)
        result = agent.run_task("Open a website")
        self.assertEqual(result.status, "failed")
        self.assertIs(agent.last_result, result)

    def test_completion_requires_real_evidence(self):
        backend = FakeBackend()
        agent = BrowserAgent(backend, FakeModel(), emit=lambda text: None)
        result = agent.run_task("task")
        self.assertEqual(result.status, "blocked")
        self.assertFalse(backend.calls)

    def test_repeated_actions_replan_then_stop(self):
        backend, model = FakeBackend(), FakeModel()
        model.choose = lambda *args: ActionRequest("scroll", {"amount": 0})
        result = BrowserAgent(backend, model, emit=lambda text: None).run_task("task")
        self.assertEqual(result.status, "blocked")
        self.assertLess(len(backend.calls), 10)

    def test_question_preserves_task_and_original_values(self):
        model = FakeModel()
        model.choose = lambda *args: ActionRequest("ask_user", {"question": "Which account?"})
        agent = BrowserAgent(FakeBackend(), model, emit=lambda text: None)
        result = agent.run_task("send to intended@example.test")
        self.assertEqual(result.status, "blocked")
        self.assertIn("intended@example.test", agent.state.spec.goal)
        self.assertEqual(agent.state.question, "Which account?")

    def test_old_confirmation_cannot_prove_a_new_send(self):
        state = TaskState("t", TaskSpec("send", inputs={"recipient": "x@example.test"}))
        state.submission, state.email_checked = "uncertain", True
        state.commit_baseline = "Message sent"
        observation = Observation("o1", "p", "url", "title", [], [], {"x": {"text": "Message sent", "region_path": ()}})
        self.assertFalse(completion_is_supported(state, observation, {"complete": True, "evidence": ["Message sent"]}))

    def test_draft_task_blocks_submission(self):
        backend, model = FakeBackend(), FakeModel()
        model.plan = lambda *args: TaskSpec("draft", intent="draft")
        model.choose = lambda *args: ActionRequest("click", {"ref": "e1"}, {"kind": "submission"})
        result = BrowserAgent(backend, model, emit=lambda text: None).run_task("draft")
        self.assertEqual(result.status, "blocked")
        self.assertFalse(backend.calls)

    def test_failure_needs_actual_new_evidence(self):
        state = TaskState("t", TaskSpec("submit"))
        observation = FakeBackend().observation
        verdict = {"failed": True, "complete": False, "evidence": ["server refused"]}
        self.assertFalse(failure_is_supported(state, observation, verdict))
        observation.text["error"] = {"text": "server refused", "region_path": ()}
        self.assertTrue(failure_is_supported(state, observation, verdict))

    def test_visual_completion_requires_the_current_screenshot(self):
        state = TaskState("t", TaskSpec("inspect visual result"))
        observation = FakeBackend().observation
        observation.screenshot, observation.screenshot_id = b"captured image", "fresh"
        verdict = {"complete": True, "evidence": [], "visual_evidence": True, "screenshot_id": "old"}
        self.assertFalse(completion_is_supported(state, observation, verdict))
        verdict["screenshot_id"] = "fresh"
        self.assertTrue(completion_is_supported(state, observation, verdict))
