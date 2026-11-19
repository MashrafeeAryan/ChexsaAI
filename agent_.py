"""Keep asking what to do next until the request ends or the agent must stop."""

import os
from pathlib import Path
import re
from urllib.parse import urlsplit

from playwright.sync_api import Error

from plugins.canvas_ import assignment_path, canvas_command, canvas_intent

from browser_ import (
    click_node,
    inspect_control,
    list_tabs,
    select_tab,
    select_option,
    selected_page_text,
    set_checked,
    open_browser,
    read_page,
    read_options,
    scroll_page,
    scroll_region,
    type_node,
    upload_file,
    run_action_group,
    wait_for_page,
)
from llm_ import choose_engine, get_reply
from observations_ import find_page_text, page_outline
from files_ import write_file
from app_runtime_ import (
    check_cancelled,
    delete_browser_checkpoint,
    list_browser_checkpoints,
    read_browser_checkpoint,
    save_browser_checkpoint,
)
from task_metrics_ import measure_task, record_outcome, time_step


def run_auto_agent(message, state, browser, desktop):
    """Choose an existing engine and keep that engine's objects in its own state."""
    from desktop_agent_ import run_desktop_agent

    with measure_task(state):
        check_cancelled(state)
        saved = browser.get("_browser_task", {})
        resuming = message.strip().casefold() in ("continue", "resume", "/continue", "/resume")
        first_word = message.strip().casefold().split(maxsplit=1)[:1]
        is_checkpoint = first_word in (["/checkpoint"], ["/restore"], ["/forget_task"], ["/remember"], ["/tasks"])
        if is_checkpoint or (resuming and saved.get("status") == "paused"):
            choice = {"mode": "browser"}
        else:
            choice = choose_engine(message)
        check_cancelled(state)
        state["engine"] = choice.get("mode")
        if "reply" in choice:
            return choice["reply"]
        if choice["mode"] == "browser":
            browser["_cancel"] = state.get("_cancel")
            previous = browser.get("_browser_task")
            previous_count = len(previous.get("history", [])) if previous else 0
            answer = run_agent(message, browser)
            # Pass only exports from this request, not files from an earlier task.
            task = browser.get("_browser_task") or {}
            start = previous_count if task is previous else 0
            paths = [
                item["result"]["saved_path"]
                for item in task.get("history", [])[start:]
                if item["action"]["action"] == "save_capture"
                and isinstance(item["result"], dict) and item["result"].get("verified") is True
            ]
            if paths:
                desktop["recent_files"] = list(dict.fromkeys(paths))
            return answer
        desktop["_cancel"] = state.get("_cancel")
        return run_desktop_agent(message, desktop)


def _save_checkpoint(task, browser):
    """Keep what was verified or sent, without storing live browser IDs."""
    actions = dict(task.get("saved_progress", {}))
    for entry in task["history"]:
        kind = entry["action"]["action"]
        result = entry["result"]
        if kind in ("type", "set_checked", "select_option", "upload_file", "click"):
            if result != "Not completed.":
                actions[kind] = actions.get(kind, 0) + 1
        elif kind == "batch" and isinstance(result, dict):
            actions["group_actions"] = actions.get("group_actions", 0) + result.get("completed", 0)

    reading = task.get("_observation") or {}
    record = {
        "request": task["request"],
        "url": reading.get("url", task.get("saved_url", "")),
        "status": task["status"],
        "progress": actions,
        "pending": bool(task.get("in_flight") or task.get("review_only")),
    }
    task["checkpoint_id"] = save_browser_checkpoint(
        record, browser.get("_checkpoint_path"), task.get("checkpoint_id")
    )
    return task["checkpoint_id"]


def _save_if_enabled(task, browser):
    """Update a task only after the user has enabled its disk checkpoint."""
    if task.get("checkpoint_id"):
        _save_checkpoint(task, browser)


def _restore_checkpoint(task_id, browser):
    """Find the saved tab and start a new, inspection-only browser reading."""
    record = read_browser_checkpoint(task_id, browser.get("_checkpoint_path"))
    url = record["url"]
    if not url:
        return "This checkpoint has no saved page to inspect."
    if browser.get("playwright") is None:
        browser["playwright"], browser["page"] = open_browser()

    check_cancelled(browser)
    pages = [
        page for page in browser["page"].context.pages
        if not page.is_closed() and page.url == url
    ]
    if len(pages) != 1:
        return "Open one tab at the saved page in Chexsa's browser, then restore again."

    page = browser["page"] = pages[0]
    observation = read_page(page)
    if observation["url"] != url:
        return "The saved page changed while opening. Restore again after checking the tab."
    task = {
        "request": record["request"],
        "status": "paused",
        "review_only": True,
        "in_flight": None,
        "_observation": observation,
        "scope": tuple(observation.get(key) for key in ("page_id", "document_id", "url")),
        "checkpoint_id": task_id,
        "saved_progress": record["progress"],
        "history": [{
            "action": {"action": "observe"},
            "result": {
                "note": "Saved history is historical. Inspect fresh evidence only.",
                "saved_status": record["status"],
                "saved_action_counts": record["progress"],
                "prior_input_may_have_been_sent": record["pending"],
            },
        }],
    }
    browser["_browser_task"] = task
    return "Saved browser task restored for inspection. Enter /continue to check the current page."


# Keep one request and its action history together while working in the browser.
def run_agent(message, browser):
    """Run one browser request and keep its local model call count."""
    with measure_task(browser, share=True):
        return _run_request(message, browser)


def _run_request(message, browser):
    """Start a request, or continue its saved progress using a new page reading.

    Example: after Stop, enter 'continue' in the same browser session.
    The checkpoint lives only in memory; closing Chexsa clears it.
    """
    check_cancelled(browser)
    parts = message.strip().split(maxsplit=1)
    remember = bool(parts and parts[0].casefold() == "/remember")
    if remember:
        if len(parts) != 2:
            return "Enter /remember followed by a browser request."
        message = parts[1]
    if parts and parts[0].casefold() == "/tasks":
        tasks = list_browser_checkpoints(browser.get("_checkpoint_path"))
        return "\n".join(f"{task_id} {status}" for task_id, status in tasks) or "No saved browser tasks."
    if parts and parts[0].casefold() == "/checkpoint":
        task = browser.get("_browser_task")
        if task is None:
            return "There is no browser task to save."
        task_id = _save_checkpoint(task, browser)
        return f"Saved local browser checkpoint {task_id}."
    if parts and parts[0].casefold() == "/forget_task":
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}", parts[1]):
            return "Enter /forget_task followed by the checkpoint ID."
        task = browser.get("_browser_task")
        if task and task.get("checkpoint_id") == parts[1]:
            task.pop("checkpoint_id", None)
        deleted = delete_browser_checkpoint(parts[1], browser.get("_checkpoint_path"))
        return "Saved checkpoint deleted." if deleted else "No saved browser task has that ID."
    if parts and parts[0].casefold() == "/restore":
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{32}", parts[1]):
            return "Enter /restore followed by the saved browser checkpoint ID."
        return _restore_checkpoint(parts[1], browser)
    if parts and parts[0].casefold() == "/canvas":
        return canvas_command(
            parts[1] if len(parts) > 1 else "",
            browser,
            lambda: check_cancelled(browser),
            lambda url: _open_assignment(browser, url),
        )
    route = None if remember else _canvas_route(message, browser)
    if route is not None:
        return _run_canvas_request(route, browser)
    command = message.strip().casefold()
    saved = browser.get("_browser_task")
    resuming = not remember and (
        command in ("/continue", "/resume")
        or (command in ("continue", "resume") and saved is not None and saved["status"] != "finished")
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
        if remember:
            _save_checkpoint(task, browser)

    if resuming and (browser.get("page") is None or browser["page"].is_closed()):
        return "The saved browser tab is closed. Start a new request; old targets will not be reused."
    task["status"] = "running"
    try:
        answer = _run_browser_task(task, browser, resuming)
        if remember:
            return f"{answer}\nCheckpoint: {task['checkpoint_id']}"
        return answer
    except (Exception, KeyboardInterrupt):
        # Keep progress, but let the CLI or app display the original error or Stop.
        task["status"] = "paused"
        raise
    finally:
        # Limits and repeated-action stops must protect prior input too.
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
            # A pause is useful for recovery, but it does not verify completion.
            record_outcome("uncertain" if task["review_only"] else "paused")
            # A failed write must leave the last durable intent available.
            try:
                _save_if_enabled(task, browser)
            except Exception as error:
                raise RuntimeError("Could not update the local task checkpoint. Check its previous state.") from error


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


def _capture_text(task, text):
    """Keep a bounded string locally and return only a short handle to the model."""
    if not text.strip():
        return {"reason": "No readable text was found."}
    if len(text) > 200_000:
        return {"reason": "The text is too large. Choose a smaller selection."}
    artifacts = task.setdefault("artifacts", {})
    if len(artifacts) >= 3:
        return {"reason": "This task already holds three text captures."}
    number = len(artifacts) + 1
    artifacts[number] = text
    return {"capture": number, "characters": len(text)}


def _save_capture(task, action):
    """Save existing captured text in a new file and verify it through the file tool."""
    text = task.get("artifacts", {}).get(action["capture"])
    if text is None:
        raise RuntimeError("Capture the text in this task before saving it.")
    target = Path(action["path"])
    if target.suffix.lower() not in (".txt", ".md", ".docx"):
        raise RuntimeError("Save captured text to a .txt, .md, or .docx file.")
    parts = target.parts[1:] if target.is_absolute() else target.parts
    if target.is_reserved() or any(":" in part for part in parts):
        raise RuntimeError("Use the name of a regular text or Word document.")
    if target.is_absolute():
        if (
            len(target.drive) != 2 or target.drive[1] != ":"
            or action["path"] not in re.findall(r'"([^"]+)"', task["request"])
        ):
            raise RuntimeError("Give the full destination path in double quotes, or use a filename.")
    elif len(target.parts) != 1 or target.drive:
        raise RuntimeError("Use one filename in Chexsa's output folder.")
    try:
        path = write_file(str(target), text)
    except FileExistsError:
        raise RuntimeError("That file already exists. Choose a new filename.") from None
    return {"saved_path": path, "verified": True}


def _attachment_path(request, page_url, name):
    """Limit file attachments to a quoted path and a site named by the user."""
    def origin(url):
        """Ignore query, path, and fragment when comparing the allowed site."""
        try:
            address = urlsplit(url)
            if address.scheme in ("http", "https") and address.hostname:
                return (
                    address.scheme,
                    address.hostname,
                    address.port or (443 if address.scheme == "https" else 80),
                )
        except ValueError:
            pass
        return None

    current = origin(page_url)
    links = re.findall(r'https?://[^\s"<>]+', request)
    if current is None or not any(origin(url.rstrip(".,)")) == current for url in links):
        raise RuntimeError("Name the attachment's destination with a full web address.")
    if not any(match == name for match in re.findall(r'"([^"]+)"', request)):
        raise RuntimeError("Give the local file's full path in double quotes.")

    path = Path(name)
    if not path.is_absolute() or len(path.drive) != 2 or path.drive[1] != ":":
        raise RuntimeError("Use an absolute path on a local drive.")
    if path.is_reserved() or any(":" in part for part in path.parts[1:]):
        raise RuntimeError("Use a regular local file.")
    resolved = path.resolve(strict=True)
    if resolved != path or not resolved.is_file():
        raise RuntimeError("Use the full path of a regular file without redirects.")
    return resolved


@time_step("action")
def _navigate(page, action):
    """Navigate within the selected tab and report whether history was available."""
    kind = action["action"]
    options = {"wait_until": "domcontentloaded", "timeout": 30000}
    if kind == "navigate":
        page.goto(action["url"], **options)
        return "Navigation finished."
    move = page.go_back if kind == "go_back" else page.go_forward
    old_url = page.url
    response = move(**options)
    moved = response is not None or page.url != old_url
    return "History navigation finished." if moved else "No URL change observed. Read the current page."


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
    listed_tabs = {}
    # Old snapshots are comparison data only. All action IDs come from the new reading.
    previous = task.get("_observation") if resuming and same_document else None
    task["_observation"] = observation
    _save_if_enabled(task, browser)

    # Each turn can make one model call. This fixed limit prevents endless API calls.
    for step in range(10):
        check_cancelled(browser)
        used = task.get("decisions_used", 0)
        if used >= 40:
            task["status"] = "paused"
            return "This task reached its total model decision limit. Check the page before starting another request."
        task["decisions_used"] = used + 1
        action = get_reply(message, observation, history, previous)
        # Stop may have been pressed while the model was replying.
        check_cancelled(browser)
        if action["action"] not in ("switch_tab", "list_tabs"):
            listed_tabs = {}
        if action["action"] == "reply":
            # A reply ends the run: an answer, missing information, or a final report.
            task["status"] = "finished"
            _save_if_enabled(task, browser)
            return action["text"]
        if task.get("review_only") and action["action"] not in (
            "find_elements",
            "discover",
            "find_text",
            "inspect_region",
            "outline",
            "list_tabs",
            "read_options",
            "inspect_control",
            "capture_page_text",
            "capture_selection",
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
        if action["action"] in ("click", "type", "set_checked", "select_option", "upload_file"):
            task["in_flight"] = action.copy()
            _save_if_enabled(task, browser)
        # Any action error leaves this function immediately. Uncertain actions are not retried.
        if action["action"] == "observe":
            result = "Browser connected; current page will be read."
        elif action["action"] == "discover":
            result = "See the requested group's tool descriptions in the next decision."
        elif action["action"] in ("find_elements", "find_text", "inspect_region"):
            result = "Local search requested; fresh matches are supplied with the next observation."
        elif action["action"] in ("navigate", "go_back", "go_forward"):
            result = _navigate(page, action)
        elif action["action"] == "outline":
            result = page_outline(observation, action["offset"])
        elif action["action"] == "list_tabs":
            tabs, listed_tabs = list_tabs(page)
            result = {"tabs": tabs}
        elif action["action"] == "switch_tab":
            page = select_tab(listed_tabs, action["tab"])
            browser["page"] = page
            listed_tabs = {}
            result = "Selected the listed tab. Read its current page."
        elif action["action"] == "save_capture":
            result = _save_capture(task, action)
        elif action["action"] == "capture_page_text":
            result = _capture_text(task, observation.get("content", ""))
        elif action["action"] == "capture_selection":
            result = _capture_text(task, selected_page_text(page))
        elif action["action"] == "inspect_control":
            result = inspect_control(page, observation, action["backend_node_id"])
        elif action["action"] == "read_options":
            result = read_options(page, action["backend_node_id"], action.get("offset", 0))
        elif action["action"] == "scroll":
            if "backend_node_id" in action:
                moved = scroll_region(page, action["backend_node_id"], action["direction"])
            else:
                moved = scroll_page(page, action["direction"])
            result = {"moved": moved}
        elif action["action"] == "click":
            click_node(page, action["backend_node_id"])
            result = "Click sent. Check the new observation for its outcome."
        elif action["action"] == "upload_file":
            path = _attachment_path(message, page.url, action["path"])
            result = upload_file(page, action["backend_node_id"], path)
        elif action["action"] == "select_option":
            select_option(page, action["backend_node_id"], action["label"])
            result = {"option": action["label"], "verified": True}
        elif action["action"] == "set_checked":
            next_observation = set_checked(
                page, observation, action["backend_node_id"], action["checked"]
            )
            result = {"checked": action["checked"], "verified": True}
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
                _save_if_enabled(task, browser)

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
        if action["action"] == "find_text":
            entry["result"] = {
                "source": observation["url"],
                **find_page_text(observation, action["query"], action.get("offset", 0)),
            }
        task["_observation"] = observation
        task["scope"] = tuple(
            observation.get(key) for key in ("page_id", "document_id", "url")
        )
        _save_if_enabled(task, browser)

    task["status"] = "paused"
    return "Stopped after 10 model decisions. The request may be unfinished; please check the page."
