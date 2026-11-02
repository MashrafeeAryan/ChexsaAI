"""Compare local page readings and choose a small view for the AI."""

import re


def validate_action_group(actions, shown_ids):
    """Check the whole group before anything runs.

    Example: two type actions and one final click are allowed.
    A click in the middle is rejected because it could change the next target.
    """
    if not isinstance(actions, list) or not 1 <= len(actions) <= 5:
        raise ValueError("Give between one and five browser actions.")

    used = set()
    for index, action in enumerate(actions):
        if not isinstance(action, dict):
            raise ValueError("Each browser action must be an object.")
        kind = action.get("action")
        keys = (
            {"action", "backend_node_id", "text"}
            if kind == "type"
            else {"action", "backend_node_id"}
        )
        if kind not in ("type", "click") or set(action) != keys:
            raise ValueError("Groups support typing and one final click only.")
        node = action["backend_node_id"]
        if type(node) is not int or node <= 0 or node not in shown_ids or node in used:
            raise ValueError("Use different node IDs from the current reading.")
        if kind == "type" and not isinstance(action["text"], str):
            raise ValueError("Text must be a string.")
        if kind == "click" and index != len(actions) - 1:
            raise ValueError("A click must be the last action in a group.")
        used.add(node)
    return actions


def validate_wait(action, shown_ids):
    """Allow a short wait for page text or a known control's state.

    Example: {"action": "wait_for", "text": "Results ready", "timeout": 3}.
    """
    from math import isfinite

    if not isinstance(action, dict) or action.get("action") != "wait_for":
        raise ValueError("Give a browser wait condition.")
    keys = set(action) - {"timeout"}
    if keys == {"action", "text"}:
        if (
            not isinstance(action["text"], str)
            or not action["text"].strip()
            or len(action["text"]) > 500
        ):
            raise ValueError("Give a short piece of page text to wait for.")
    elif keys == {"action", "backend_node_id", "state"}:
        node = action["backend_node_id"]
        if type(node) is not int or node not in shown_ids:
            raise ValueError("Wait for a node from the current reading.")
        if action["state"] not in ("enabled", "disabled", "checked", "unchecked"):
            raise ValueError("Choose enabled, disabled, checked, or unchecked.")
    else:
        raise ValueError("Wait for text or one known control's state.")
    timeout = action.get("timeout", 3)
    if (
        type(timeout) not in (int, float)
        or not isfinite(timeout)
        or not 0 < timeout <= 5
    ):
        raise ValueError(
            "Browser waits must be greater than zero and at most five seconds."
        )
    return action



# Find added, removed, and changed nodes; a new document starts a fresh view.
def get_changes(previous, current):
    same_page = (
        previous is not None
        and "controls" in previous
        and "text_nodes" in previous
        and all(
            key in previous and key in current and previous[key] == current[key]
            for key in ("page_id", "document_id", "url")
        )
    )

    if not same_page:
        return {
            "full": True,
            "added": list(current["controls"]),
            "updated": [],
            "removed": [],
            "added_text": list(current["text_nodes"].values()),
            "removed_text": [],
        }

    before, after = previous["controls"], current["controls"]
    old_text, new_text = previous["text_nodes"], current["text_nodes"]

    return {
        "full": False,
        "added": [node for node in after if node not in before],
        "updated": [node for node in after if node in before and after[node] != before[node]],
        "removed": [node for node in before if node not in after],
        "added_text": [text for node, text in new_text.items() if old_text.get(node) != text],
        "removed_text": [text for node, text in old_text.items() if new_text.get(node) != text],
    }


# Show useful control state without copying field values into the model request.
def describe_control(control):
    line = control["line"]

    for state, value in control["states"].items():
        if state != "focused":
            line += f" | {state}: {str(value).lower()}"

    return line


def compact_history(request, history):
    """Reference long text already present in the request instead of sending it twice.

    Example: a history entry can use text_from_request=[20, 140].
    Those are character offsets into the original request, which is still sent in full.
    Generated text that is not in the request is preserved. The local history is unchanged.
    """

    def summarize(action):
        """Copy an action description and replace only an exact repeated text span."""
        summary = action.copy()
        if action.get("action") == "batch":
            summary["actions"] = [summarize(item) for item in action["actions"]]
        text = action.get("text")
        if (
            action.get("action") == "type"
            and isinstance(text, str)
            and len(text) >= 160
        ):
            start = request.find(text)
            if start >= 0:
                summary.pop("text")
                summary["text_from_request"] = [start, start + len(text)]
        return summary

    return [{**entry, "action": summarize(entry["action"])} for entry in history]



# Search the complete local control list; offset lets the AI request the next page.
def find_elements(observation, query, offset=0):
    matches = [
        control
        for control in observation["controls"].values()
        if query.casefold() in control["line"].casefold()
    ]

    selected = matches[offset : offset + 40]
    next_offset = offset + len(selected)

    return {
        "query": query,
        "elements": "\n".join(describe_control(control) for control in selected),
        "total_matches": len(matches),
        "next_offset": next_offset if next_offset < len(matches) else None,
    }


# Send changes and a small working view, while the full page stays on this computer.
def page_context(current, previous, request, history):
    if "controls" not in current:
        return {key: current[key] for key in ("url", "title", "elements")}

    changes = get_changes(previous, current)
    controls = current["controls"]
    last_action = history[-1]["action"] if history else {}

    words = set(re.findall(r"[a-z0-9]{3,}", request.lower())) - {
        "the", "and", "for", "with", "then", "open", "please", "chexsa",
    }

    changed = changes["added"] + changes["updated"] if not changes["full"] else []
    focused = [
        node
        for node, control in controls.items()
        if control["states"].get("focused")
    ]
    recent = last_action.get("backend_node_id")
    anchor = controls.get(focused[0]) if focused else controls.get(recent)

    if anchor is None:
        anchor = next(
            (
                control
                for control in controls.values()
                if any(
                    region.startswith(("dialog ", "alertdialog "))
                    for region in control["context"]
                )
            ),
            None,
        )

    region = anchor["context"][0] if anchor and anchor["context"] else None

    # Keep the focused form or dialog ahead of broad matches elsewhere on the page.
    regional = [
        node
        for node, control in controls.items()
        if region and region in control["context"]
    ]
    relevant = [
        node
        for node, control in controls.items()
        if any(word in control["line"].lower() for word in words)
    ]

    # Keep complete entries, never cut a control's description halfway through.
    selected = list(
        dict.fromkeys(
            changed
            + focused
            + ([recent] if recent in controls else [])
            + regional
            + relevant
        )
    )

    if changes["full"]:
        selected = list(dict.fromkeys(selected + list(controls)))

    selected = selected[:40]
    visible_ids = set(selected)

    view = {
        "url": current["url"],
        "title": current["title"],
        "mode": "full" if changes["full"] else "changes",
        "elements": "\n".join(describe_control(controls[node]) for node in selected),
        "control_count": len(controls),
        "omitted_controls": len(controls) - len(selected),
        "changes": {
            "added_ids": [node for node in changes["added"] if node in visible_ids],
            "updated_ids": [node for node in changes["updated"] if node in visible_ids],
            "removed_ids": changes["removed"][:40],
            "added_text": changes["added_text"][:30],
            "removed_text": changes["removed_text"][:30],
            "omitted_changes": {
                "controls": sum(node not in visible_ids for node in changed),
                "removed_controls": max(0, len(changes["removed"]) - 40),
                "added_text": max(0, len(changes["added_text"]) - 30),
                "removed_text": max(0, len(changes["removed_text"]) - 30),
            },
        },
    }

    if last_action.get("action") == "find_elements":
        # Search fresh local data, rather than replaying IDs from an older page.
        view["search"] = find_elements(
            current, last_action["query"], last_action.get("offset", 0)
        )

    return view
