"""Keep asking what to do next until the request ends or the agent must stop."""

import os

from playwright.sync_api import Error

from plugins.canvas_ import assignment_path, canvas_command, canvas_intent

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
    parts = message.strip().split(maxsplit=1)
    if parts and parts[0].casefold() == "/canvas":
        return canvas_command(
            parts[1] if len(parts) > 1 else "",
            browser,
            lambda: check_cancelled(browser),
            lambda url: _open_assignment(browser, url),
        )
    route = _canvas_route(message, browser)
    if route is not None:
        return _run_canvas_request(route, browser)
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
        if task.get("review_only"):
            task["history"].append(
                {
                    "action": {"action": "observe"},
                    "result": "Recovery is inspection only: previous input may have been sent. Use fresh evidence; do not send new input.",
                }
            )
    else:
        if saved and saved.get("review_only") and message == saved["request"]:
            return "The previous attempt may already have changed the page. Enter /continue to inspect its result before repeating it."
        task = {
            "request": message,
            "history": [],
            "status": "running",
            "in_flight": None,
        }
        browser["_browser_task"] = task

    if resuming and (browser.get("page") is None or browser["page"].is_closed()):
        return "The saved browser tab is closed. Start a new request; old targets will not be reused."
    task["status"] = "running"
    try:
        return _run_browser_task(task, browser, resuming)
    except (Exception, KeyboardInterrupt):
        # Keep progress, but let the CLI or app display the original error or Stop.
        task["status"] = "paused"
        raise
    finally:
        # Limits and repeated-action stops must protect sent clicks too.
        if task["status"] == "paused":
            task["review_only"] = (
                task.get("review_only", False)
                or task["in_flight"] is not None
                or any(
                    entry["action"]["action"] == "click"
                    or (
                        entry["action"]["action"] == "batch"
                        and any(
                            item["action"] == "click"
                            for item in entry["action"]["actions"][
                                : entry["result"].get("completed", 0)
                            ]
                        )
                    )
                    for entry in task["history"]
                    if isinstance(entry["result"], dict)
                    or entry["action"]["action"] == "click"
                )
            )


def _canvas_route(message, browser):
    """Check if the user wants to work with a Canvas assignment."""
    known_assignment = bool(browser.get("_canvas_link"))
    page = browser.get("page")
    school = os.getenv("CANVAS_URL", "").strip()
    url = getattr(page, "url", "")
    if not known_assignment and school and isinstance(url, str) and url:
        try:
            assignment_path(url, school)
            known_assignment = True
        except ValueError:
            pass
    route = canvas_intent(message, known_assignment, bool(browser.get("_canvas_review")))
    if route is None and school and "this assignment" in message.casefold():
        candidate = canvas_intent(message, has_assignment=True)
        if candidate and candidate[0] in ("outline", "open_outline"):
            return candidate
    return route


def is_canvas_request(message, browser):
    """Let Desktop chat send Canvas work to the browser agent."""
    return _canvas_route(message, browser) is not None


def _canvas_tab(browser, school):
    """Use the focused assignment tab or the only matching tab."""
    if browser.get("playwright") is None:
        browser["playwright"], browser["page"] = open_browser()
    pages = []
    for page in browser["page"].context.pages:
        if page.is_closed():
            continue
        try:
            assignment_path(page.url, school)
        except ValueError:
            continue
        pages.append(page)
    if len(pages) == 1:
        return pages[0].url

    focused = []
    for page in pages:
        try:
            if page.evaluate("document.hasFocus()"):
                focused.append(page)
        except Error:
            continue  # The tab may have closed while we checked it.
    if len(focused) == 1:
        return focused[0].url
    return ""


def _run_canvas_request(route, browser):
    """Find the assignment, then call the Canvas tool for the user."""
    action, arguments = route
    if action == "review_again":
        review = browser["_canvas_review"]
        action = "attach"
        arguments = f"{review['school']}{review['assignment']} | {review['file']}"
    if action == "choose_file":
        return "Ask me to draft the Canvas assignment, or give me the file path in quotes."
    url, separator, extra = arguments.partition("|")
    url = url.strip()
    if not url and action != "submit":
        if action == "status":
            url = browser.get("_canvas_link", "")
        if not url:
            school = os.getenv("CANVAS_URL", "").strip()
            if not school:
                return "Set CANVAS_URL and CANVAS_TOKEN in .env, or paste the assignment link to open it."
            if action != "open" and not os.getenv("CANVAS_TOKEN", "").strip():
                return "Set CANVAS_TOKEN in .env and restart Chexsa to read your Canvas assignment."
            url = _canvas_tab(browser, school)
        if not url:
            return "Open the assignment in Chexsa's Chrome window or paste its Canvas link here."
    arguments = url + (" | " + extra.strip() if separator else "")
    return canvas_command(
        f"{action} {arguments}".strip(),
        browser,
        lambda: check_cancelled(browser),
        lambda link: _open_assignment(browser, link),
    )


def _open_assignment(browser, url):
    """Open the checked Canvas link in the current Chrome session."""
    if browser.get("playwright") is None:
        browser["playwright"], browser["page"] = open_browser()
    elif browser["page"].is_closed():
        browser["page"] = browser["page"].context.new_page()
    check_cancelled(browser)
    browser["page"].goto(url, wait_until="domcontentloaded", timeout=30000)
    check_cancelled(browser)


def _run_browser_task(task, browser, resuming=False):
    """Use saved results for planning, while getting all executable IDs afresh."""
    message, history = task["request"], task["history"]
    # The CLI keeps this dictionary so later requests can reuse the same Chrome tab.
    check_cancelled(browser)
    page = browser.get("page")
    observation = read_page(page) if page is not None and not page.is_closed() else None
    scope = (
        tuple(observation.get(key) for key in ("page_id", "document_id", "url"))
        if observation
        else None
    )
    same_document = task.get("scope") == scope
    if resuming and not same_document:
        task["review_only"] = True
        history.append(
            {
                "action": {"action": "observe"},
                "result": "The saved page/document changed. Earlier progress is historical; inspect only and ask for a new request before sending input.",
            }
        )
    task["scope"] = scope
    last_action = None
    last_observation = None
    # Old snapshots are comparison data only. All action IDs come from the new reading.
    previous = task.get("_observation") if resuming and same_document else None
    task["_observation"] = observation

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
        if task.get("review_only") and action["action"] not in (
            "find_elements",
            "wait_for",
            "observe",
        ):
            task["status"] = "paused"
            return "The previous input outcome is uncertain. Inspection only: no new input was sent. Check the page before starting another request."
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
                if progress.get("observation") is not None:
                    task["_observation"] = progress["observation"]

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
            task["review_only"] = True
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
        task["_observation"] = observation
        task["scope"] = tuple(
            observation.get(key) for key in ("page_id", "document_id", "url")
        )

    task["status"] = "paused"
    return "Stopped after 10 model decisions. The request may be unfinished; please check the page."
