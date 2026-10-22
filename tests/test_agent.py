"""Unit tests for Chexsa's agent loop."""

import unittest

from agent import Agent, AgentDecision


class AgentTests(unittest.TestCase):
    def test_done_with_action_executes_before_completion(self):
        launched = []
        observations = []

        def observe():
            observations.append(list(launched))
            return list(launched)

        def decide(request, state, history):
            if not history:
                return AgentDecision(action="launch_app", arguments={"command": "notepad.exe"}, done=True, response="Opened")
            self.assertEqual(state, ["notepad.exe"])
            return AgentDecision(done=True, response="Opened")

        agent = Agent(observe, decide, lambda action, arguments: launched.append(arguments["command"]))
        self.assertEqual(agent.run("Open Notepad"), "Opened")
        self.assertEqual(observations, [[], ["notepad.exe"]])

    def test_failed_action_marked_done_is_not_reported_as_completed(self):
        def execute(action, arguments):
            raise RuntimeError("Could not launch")

        def decide(request, state, history):
            if history:
                self.assertEqual(history[0].error, "Could not launch")
                return AgentDecision(done=True, response="Launch failed")
            return AgentDecision(action="launch_app", arguments={"command": "missing.exe"}, done=True, response="Opened")

        self.assertEqual(Agent(lambda: [], decide, execute).run("Open app"), "Launch failed")

    def test_runs_action_then_finishes(self):
        """The agent should execute an action and then finish."""

        decisions = iter(
            [
                AgentDecision(
                    action="navigate",
                    arguments={"url": "https://example.com"},
                ),
                AgentDecision(
                    done=True,
                    response="Done.",
                ),
            ]
        )
        executed = []

        agent = Agent(
            observe=lambda: "page",
            decide=lambda request, state, history: next(decisions),
            execute=lambda action, arguments: executed.append(
                (action, arguments)
            ),
        )

        response = agent.run("Open example.com")

        self.assertEqual(response, "Done.")
        self.assertEqual(
            executed,
            [("navigate", {"url": "https://example.com"})],
        )

    def test_stops_after_default_step_limit(self):
        """The default testing limit should stop after six actions."""

        executed = []

        agent = Agent(
            observe=lambda: "page",
            decide=lambda request, state, history: AgentDecision(
                action="scroll",
                arguments={"amount": 100},
            ),
            execute=lambda action, arguments: executed.append(
                (action, arguments)
            ),
        )

        response = agent.run("Keep scrolling")

        self.assertEqual(len(executed), 6)
        self.assertEqual(
            response,
            "Stopped after 6 steps before the task was complete.",
        )

    def test_action_error_is_given_back_to_the_model(self):
        """Action failures should appear in the next decision history."""

        seen_history = []

        def decide(request, state, history):
            seen_history.append(list(history))

            if not history:
                return AgentDecision(
                    action="click",
                    arguments={"role": "button", "name": "Missing"},
                )

            return AgentDecision(
                done=True,
                response="Stopped safely.",
            )

        def execute(action, arguments):
            raise RuntimeError("Button was not found.")

        agent = Agent(
            observe=lambda: "page",
            decide=decide,
            execute=execute,
        )

        response = agent.run("Click the button")

        self.assertEqual(response, "Stopped safely.")
        self.assertEqual(len(seen_history[1]), 1)
        self.assertEqual(
            seen_history[1][0].error,
            "Button was not found.",
        )


    def test_decision_error_stops_cleanly(self):
        """Model failures should stop the run without crashing."""

        def decide(request, state, history):
            raise RuntimeError("Model unavailable.")

        agent = Agent(
            observe=lambda: "page",
            decide=decide,
            execute=lambda action, arguments: None,
        )

        response = agent.run("Open YouTube")

        self.assertEqual(
            response,
            "Chexsa stopped: Model unavailable.",
        )


if __name__ == "__main__":
    unittest.main()
