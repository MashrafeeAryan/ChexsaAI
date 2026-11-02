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


def run_case(page, runtime, name):
    """Run one fixture through the real prompt and executor with scripted model answers."""
    case = CASES[name]
    page.goto(FIXTURE.resolve().as_uri())
    payloads, replies = [], []
    planned = []
    request = f'Fill {case["fields"]} in {name}, then click {case["button"]}.'

    def choose(**kwargs):
        """Capture the complete text sent to the model, then choose a fixture action."""
        payloads.append(kwargs["messages"])
        payload = json.loads(kwargs["messages"][-1]["content"])
        if not planned:
            planned.extend(choose_actions(payload["page"], case))
        if len(replies) < len(planned):
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
    assert page.evaluate("window.saved") == case["saved"]
    assert page.evaluate("window.submissions") == 1
    assert page.evaluate("window.wrongClicks") == 0
    return {
        "case": name,
        "model_calls": len(replies),
        "input_characters": sum(
            len(message["content"]) for messages in payloads for message in messages
        ),
        "local_seconds": round(elapsed, 4),
    }


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
    ):
        page.goto(FIXTURE.resolve().as_uri())
        page.evaluate("mode => window.fixtureMode = mode", mode)
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


def main():
    """Launch an isolated Chrome profile and record the current single-action baseline."""
    with (
        TemporaryDirectory(prefix="chexsa-workflows-") as profile,
        sync_playwright() as runtime,
    ):
        context = runtime.chromium.launch_persistent_context(
            profile, channel="chrome", headless=True
        )
        try:
            page = context.new_page()
            for name in CASES:
                print(json.dumps(run_case(page, runtime, name)))
            check_action_groups(page)
        finally:
            context.close()
            browser_._observations.clear()


if __name__ == "__main__":
    main()
