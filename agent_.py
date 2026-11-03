"""Keep asking what to do next until the request ends or the agent must stop."""

from browser_ import (
    click_node,
    open_browser,
    read_page,
    type_node,
    run_action_group,
    wait_for_page,
)
from llm_ import get_reply
from app_runtime_ import check_cancelled


# Keep one request and its action history together while working in the browser.
def run_agent(message, browser):
    """Start a request, or continue its saved progress using a new page reading.

    Example: after Stop, enter 'continue' in the same browser session.
    The checkpoint lives only in memory; closing Chexsa clears it.
    """
    check_cancelled(browser)
    command = message.strip().casefold()
    saved = browser.get("_browser_task")
    resuming = command in ("/continue", "/resume") or (
        command in ("continue", "resume")
        and saved is not None
        and saved["status"] != "finished"
    )
    if resuming:
        task = saved
        if task is None or task["status"] == "finished":
            return "No unfinished browser request to continue. Give a new request."
        if task["in_flight"] is not None:
            return "Previous input has an uncertain outcome. Check the page before starting another request."
    else:
        task = {
            "request": message,
            "history": [],
            "status": "running",
            "in_flight": None,
        }
        browser["_browser_task"] = task

    task["status"] = "running"
    try:
        return _run_browser_task(task, browser)
    except (Exception, KeyboardInterrupt):
        # Keep progress, but let the CLI or app display the original error or Stop.
        task["status"] = "paused"
        raise


def _run_browser_task(task, browser):
    """Use saved results for planning, while getting all executable IDs afresh."""
    message, history = task["request"], task["history"]
    # The CLI keeps this dictionary so later requests can reuse the same Chrome tab.
    check_cancelled(browser)
    page = browser.get("page")
    observation = read_page(page) if page is not None and not page.is_closed() else None
    last_action = None
    last_observation = None
    previous = None

    # Each turn can make one model call. This fixed limit prevents endless API calls.
    for step in range(10):
        check_cancelled(browser)
        action = get_reply(message, observation, history, previous)
        # Stop may have been pressed while the model was replying.
        check_cancelled(browser)
        if action["action"] == "reply":
            # A reply ends the run: an answer, missing information, or a final report.
            task["status"] = "finished"
            return action["text"]
        if action == last_action and observation == last_observation:
            task["status"] = "paused"
            return "Stopped because the AI repeated an action without a page change. Please check the page."

        if action["action"] in ("navigate", "observe"):
            # Talking to Chexsa alone does not open Chrome.
            if browser.get("playwright") is None:
                browser["playwright"], browser["page"] = open_browser()
            elif browser["page"].is_closed():
                browser["page"] = browser["page"].context.new_page()
            page = browser["page"]

        next_observation = None
        group_error = None
        entry = {"action": action.copy(), "result": "Not completed."}
        history.append(entry)
        # Save input intent before execution. An exception must not erase it.
        if action["action"] in ("click", "type"):
            task["in_flight"] = action.copy()
        # Any action error leaves this function immediately. Uncertain actions are not retried.
        if action["action"] == "observe":
            result = "Browser connected; current page will be read."
        elif action["action"] == "find_elements":
            result = "Local search requested; fresh matches are supplied with the next observation."
        elif action["action"] == "navigate":
            page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
            result = "Navigation finished."
        elif action["action"] == "click":
            click_node(page, action["backend_node_id"])
            result = "Click sent. Check the new observation for its outcome."
        elif action["action"] == "type":
            type_node(page, action["backend_node_id"], action["text"])
            result = "Text entered and the field value verified."
            task["in_flight"] = None
        elif action["action"] == "batch":

            def remember(progress):
                """Keep completed counts even if Stop interrupts this group."""
                entry["result"] = {
                    "completed": len(progress["completed"]),
                    "remaining": progress["remaining"],
                    "stopped": progress["stopped"],
                }
                task["in_flight"] = progress["attempting"]

            # The browser rechecks targets between actions without consulting the model.
            group = run_action_group(
                page,
                action["actions"],
                observation,
                lambda: check_cancelled(browser),
                remember,
            )
            next_observation = group["observation"]
            result = {
                "completed": len(group["completed"]),
                "remaining": group["remaining"],
                "stopped": group["stopped"],
            }
            group_error = group["error"]
        elif action["action"] == "wait_for":
            waiting = wait_for_page(
                page, action, observation, lambda: check_cancelled(browser)
            )
            next_observation = waiting["observation"]
            result = {"matched": waiting["matched"], "reason": waiting["reason"]}
        else:
            raise RuntimeError("Unsupported agent action. Nothing was run.")

        entry["result"] = result
        if group_error:
            raise RuntimeError(
                f"Stopped after {result['completed']} actions were sent or verified. {group_error} Do not repeat the group automatically."
            )
        last_action, last_observation = action.copy(), observation
        # Observe after every action; the next decision gets current nodes and page state.
        check_cancelled(browser)
        previous = observation
        observation = (
            next_observation if next_observation is not None else read_page(page)
        )
        task["in_flight"] = None

    task["status"] = "paused"
    return "Stopped after 10 model decisions. The request may be unfinished; please check the page."
