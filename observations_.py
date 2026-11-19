"""Compare local page readings and choose a small view for the AI."""

import json
import re


def control_details(target, role, name, state, actions):
    """Give either engine the same small description of one control.

    Include state flags and supported operation names. Field values stay local.
    """
    return {
        "target": list(target) if isinstance(target, tuple) else target,
        "role": role.lower(),
        "name": name[:240],
        "state": {
            key: value for key, value in state.items()
            if type(value) is bool or value == "mixed"
        },
        "actions": list(actions),
    }


def shown_control_ids(text, *, browser=False):
    """Read target IDs from the leading label on each displayed control line.

    Example: '[12] button "Save"' gives 12 in Chrome or (12,) in Windows.
    Descriptions and their text cannot create targets on their own.
    """
    ids = set()
    for line in text.split("\n"):
        prefix, marker, _ = line.partition("] ")
        if not marker or not prefix.startswith("["):
            continue
        try:
            parts = json.loads(prefix + "]")
        except (ValueError, RecursionError):
            continue
        if not parts or any(type(part) is not int for part in parts):
            continue
        if browser:
            if len(parts) == 1 and parts[0] > 0:
                ids.add(parts[0])
        else:
            ids.add(tuple(parts))
    return ids


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
        keys = {"action", "backend_node_id"}
        if kind == "type":
            keys.add("text")
        elif kind == "set_checked":
            keys.add("checked")
        if kind not in ("type", "set_checked", "click") or set(action) != keys:
            raise ValueError("Groups support typing, checkbox changes, and one final click.")
        node = action["backend_node_id"]
        if type(node) is not int or node <= 0 or node not in shown_ids or node in used:
            raise ValueError("Use different node IDs from the current reading.")
        if kind == "type" and not isinstance(action["text"], str):
            raise ValueError("Text must be a string.")
        if kind == "set_checked" and type(action["checked"]) is not bool:
            raise ValueError("Choose true or false for each checkbox.")
        if kind == "click" and index != len(actions) - 1:
            raise ValueError("A click must be the last action in a group.")
        used.add(node)
    return actions


def validate_wait(action, shown_ids):
    """Allow a short wait for page text or a known control's state.

    Example: {"action": "wait_for", "text": "Results ready", "timeout": 3}.
    """
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
        if type(node) is not int or node <= 0 or node not in shown_ids:
            raise ValueError("Wait for a node from the current reading.")
        if action["state"] not in ("enabled", "disabled", "checked", "unchecked"):
            raise ValueError("Choose enabled, disabled, checked, or unchecked.")
    else:
        raise ValueError("Wait for text or one known control's state.")
    timeout = action.get("timeout", 3)
    if type(timeout) not in (int, float) or not 0 < timeout <= 5:
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
    Partial groups describe completed actions only. Unsent generated text is kept
    in remaining_generated; supplied values are still in the request.
    The local history is unchanged.
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

    compact = []
    for index, entry in enumerate(history):
        action = entry["action"]
        # Old searches and menus help discovery, but they contain no completed work.
        if index < len(history) - 1 and action.get("action") in (
            "discover", "find_elements", "inspect_region", "list_tabs",
        ):
            continue
        summary = {**entry, "action": summarize(action)}
        action, result = entry["action"], entry["result"]
        if action.get("action") == "batch" and isinstance(result, dict):
            completed = result.get("completed")
            if type(completed) is int and 0 <= completed < len(action["actions"]):
                # Unsent supplied values are still in the request; they are not progress.
                summary["action"]["actions"] = summary["action"]["actions"][:completed]
                generated = [
                    summarize(item)
                    for item in action["actions"][completed:]
                    if item.get("action") == "type" and item["text"] not in request
                ]
                # New generated text may exist only in the plan, so keep it for recovery.
                if generated:
                    summary["remaining_generated"] = generated
        compact.append(summary)
    return compact



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


def inspect_region(observation, anchor_id, offset=0):
    """Show controls in the anchor's real form or dialog.

    Example: inspect an observed Send button to see the fields beside it.
    The nearest region ID keeps two forms with the same label separate.
    """
    controls = observation.get("controls", {})
    anchor = controls.get(anchor_id)
    region_id = anchor.get("region_id") if anchor else None
    matches = (
        [control for control in controls.values() if control.get("region_id") == region_id]
        if region_id is not None else ([anchor] if anchor else [])
    )
    selected = matches[offset:offset + 40]
    end = offset + len(selected)
    return {
        "query": f"Region of [{anchor_id}]",
        "elements": "\n".join(describe_control(control) for control in selected),
        "total_matches": len(matches),
        "next_offset": end if end < len(matches) else None,
    }


def find_page_text(observation, query, offset=0):
    """Find readable text in a page without adding new action targets.

    Example: search 'receipt' to find a confirmation beyond the first view.
    """
    needle = query.lower()
    matches = []
    for text in observation.get("text_nodes", {}).values():
        position = text.lower().find(needle)
        if position >= 0:
            matches.append((text, position))

    selected = matches[offset:offset + 12]
    excerpts = []
    for text, position in selected:
        left = max(0, position - 120)
        right = min(len(text), left + 400)
        excerpt = text[left:right]
        excerpts.append(("..." if left else "") + excerpt + ("..." if right < len(text) else ""))

    end = offset + len(selected)
    return {
        "matches": excerpts,
        "total_matches": len(matches),
        "next_offset": end if end < len(matches) else None,
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

    region = anchor.get("region_id") if anchor else None
    label = anchor["context"][0] if anchor and anchor["context"] else None

    # Prefer the actual region identity. A name can be shared by two dialogs.
    regional = [
        node
        for node, control in controls.items()
        if (
            control.get("region_id") == region
            if region is not None
            else label and label in control["context"]
        )
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

    if last_action.get("action") == "inspect_region":
        view["search"] = inspect_region(
            current, last_action["backend_node_id"], last_action.get("offset", 0)
        )
    return view
