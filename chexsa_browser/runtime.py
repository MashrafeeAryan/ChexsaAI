"""Set up the same browser tools for terminal and voice requests."""

# Read the saved Chrome connection and profile settings.
import os

# Run the task by observing, choosing an action, and checking the result.
from .agent import BrowserAgent
# Connect to Chrome, read pages, and carry out actions.
from .backend import BrowserBackend
# Save task progress in a local database.
from .journal import TaskJournal
# Give the AI browser instructions and read its decisions.
from .model import BrowserModel


# Connect the browser tools, AI decisions, and saved progress in one place.
def create_browser_agent(llm):
    backend = BrowserBackend(
        cdp_url=os.getenv("CHEXSA_CDP_URL"),
        profile_dir=os.getenv("CHEXSA_CHROME_USER_DATA_DIR"),
        profile_name=os.getenv("CHEXSA_CHROME_PROFILE", "Default"),
        auto_launch=os.getenv("CHEXSA_AUTO_LAUNCH", "1").lower() in ("1", "true", "yes"),
        # Keep the page summary small to reduce token use.
        context_budget=6000,
        trace_screenshots=os.getenv("CHEXSA_TRACE_SCREENSHOTS", "0").lower() in ("1", "true", "yes"),
    )
    journal = TaskJournal()
    # Let browser cleanup also close the task database.
    backend.task_journal = journal
    try:
        backend.connect()
        # Use built-in limits: 50 actions, 10 minutes, and 3 failures in a row.
        agent = BrowserAgent(backend, BrowserModel(llm), journal=journal)
        return backend, agent
    except Exception:
        # Release the connections and database if setup fails.
        backend.close()
        raise
