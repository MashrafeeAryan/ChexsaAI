"""Runs Chexsa's observe, decide, and act loop."""

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class AgentDecision:
    """Describe what the LLM wants Chexsa to do next."""

    action: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)
    done: bool = False
    response: str = ""


@dataclass
class StepResult:
    """Store what happened after one attempted action."""

    action: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None


ObserveFn = Callable[[], Any]
DecideFn = Callable[[str, Any, list[StepResult]], AgentDecision]
ExecuteFn = Callable[[str, dict[str, Any]], Any]


class Agent:
    """Run Chexsa's observe, decide, and act loop."""

    def __init__(
        self,
        observe: ObserveFn,
        decide: DecideFn,
        execute: ExecuteFn,
        max_steps: int = 6,
    ) -> None:
        self.observe = observe
        self.decide = decide
        self.execute = execute
        self.max_steps = max_steps

    def run(self, request: str) -> str:
        """Keep working until the task finishes or reaches the step limit."""

        history: list[StepResult] = []

        # Start each step by reading the latest state.
        for step_number in range(1, self.max_steps + 1):
            try:
                state = self.observe()
                decision = self.decide(request, state, history)
            except Exception as error:
                return f"Chexsa stopped: {error}"

            print(
                f"[AGENT] Step {step_number}: "
                f"action={decision.action or 'none'} "
                f"arguments={decision.arguments} "
                f"done={decision.done}"
            )

            if decision.done and not decision.action:
                return decision.response or "Task complete."

            if not decision.action:
                return "Chexsa could not choose a next action."

            step = self._run_step(decision)
            history.append(step)
            # An action is still a proposal even when the model marks it done.
            # Execute it, then observe again before accepting completion.

        return f"Stopped after {self.max_steps} steps before the task was complete."

    def _run_step(self, decision: AgentDecision) -> StepResult:
        """Run one action and save what happened."""

        try:
            result = self.execute(decision.action, decision.arguments)

            return StepResult(
                action=decision.action,
                arguments=decision.arguments,
                result=result,
            )

        except Exception as error:
            # Save failures so the LLM can react on the next step.
            return StepResult(
                action=decision.action,
                arguments=decision.arguments,
                error=str(error),
            )
