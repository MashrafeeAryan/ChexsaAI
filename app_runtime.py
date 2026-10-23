"""Route requests and create browser or desktop resources only when needed."""

from agent import Agent
from chexsa_browser.runtime import create_browser_agent
from desktop_actions import DesktopActions
from desktop_state import DesktopState
from llm import LLM


def create_desktop_agent(llm):
    state, actions = DesktopState(), DesktopActions()
    return Agent(observe=state.observe, decide=llm.decide_desktop, execute=actions.execute)


class AppSession:
    def __init__(self, llm=None, max_steps=None, timeout=None, model=None):
        self._llm = llm
        self.model_override = model
        self.max_steps, self.timeout = max_steps, timeout
        self.browser_backend = self.browser_agent = self.desktop_agent = None
        self.last_mode = None

    @property
    def llm(self):
        if self._llm is None:
            self._llm = LLM(model=self.model_override) if self.model_override else LLM()
        return self._llm

    def _browser(self):
        if self.browser_agent is None:
            self.browser_backend, self.browser_agent = create_browser_agent(self.llm, max_steps=self.max_steps, timeout=self.timeout)
        return self.browser_agent

    def run(self, request):
        state = getattr(self.browser_agent, "state", None)
        if state and state.status == "blocked" and state.question:
            mode = "browser"  # Keep an answer attached to the task that asked for it.
        else:
            mode = self.llm.choose_mode(request)
        if mode not in ("chat", "browser", "desktop"):
            raise ValueError("The model did not choose chat, browser, or desktop. Please retry.")
        self.last_mode = mode
        if mode == "chat":
            return self.llm.reply(request)
        if mode == "desktop":
            if self.desktop_agent is None:
                self.desktop_agent = create_desktop_agent(self.llm)
            return self.desktop_agent.run(request)
        return self._browser().run(request)

    def resume(self, task_id):
        self.last_mode = "browser"
        return self._browser().run_task(task_id=task_id)

    def close(self):
        if self.browser_backend is not None:
            self.browser_backend.close()
            self.browser_backend = self.browser_agent = None
