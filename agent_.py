"""Keep asking what to do next until the request ends or the agent must stop."""

from browser_ import click_node, open_browser, read_page, type_node
from llm_ import get_reply


# Keep one request and its action history together while working in the browser.
def run_agent(message, browser):
    # The CLI keeps this dictionary so later requests can reuse the same Chrome tab.
    page = browser.get("page")
    observation = read_page(page) if page is not None and not page.is_closed() else None
    history = []
    last_action = None
    last_observation = None
    previous = None

    # Each turn can make one model call. This fixed limit prevents endless API calls.
    for step in range(10):
        action = get_reply(message, observation, history, previous)
        if action["action"] == "reply":
            # A reply ends the run: an answer, missing information, or a final report.
            return action["text"]
        if action == last_action and observation == last_observation:
            return "Stopped because the AI repeated an action without a page change. Please check the page."

        if action["action"] in ("navigate", "observe"):
            # Talking to Chexsa alone does not open Chrome.
            if browser.get("playwright") is None:
                browser["playwright"], browser["page"] = open_browser()
            elif browser["page"].is_closed():
                browser["page"] = browser["page"].context.new_page()
            page = browser["page"]

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
        else:
            raise RuntimeError("Unsupported agent action. Nothing was run.")

        history.append({"action": action.copy(), "result": result})
        last_action, last_observation = action.copy(), observation
        # Observe after every action; the next decision gets current nodes and page state.
        previous = observation
        observation = read_page(page)

    return "Stopped after 10 model decisions. The request may be unfinished; please check the page."
