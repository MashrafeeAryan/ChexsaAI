"""One construction path for terminal and voice mode."""

import os

from .agent import BrowserAgent
from .backend import BrowserBackend
from .journal import TaskJournal
from .model import BrowserModel


def positive_setting(name, default, minimum=1):
    value = int(os.getenv(name, str(default)))
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}.")
    return value


def create_browser_agent(llm, max_steps=None, timeout=None):
    backend = BrowserBackend(cdp_url=os.getenv("CHEXSA_CDP_URL", "http://127.0.0.1:9222"), auto_launch=os.getenv("CHEXSA_AUTO_LAUNCH", "1").lower() in ("1", "true", "yes"), context_budget=positive_setting("CHEXSA_CONTEXT_CHARS", 6000, 2000), trace_screenshots=os.getenv("CHEXSA_TRACE_SCREENSHOTS", "0").lower() in ("1", "true", "yes"))
    journal = TaskJournal()
    backend.task_journal = journal
    try:
        backend.connect()
        agent = BrowserAgent(backend, BrowserModel(llm), journal=journal, max_steps=max_steps or positive_setting("CHEXSA_MAX_STEPS", 50), timeout=timeout or positive_setting("CHEXSA_TIMEOUT", 600), max_failures=positive_setting("CHEXSA_MAX_FAILURES", 3))
        return backend, agent
    except Exception:
        backend.close()
        raise
