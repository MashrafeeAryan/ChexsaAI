"""Bounded observe/act/verify loop with explicit uncertainty and recovery."""

import time
import uuid
import hashlib

from .actions import DISCOVERY
from .models import BrowserError, TaskResult, TaskState
from .verification import completion_is_supported, evidence_text, failure_is_supported, is_submission, preflight_email


class BrowserAgent:
    def __init__(self, backend, model, max_steps=50, timeout=600, max_failures=3, journal=None, emit=print):
        self.backend, self.model = backend, model
        self.max_steps, self.timeout, self.max_failures = max_steps, timeout, max_failures
        self.journal, self.emit = journal, emit
        self.state = None
        self.cancelled = False
        self.last_result = None
        self._usage_start = {}

    def cancel(self):
        self.cancelled = True

    def _save(self):
        if self.journal and self.state:
            self.journal.save(self.state)

    def _finish(self, status, message):
        self.state.status = status
        self.state.result_message = message
        self.state.metrics.update({key: value - self._usage_start.get(key, 0) for key, value in getattr(self.model, "usage", {}).items()})
        self._save()
        self.last_result = TaskResult(status, message, self.state.id)
        return self.last_result

    def run(self, request):
        if self.state and self.state.status == "blocked" and self.state.question:
            request = self.state.spec.goal + "\nUser clarification: " + request
            self.state.spec.goal = request
            self.state.question = ""
            self.state.spec = self.model.plan(request, self.backend.observe(), self.state)
            result = self.run_task(state=self.state)
        else:
            result = self.run_task(request)
        return result.message

    def run_task(self, request=None, state=None, task_id=None):
        started = time.monotonic()
        self.cancelled = False
        self._usage_start = dict(getattr(self.model, "usage", {}))
        self.state = state
        try:
            if task_id:
                if self.journal is None:
                    raise ValueError("A task journal is required to resume a task.")
                state = self.journal.load(task_id)
                self.state = state
                if state.status == "success":
                    self.last_result = TaskResult("success", state.result_message or "This task was already completed; no actions were replayed.", state.id)
                    return self.last_result
            observation = self.backend.observe()
            if state is None:
                self.state = TaskState(uuid.uuid4().hex, self.model.plan(request, observation))
            else:
                self.state = state
                self.state.status = "running"
                # A crash may have occurred after the browser acted but before recording the result.
                if self.state.submission == "attempting":
                    self.state.submission = "uncertain"
                self.state.history.append({"action": "resume", "status": "ok", "message": "Observed current state; do not replay previous actions."})
            self._save()
            if "recipient" in self.state.spec.inputs:
                missing = [key for key in ("recipient", "body") if not self.state.spec.inputs.get(key, "").strip()]
                if missing:
                    self.state.question = "Who is the recipient, and what message should I send?" if len(missing) == 2 else ("Who should I send it to?" if missing[0] == "recipient" else "What message should I send?")
                    return self._finish("blocked", self.state.question)
            previous = None
            last_signature, repeats, replans = None, 0, 0
            for _ in range(self.max_steps):
                if self.cancelled:
                    return self._finish("cancelled", "Task cancelled.")
                if time.monotonic() - started >= self.timeout:
                    break
                self.state.steps += 1
                try:
                    action = self.model.choose(self.state, observation)
                    if self.cancelled:
                        return self._finish("cancelled", "Task cancelled before the next action.")
                    if time.monotonic() - started >= self.timeout:
                        break
                    self.emit(f"[BROWSER] Step {self.state.steps}: {action.action}")
                    if action.action == "ask_user":
                        self.state.question = action.arguments["question"]
                        return self._finish("blocked", self.state.question)
                    if action.action == "finish":
                        # Always refresh; a completion proposal is never its own evidence.
                        if self.state.submission == "uncertain":
                            self.backend.wait_for_change()
                        current = self.backend.observe()
                        if observation.screenshot:
                            self.backend.capture_screenshot()
                        verdict = self.model.verify(self.state, previous or observation, current)
                        if self.state.spec.intent == "draft" and "recipient" in self.state.spec.inputs:
                            preflight_email(self.state, current, self.backend, self.model)
                        if completion_is_supported(self.state, current, verdict):
                            return self._finish("success", verdict.get("progress") or "The requested outcome was verified.")
                        if failure_is_supported(self.state, current, verdict):
                            return self._finish("failed", verdict.get("reason") or "The application reported a failure.")
                        observation = current
                        raise BrowserError("verification_failed", "Completion was not supported by fresh page evidence. Continue inspecting the task.")
                    target_ref = action.arguments.get("ref")
                    target = next((e.identity for e in observation.elements if e.ref == target_ref), target_ref)
                    signature = (observation.fingerprint, action.action, repr({**action.arguments, "ref": target}))
                    repeats = repeats + 1 if signature == last_signature else 1
                    last_signature = signature
                    if repeats >= 3:
                        if replans >= 1:
                            return self._finish("uncertain" if self.state.submission != "none" else "blocked", "Stopped because repeated actions made no progress.")
                        replans += 1
                        self.state.spec = self.model.plan(self.state.spec.goal, observation, self.state)
                        self.state.history.append({"action": "replan", "status": "ok", "message": "Repeated action without progress; choose a different approach."})
                        repeats = 0
                        continue
                    submission = is_submission(action, observation)
                    if submission:
                        if self.state.spec.intent == "draft":
                            raise BrowserError("not_authorized", "The user requested a draft, not submission.")
                        if self.state.submission != "none":
                            raise BrowserError("outcome_uncertain", "Submission was already attempted. Inspect the outcome; do not submit again.")
                        if "recipient" in self.state.spec.inputs:
                            preflight_email(self.state, observation, self.backend, self.model, action)
                        if time.monotonic() - started >= self.timeout:
                            break
                        self.state.commit_baseline = evidence_text(observation)
                        self.state.commit_image_hash = hashlib.sha256(observation.screenshot).hexdigest() if observation.screenshot else ""
                        self.state.submission = "attempting"
                        self._save()  # Persist BEFORE dispatch, not after.
                    result = self.backend.execute(action)
                    self.state.history.append({"action": action.action, "arguments": action.arguments, "status": result.status, "message": result.message, "code": result.code, "data": result.data})
                    if submission:
                        self.state.submission = "uncertain" if result.executed else "none"
                    self._save()
                    if result.status != "ok":
                        self.state.metrics["targeting_failures"] = self.state.metrics.get("targeting_failures", 0) + int(result.code in ("stale_target", "target_detached", "blocked"))
                    if action.action in DISCOVERY:
                        observation = self.backend.observation
                    else:
                        self.backend.wait_for_change()
                        previous, observation = observation, self.backend.observe()
                        if previous.screenshot and action.action not in ("navigate", "go_back", "new_tab", "close_tab", "switch_tab"):
                            self.backend.capture_screenshot()
                        if result.data.get("verified"):
                            self.state.progress.append(f"Verified {action.action} against the actual control state.")
                        if submission and result.executed:
                            verdict = self.model.verify(self.state, previous, observation, result)
                            if completion_is_supported(self.state, observation, verdict):
                                self.state.submission = "confirmed"
                                return self._finish("success", verdict.get("progress") or "The requested submission was confirmed by the application.")
                            if failure_is_supported(self.state, observation, verdict):
                                return self._finish("failed", verdict.get("reason") or "The application reported a failure.")
                    if result.status != "ok":
                        raise BrowserError(result.code, result.message)
                    self.state.failures = 0
                except BrowserError as error:
                    if error.code == "rate_limited":
                        return self._finish("uncertain" if self.state.submission != "none" else "blocked", str(error))
                    self.state.failures += 1
                    self.state.history.append({"action": "recovery", "status": "error", "message": str(error), "code": error.code})
                    self._save()
                    if self.state.failures >= self.max_failures:
                        return self._finish("uncertain" if self.state.submission != "none" else "blocked", "Could not verify the submission; it will not be sent again automatically." if self.state.submission != "none" else f"Task needs attention: {error}")
                    observation = self.backend.observe()
                    self.emit(f"[BROWSER] Refreshing after {error.code}.")
            return self._finish("uncertain" if self.state.submission != "none" else "blocked", "Stopped at the configured task limit. Progress was preserved.")
        except KeyboardInterrupt:
            if self.state:
                return self._finish("cancelled", "Task cancelled.")
            self.last_result = TaskResult("cancelled", "Task cancelled.", "")
            return self.last_result
        except Exception as error:
            if self.state:
                return self._finish("uncertain" if self.state.submission != "none" else "failed", f"Chexsa stopped: {error}")
            self.last_result = TaskResult("failed", f"Chexsa could not start the task: {error}", "")
            return self.last_result
        finally:
            if self.state:
                self.state.metrics["latency_ms"] = round((time.monotonic() - started) * 1000)
                self._save()
