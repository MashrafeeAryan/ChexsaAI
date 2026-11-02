"""Compare browser decisions on local pages. No account or model API is used."""

import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_
import browser_
import llm_

FIXTURE = Path(__file__).parent / "fixtures" / "browser_workflows_.html"
CASES = {
    "profile": {
        "fields": {
            "Name": "Sam Example",
            "Email": "sam@example.test",
            "Notes": "A short note",
        },
        "button": "Save",
        "region": 'form "Profile"',
        "evidence": "Profile saved",
        "saved": {
            "name": "Sam Example",
            "email": "sam@example.test",
            "notes": "A short note",
        },
    },
    "filters": {
        "fields": {"Search": "research", "Location": "Boston"},
        "button": "Apply filters",
        "region": 'form "Filters"',
        "evidence": "Matching records ready",
        "saved": {"search": "research", "location": "Boston"},
    },
}

# A longer supplied value checks whether completed text is unnecessarily resent.
CASES["long_note"] = {
    **CASES["profile"],
    "fields": {
        **CASES["profile"]["fields"],
        "Notes": "Community projects help people share knowledge and support each other. "
        * 10,
    },
    "saved": {
        **CASES["profile"]["saved"],
        "notes": "Community projects help people share knowledge and support each other. "
        * 10,
    },
}


def choose_actions(view, case):
    """Read fixture IDs from the actual model view, including duplicate-button context."""
    lines = (
        view["elements"] + "\n" + view.get("search", {}).get("elements", "")
    ).splitlines()
    actions = []
    for name, text in case["fields"].items():
        line = next(
            line
            for line in lines
            if f'textbox "{name}"' in line and case["region"] in line
        )
        actions.append(
            {
                "action": "type",
                "backend_node_id": int(re.match(r"\[(\d+)\]", line)[1]),
                "text": text,
            }
        )
    line = next(
        line
        for line in lines
        if f'button "{case["button"]}"' in line and case["region"] in line
    )
    actions.append(
        {"action": "click", "backend_node_id": int(re.match(r"\[(\d+)\]", line)[1])}
    )
    return actions


def run_case(page, runtime, name, grouped=False, tokenizer=None, delay=0):
    """Run one fixture through the real prompt and executor with scripted model answers."""
    case = CASES[name]
    # The same URL keeps path lengths from biasing the old-versus-new token counts.
    page.goto("about:blank")
    page.set_content(FIXTURE.read_text(encoding="utf-8"))
    page.evaluate("delay => window.delay = delay", delay)
    payloads, replies = [], []
    planned = []
    request = f'Fill {case["fields"]} in {name}, then click {case["button"]}.'

    def choose(**kwargs):
        """Capture the complete text sent to the model, then choose a fixture action."""
        payloads.append(kwargs["messages"])
        payload = json.loads(kwargs["messages"][-1]["content"])
        if not planned:
            planned.extend(choose_actions(payload["page"], case))
        if grouped and not replies:
            action = {"action": "batch", "actions": planned}
        elif grouped and delay and len(replies) == 1:
            action = {"action": "wait_for", "text": case["evidence"], "timeout": 2}
        elif not grouped and len(replies) < len(planned):
            action = planned[len(replies)]
        else:
            assert case["evidence"] in page.locator("#status").inner_text()
            action = {"action": "reply", "text": "Fixture verified"}
        replies.append(action)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content=json.dumps(action)))
            ]
        )

    environment = {
        "LLM_API_KEY": "fixture",
        "LLM_BASE_URL": "https://example.invalid/v1",
        "LLM_MODEL": "fixture",
    }
    started = perf_counter()
    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(llm_, "_client", None),
        patch.object(llm_, "OpenAI") as client,
    ):
        client.return_value.chat.completions.create.side_effect = choose
        result = agent_.run_agent(request, {"playwright": runtime, "page": page})
    elapsed = perf_counter() - started
    assert result == "Fixture verified"
    assert len(replies) == (
        3 if grouped and delay else 2 if grouped else len(planned) + 1
    )
    assert page.evaluate("window.saved") == case["saved"]
    assert page.evaluate("window.submissions") == 1
    assert page.evaluate("window.wrongClicks") == 0
    metrics = {
        "case": name,
        "mode": "grouped" if grouped else "single",
        "model_calls": len(replies),
        "input_characters": sum(
            len(message["content"]) for messages in payloads for message in messages
        ),
        "local_seconds": round(elapsed, 4),
    }
    if tokenizer is not None:
        metrics["input_text_tokens"] = sum(
            len(tokenizer.encode(message["content"]).ids)
            for messages in payloads
            for message in messages
        )
        metrics["output_text_tokens"] = sum(
            len(tokenizer.encode(json.dumps(action)).ids) for action in replies
        )
    return metrics


def check_action_groups(page):
    """Exercise real node guards when a page changes between grouped actions."""
    case = CASES["profile"]
    for mode in (
        "normal",
        "reorder",
        "replace",
        "rename",
        "disable",
        "value",
        "dialog",
        "navigate",
        "reparent",
    ):
        page.goto(FIXTURE.resolve().as_uri())
        page.evaluate("mode => window.fixtureMode = mode", mode)
        if mode == "reparent":
            # Same names do not mean the same parent; moving a field must stop the group.
            page.evaluate(
                "document.body.insertAdjacentHTML('beforeend', '<form id=otherProfile aria-label=Profile></form>')"
            )
        before = browser_.read_page(page)
        actions = choose_actions(before, case)
        result = browser_.run_action_group(page, actions, before)
        if mode in ("normal", "reorder"):
            assert len(result["completed"]) == 4, result
            assert result["remaining"] == 0 and not result["error"]
            assert page.evaluate("window.submissions") == 1
            assert page.evaluate("window.saved") == case["saved"]
        elif mode == "navigate":
            # Navigation may interrupt the first field's readback. Never call it verified.
            assert len(result["completed"]) <= 1, result
            assert result["remaining"] >= 3 and result["stopped"]
        else:
            assert len(result["completed"]) == 1, result
            assert result["remaining"] == 3 and result["stopped"]
            if mode != "navigate":
                assert page.evaluate("window.submissions") == 0
        if mode != "navigate":
            assert page.evaluate("window.wrongClicks") == 0

    page.goto(FIXTURE.resolve().as_uri())
    before = browser_.read_page(page)
    actions = choose_actions(before, case)
    browser_.read_page(page)
    try:
        browser_.run_action_group(page, actions, before)
        raise AssertionError("An old observation was accepted")
    except RuntimeError as error:
        assert "old" in str(error)
    assert page.locator("#name").input_value() == ""

    # A replacement after observation must be rejected before even the first field changes.
    before = browser_.read_page(page)
    actions = choose_actions(before, case)
    page.evaluate(
        "const target = document.querySelector('#email'); target.replaceWith(target.cloneNode(true));"
    )
    result = browser_.run_action_group(page, actions, before)
    assert not result["completed"] and result["stopped"]
    assert page.locator("#name").input_value() == ""

    page.goto(FIXTURE.resolve().as_uri())
    page.evaluate("document.querySelector('#email').readOnly = true")
    before = browser_.read_page(page)
    result = browser_.run_action_group(page, choose_actions(before, case), before)
    assert not result["completed"] and result["stopped"]
    assert page.locator("#name").input_value() == ""

    page.goto(FIXTURE.resolve().as_uri())
    before = browser_.read_page(page)

    def cancel_after_first_field():
        """Simulate Stop between grouped actions, after one field was filled."""
        if page.locator("#name").input_value():
            raise InterruptedError("Fixture cancelled after first field")

    try:
        browser_.run_action_group(
            page, choose_actions(before, case), before, cancel_after_first_field
        )
        raise AssertionError("Mid-group cancellation was ignored")
    except InterruptedError:
        pass
    assert (
        page.locator("#email").input_value() == ""
        and page.evaluate("window.submissions") == 0
    )

    # The same typing tool also supports message editors built with contenteditable.
    page.goto(FIXTURE.resolve().as_uri())
    page.evaluate("""() => {
        const editor = document.createElement('div');
        editor.id = 'notes'; editor.contentEditable = 'true';
        editor.setAttribute('role', 'textbox'); editor.setAttribute('aria-label', 'Notes');
        document.querySelector('#notes').replaceWith(editor);
    }""")
    before = browser_.read_page(page)
    actions = choose_actions(before, case)[:-1]
    result = browser_.run_action_group(page, actions, before)
    assert len(result["completed"]) == 3 and not result["stopped"], result
    assert page.locator("#notes").inner_text() == case["fields"]["Notes"]

    page.goto(FIXTURE.resolve().as_uri())
    before = browser_.read_page(page)
    with patch.object(
        browser_, "click_node", side_effect=RuntimeError("uncertain click")
    ) as click:
        result = browser_.run_action_group(page, choose_actions(before, case), before)
        assert result["error"] == "uncertain click"
        assert len(result["completed"]) == 3 and result["remaining"] == 1
        assert click.call_count == 1 and page.evaluate("window.submissions") == 0
    print(
        "PASS: duplicate buttons, reordered/replaced/changed nodes, navigation, modal, stale reading, uncertain action."
    )


def check_local_waits(page):
    """Check delayed text, state changes, timeouts, replaced targets, and cancellation."""
    page.goto(FIXTURE.resolve().as_uri())
    before = browser_.read_page(page)
    page.evaluate(
        "setTimeout(() => document.querySelector('#status').textContent = 'Delayed result ready', 150)"
    )
    result = browser_.wait_for_page(
        page,
        {"action": "wait_for", "text": "Delayed result ready", "timeout": 1},
        before,
    )
    assert result["matched"] and not result["reason"]

    page.evaluate("document.querySelector('#email').disabled = true")
    before = browser_.read_page(page)
    email = next(
        node
        for node, control in before["controls"].items()
        if control["name"] == "Email"
    )
    page.evaluate(
        "setTimeout(() => document.querySelector('#email').disabled = false, 150)"
    )
    result = browser_.wait_for_page(
        page,
        {
            "action": "wait_for",
            "backend_node_id": email,
            "state": "enabled",
            "timeout": 1,
        },
        before,
    )
    assert result["matched"] and not result["reason"]

    before = result["observation"]
    page.evaluate(
        "setTimeout(() => {const node = document.querySelector('#email'); node.replaceWith(node.cloneNode(true));}, 100)"
    )
    result = browser_.wait_for_page(
        page,
        {
            "action": "wait_for",
            "backend_node_id": email,
            "state": "disabled",
            "timeout": 1,
        },
        before,
    )
    assert not result["matched"] and "disappeared" in result["reason"]

    result = browser_.wait_for_page(
        page,
        {"action": "wait_for", "text": "Never appears", "timeout": 0.15},
        result["observation"],
    )
    assert not result["matched"] and "Timed out" in result["reason"]

    def cancel():
        """Pretend Stop was pressed; waiting must end without another action."""
        raise InterruptedError("Fixture cancelled")

    try:
        browser_.wait_for_page(
            page,
            {"action": "wait_for", "text": "Never appears"},
            result["observation"],
            cancel,
        )
        raise AssertionError("Cancellation was ignored")
    except InterruptedError:
        pass
    print(
        "PASS: local delayed-text/state waits, timeout, replaced target, cancellation."
    )


def main():
    """Check workflows and optionally count text tokens using a local tokenizer JSON."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--single-only",
        action="store_true",
        help="Run just single actions, including when checking an archived baseline.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Repeat each workflow to check stable behavior.",
    )
    parser.add_argument(
        "--tokenizer",
        type=Path,
        help="Optional local tokenizer.json; no model API is called.",
    )
    args = parser.parse_args()
    if not 1 <= args.repeat <= 30:
        parser.error("Choose between 1 and 30 repeats.")
    tokenizer = None
    if args.tokenizer:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(args.tokenizer))
    with (
        TemporaryDirectory(prefix="chexsa-workflows-") as profile,
        sync_playwright() as runtime,
    ):
        context = runtime.chromium.launch_persistent_context(
            profile, channel="chrome", headless=True
        )
        try:
            page = context.new_page()
            for iteration in range(args.repeat):
                for name in CASES:
                    for grouped in ((False,) if args.single_only else (False, True)):
                        print(
                            json.dumps(
                                {
                                    "run": iteration + 1,
                                    **run_case(page, runtime, name, grouped, tokenizer),
                                }
                            ),
                            flush=True,
                        )
            if not args.single_only:
                check_action_groups(page)
                check_local_waits(page)
                delayed = run_case(page, runtime, "filters", grouped=True, delay=400)
                assert delayed["model_calls"] == 3
                print(
                    "PASS: delayed search/filter outcome uses one local wait decision."
                )
        finally:
            context.close()
            browser_._observations.clear()


if __name__ == "__main__":
    main()
