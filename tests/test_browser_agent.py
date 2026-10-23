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
