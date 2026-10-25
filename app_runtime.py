"""Send each message to chat, Chrome, or a Windows app."""


from agent import Agent
from chexsa_browser.runtime import create_browser_agent
from desktop_actions import DesktopActions
from desktop_state import DesktopState
# LLM is our AI helper. The model name comes from the saved .env settings.
from llm import LLM


# Build the helper that looks at and controls Windows apps.
def create_desktop_agent(llm):
    state, actions = DesktopState(), DesktopActions()
    # Give the runner three jobs: look at the screen, ask the AI, and act.
    return Agent(observe=state.observe, decide=llm.decide_desktop, execute=actions.execute)


class AppSession:
    # Remember the helpers so we can reuse them for each message.
    def __init__(self, llm=None):
        # Keep an AI helper if one was supplied; tests can supply a fake one.
        self.llm = llm
        # The backend controls Chrome; the agent runs the task. None means not started.
        self.browser_backend = self.browser_agent = self.desktop_agent = None
        self.last_mode = None

    # Start the browser tools once and reuse them for later requests.
    def _browser(self):
        if self.browser_agent is None:
            self.browser_backend, self.browser_agent = create_browser_agent(self.llm)
        return self.browser_agent

    # Choose the right helper and pass it your message.
    def run(self, request):
        # Create the AI helper on the first request, using the saved settings.
        if self.llm is None:
            self.llm = LLM()
        # Get the current browser task, or None if there is no task yet.
        state = getattr(self.browser_agent, "state", None)
        if state and state.status == "blocked" and state.question:
            mode = "browser"  # This message answers the browser task's question.
        else:
            mode = self.llm.choose_mode(request)
        if mode not in ("chat", "browser", "desktop"):
            raise ValueError("The model did not choose chat, browser, or desktop. Please retry.")
        # Tell cli.py which helper was chosen so it can show the right status.
        self.last_mode = mode
        if mode == "chat":
            return self.llm.reply(request)
        if mode == "desktop":
            if self.desktop_agent is None:
                self.desktop_agent = create_desktop_agent(self.llm)
            return self.desktop_agent.run(request)
        # Chat and desktop already returned, so this request goes to the browser.
        return self._browser().run(request)

    # Close browser connections when you leave Chexsa.
    def close(self):
        if self.browser_backend is not None:
            self.browser_backend.close()
            self.browser_backend = self.browser_agent = None
