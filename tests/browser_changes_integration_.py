"""Test large-page changes in isolated Chrome with a fake model and no API usage."""

import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent_
import browser_
import llm_
from observations_ import get_changes, page_context


def main():
    """Runs Chrome on a large test page and checks typing, clicking, page changes, and local search without an AI API."""
    payloads, old_sizes = [], []
    original = agent_.get_reply

    def traced(request, observation=None, history=None, previous=None):
        if observation:
            old_sizes.append(len(json.dumps({"request": request, "previous_actions": history or [],
                "page": {key: observation[key] for key in ("url", "title", "elements")}})))
        return original(request, observation, history, previous)

    # Choose predictable actions so this test never spends real API tokens.
    def choose(**kwargs):
        payload = json.loads(kwargs["messages"][-1]["content"])
        payloads.append(payload)
        history, view = payload["previous_actions"], payload["page"]
        if not history:
            match = re.search(r'^\[(\d+)\] textbox "Subject"', view["elements"], re.M)
            assert match, "The active form was omitted"
            action = {"action": "type", "backend_node_id": int(match.group(1)), "text": "Hello"}
        elif history[-1]["action"]["action"] == "type":
            assert view["mode"] == "changes"
            assert not view["changes"]["added_text"], "Unchanged text was marked as new"
            assert len(view["changes"]["updated_ids"]) <= 2
            match = re.search(r'^\[(\d+)\] button "Continue"', view["elements"], re.M)
            action = {"action": "click", "backend_node_id": int(match.group(1))}
        elif len(history) == 2:
            assert "Ready" in view["changes"]["added_text"]
            assert len(view["changes"]["removed_ids"]) == 2
            assert 'button "Archive 999"' not in view["elements"]
            action = {"action": "find_elements", "query": "Archive 999", "offset": 0}
        elif history[-1]["action"]["action"] == "find_elements":
            assert view["search"]["total_matches"] == 1
            match = re.search(r'^\[(\d+)\] button "Archive 999"', view["search"]["elements"], re.M)
            action = {"action": "click", "backend_node_id": int(match.group(1))}
        else:
            assert "Archived 999" in view["changes"]["added_text"]
            action = {"action": "reply", "text": "Finished"}
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(action)))])

    with TemporaryDirectory(prefix="chexsa-delta-test-") as profile:
        with sync_playwright() as runtime:
            context = runtime.chromium.launch_persistent_context(profile, channel="chrome", headless=True)
            page = context.new_page()
            buttons = "".join(
                f"""<button onclick="window.archived={number};document.querySelector('#status').textContent='Archived {number}'">Archive {number}</button>"""
                for number in range(1000)
            )
            page.set_content('<title>Large inbox fixture</title><main aria-label="Inbox">' + buttons + """</main>
<div id="form" role="dialog" aria-label="New Message"><label>Subject<input id="subject" value="old"></label>
<button onclick="window.saved=document.querySelector('#subject').value;document.querySelector('#form').remove();document.querySelector('#status').textContent='Ready'">Continue</button></div>
<p id="status">Waiting</p><script>window.saved='';window.archived=-1;</script>""")
            environment = {"LLM_API_KEY": "fake-key", "LLM_BASE_URL": "https://example.invalid/v1", "LLM_MODEL": "fake-model"}
            with patch.dict(os.environ, environment, clear=True), patch.object(llm_, "_client", None), patch.object(llm_, "OpenAI") as client, patch.object(agent_, "get_reply", side_effect=traced):
                client.return_value.chat.completions.create.side_effect = choose
                result = agent_.run_agent("Fill Subject with Hello, click Continue, then click Archive 999.", {"playwright": runtime, "page": page})
            assert result == "Finished"
            assert page.evaluate("window.saved") == "Hello"
            assert page.evaluate("window.archived") == 999
            assert len(payloads) == 5
            assert payloads[0]["page"]["mode"] == "full"
            assert all(payload["page"]["mode"] == "changes" for payload in payloads[1:])
            assert all(len(payload["page"]["elements"].splitlines()) <= 40 for payload in payloads)
            new_sizes = [len(json.dumps(payload)) for payload in payloads]
            print("PASS: type, click, discover omitted unchanged control, exact click, finish.")
            print("New user payload sizes (characters):", new_sizes)
            print("Former full-controls payload sizes (characters):", old_sizes)
            before = browser_.read_page(page)
            page.goto("data:text/html,<button>New document</button>")
            after = browser_.read_page(page)
            assert get_changes(before, after)["full"]
            assert page_context(after, before, "Read this", [])["mode"] == "full"
            print("PASS: navigation resets the page view. Zero live API calls.")
            context.close()
    browser_._observations.clear()


if __name__ == "__main__":
    main()
