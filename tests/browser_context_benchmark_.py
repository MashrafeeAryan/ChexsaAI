"""Compare browser views in isolated Chrome with fixed replies and no API quota."""

import argparse
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
from observations_ import page_context


def smaller_view(current, previous, request, history):
    """Try eight controls, keeping same-name alternatives and existing local search."""
    view = page_context(current, previous, request, history)
    if len(view["elements"].splitlines()) <= 8:
        return view
    view = {**view, "changes": {**view["changes"]}}
    lines = view["elements"].splitlines()
    chosen = lines[:8]
    selected_ids = {int(re.match(r"\[(\d+)\]", line)[1]) for line in chosen}
    labels = {
        (current["controls"][node]["role"], current["controls"][node]["name"])
        for node in selected_ids
    }
    # Names alone are ambiguous. Include alternatives from the existing working view.
    for line in lines[8:]:
        node = int(re.match(r"\[(\d+)\]", line)[1])
        control = current["controls"][node]
        if (control["role"], control["name"]) in labels:
            chosen.append(line)
            selected_ids.add(node)
    view["elements"] = "\n".join(chosen)
    view["omitted_controls"] = len(current["controls"]) - len(chosen)
    for key in ("added_ids", "updated_ids"):
        removed = [node for node in view["changes"][key] if node not in selected_ids]
        view["changes"][key] = [
            node for node in view["changes"][key] if node in selected_ids
        ]
        view["changes"]["omitted_changes"] = {
            **view["changes"]["omitted_changes"],
            "controls": view["changes"]["omitted_changes"]["controls"] + len(removed),
        }
    view["experiment"] = "Smaller view; find_elements searches all current controls."
    return view


def fixture(case, held_out):
    """Generate fake forms. The second layout changes names and distractor order."""
    field = "Destination" if held_out else "Query"
    button = (
        "Confirm" if case == "dialog" else "Send" if case == "duplicate" else "Apply"
    )
    count = 70 if case == "crowded" else 16 if case != "simple" else 1
    numbers = list(range(count))
    if held_out:
        numbers.reverse()
    clutter = "".join(
        f'<button type="button" onclick="window.wrong++">Option {i}</button>'
        for i in numbers
    )
    region = "Review" if case == "duplicate" else "Details"
    duplicate = (
        '<main aria-label="Other"><button onclick="window.wrong++">Send</button></main>'
        if case == "duplicate"
        else ""
    )
    dialog = 'role="dialog"' if case == "duplicate" else ""
    html = f"""<title>Browser context fixture</title>{duplicate}
    <form aria-label="{region}" {dialog} onsubmit="event.preventDefault(); window.submissions++; window.saved=document.querySelector('input').value; document.querySelector('#status').textContent='Saved';">
    {clutter}<label>{field}<input></label><button id="finish">{button}</button>
    </form><p id="status">Waiting</p>
    <script>window.submissions=0; window.wrong=0; window.saved=null;</script>"""
    if case == "dialog":
        html += """<script>document.querySelector('input').addEventListener('input', () => {
            document.querySelector('#finish').remove();
            const dialog=document.createElement('div');
            dialog.setAttribute('role','dialog'); dialog.setAttribute('aria-label','Review');
            const button=document.createElement('button');
            button.textContent='Confirm';
            button.onclick=() => {
                window.submissions++;
                window.saved=document.querySelector('input').value;
                document.querySelector('#status').textContent='Saved';
            };
            dialog.append(button);
            document.body.append(dialog);
        });</script>"""
    return html, field, button, region


def run_case(page, runtime, case, held_out, compact, tokenizer):
    """Count failed attempts and searches while checking the actual saved page state."""
    html, field, button, region = fixture(case, held_out)
    page.goto("about:blank")
    page.set_content(html)
    payloads, replies = [], []
    searches = expansions = 0
    stage = 0
    request = f"Enter Hello in {field}, then choose {button} in {region}."

    def choose(**kwargs):
        """Choose only from visible descriptions, searching when a target is omitted."""
        nonlocal stage, searches, expansions
        payloads.append(kwargs["messages"])
        payload = json.loads(kwargs["messages"][-1]["content"])
        view = payload["page"]
        descriptions = (
            view["elements"] + "\n" + view.get("search", {}).get("elements", "")
        )
        if stage == 2:
            assert (
                "Saved" in view["changes"]["added_text"]
            ), "Fresh completion evidence was absent"
            action = {"action": "reply", "text": "Verified"}
        else:
            role, name = ("textbox", field) if stage == 0 else ("button", button)
            candidates = [
                line
                for line in descriptions.splitlines()
                if f'{role} "{name}"' in line
                and (stage == 0 or case != "duplicate" or 'dialog "Review"' in line)
            ]
            if not candidates:
                searches += 1
                expansions += 1
                action = {
                    "action": "find_elements",
                    "query": "" if case == "omitted" else name,
                    "offset": 0,
                }
            else:
                node = int(re.match(r"\[(\d+)\]", candidates[0])[1])
                action = (
                    {"action": "type", "backend_node_id": node, "text": "Hello"}
                    if stage == 0
                    else {"action": "click", "backend_node_id": node}
                )
                if stage == 1 and case == "replaced":
                    # The model's chosen node becomes detached before input is sent.
                    page.evaluate(
                        "const button=document.querySelector('#finish');button.replaceWith(button.cloneNode(true));"
                    )
                stage += 1
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
    error = None
    policy = smaller_view if compact else page_context
    with (
        patch.dict(os.environ, environment, clear=True),
        patch.object(llm_, "_client", None),
        patch.object(llm_, "OpenAI") as client,
        patch.object(llm_, "page_context", policy),
    ):
        client.return_value.chat.completions.create.side_effect = choose
        try:
            result = agent_.run_agent(request, {"playwright": runtime, "page": page})
            assert result == "Verified"
        except RuntimeError as caught:
            error = str(caught)
    elapsed = perf_counter() - started
    success = page.evaluate("window.saved === 'Hello' && window.submissions === 1")
    wrong = page.evaluate("window.wrong")
    assert wrong == 0
    if case == "dialog":
        assert (
            page.locator('[role="dialog"]').count() == 1
        ), "The dynamic dialog did not open"
    if case == "replaced":
        assert error and not success and page.evaluate("window.submissions") == 0
        assert (
            stage == 2 and replies[-1]["action"] == "click"
        ), "Stop happened before the stale click was tested"
    else:
        assert error is None and success, (case, error)
    metrics = {
        "case": case,
        "held_out": held_out,
        "policy": "small" if compact else "current",
        "success": success,
        "guarded_stop": bool(error),
        "wrong_targets": wrong,
        "duplicate_submissions": max(0, page.evaluate("window.submissions") - 1),
        "calls": len(replies),
        "searches": searches,
        "expansions": expansions,
        "retries": 0,
        "local_seconds": round(elapsed, 4),
    }
    if tokenizer:
        metrics["input_text_tokens"] = sum(
            len(tokenizer.encode(message["content"]).ids)
            for messages in payloads
            for message in messages
        )
        metrics["output_text_tokens"] = sum(
            len(tokenizer.encode(json.dumps(reply)).ids) for reply in replies
        )
    return metrics


def mcp_snapshots(cli_path, tokenizer):
    """Count real MCP snapshots on the same fixtures, separately from task traces.

    Pass the cli.js from an installed @playwright/mcp 0.0.84 package.
    This records observation and tool-schema costs, not live model decisions.
    """
    from queue import Queue
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    import subprocess
    from threading import Thread

    with TemporaryDirectory(prefix="chexsa-mcp-") as folder:
        process = subprocess.Popen(
            ["node", str(cli_path), "--headless", "--browser", "chrome", "--isolated"],
            cwd=folder,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
        messages = Queue()
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=folder)
        )
        Thread(target=server.serve_forever, daemon=True).start()

        def read_responses():
            """A queue gives each protocol request a bounded wait."""
            for line in process.stdout:
                messages.put(json.loads(line))

        Thread(target=read_responses, daemon=True).start()
        number = 0

        def call(method, params):
            """Send one MCP request and reject protocol or tool errors."""
            nonlocal number
            number += 1
            process.stdin.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": number, "method": method, "params": params}
                )
                + "\n"
            )
            process.stdin.flush()
            while True:
                response = messages.get(timeout=40)
                if response.get("id") == number:
                    if "error" in response or response.get("result", {}).get("isError"):
                        raise RuntimeError(str(response))
                    return response["result"]

        try:
            init = call(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "chexsa-fixture", "version": "1"},
                },
            )
            process.stdin.write(
                json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})
                + "\n"
            )
            process.stdin.flush()
            tools = call("tools/list", {})["tools"]
            schemas = len(tokenizer.encode(json.dumps(tools)).ids)
            for case in (
                "simple",
                "crowded",
                "unchanged",
                "omitted",
                "duplicate",
                "dialog",
                "replaced",
            ):
                for held_out in (False, True):
                    html, _, _, _ = fixture(case, held_out)
                    filename = f"{case}-{held_out}.html"
                    (Path(folder) / filename).write_text(html, encoding="utf-8")
                    call(
                        "tools/call",
                        {
                            "name": "browser_navigate",
                            "arguments": {
                                "url": f"http://127.0.0.1:{server.server_port}/{filename}"
                            },
                        },
                    )
                    snapshot = call(
                        "tools/call", {"name": "browser_snapshot", "arguments": {}}
                    )
                    text = "\n".join(
                        item.get("text", "") for item in snapshot.get("content", [])
                    )
                    assert "textbox" in text and "Waiting" in text
                    print(
                        json.dumps(
                            {
                                "baseline": "Playwright MCP",
                                "package_version": json.loads(
                                    (cli_path.parent / "package.json").read_text(
                                        encoding="utf-8"
                                    )
                                )["version"],
                                "server_version": init["serverInfo"]["version"],
                                "case": case,
                                "held_out": held_out,
                                "snapshot_text_tokens": len(tokenizer.encode(text).ids),
                                "tool_schema_text_tokens": schemas,
                            }
                        ),
                        flush=True,
                    )
            call("tools/call", {"name": "browser_close", "arguments": {}})
        finally:
            server.shutdown()
            server.server_close()
            process.terminate()
            process.wait(timeout=10)


def main():
    """Run disposable Chrome workflows and print aggregate-friendly metrics only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument(
        "--mcp-cli",
        type=Path,
        help="Optional installed Playwright MCP cli.js for snapshot-only comparison.",
    )
    args = parser.parse_args()
    if not 1 <= args.repeat <= 20:
        parser.error("Choose 1 to 20 repeats.")
    tokenizer = None
    if args.tokenizer:
        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(args.tokenizer))
    if args.mcp_cli:
        if tokenizer is None:
            parser.error("MCP snapshot counts need --tokenizer.")
        mcp_snapshots(args.mcp_cli.resolve(), tokenizer)
        return
    with (
        TemporaryDirectory(prefix="chexsa-context-") as folder,
        sync_playwright() as runtime,
    ):
        context = runtime.chromium.launch_persistent_context(
            folder, channel="chrome", headless=True
        )
        try:
            page = context.new_page()
            for run in range(args.repeat):
                for case in (
                    "simple",
                    "crowded",
                    "unchanged",
                    "omitted",
                    "duplicate",
                    "dialog",
                    "replaced",
                ):
                    for held_out in (False, True):
                        # Alternate order so one policy does not always get the warm run.
                        for compact in (
                            (False, True) if run % 2 == 0 else (True, False)
                        ):
                            print(
                                json.dumps(
                                    {
                                        "run": run + 1,
                                        **run_case(
                                            page,
                                            runtime,
                                            case,
                                            held_out,
                                            compact,
                                            tokenizer,
                                        ),
                                    }
                                ),
                                flush=True,
                            )
        finally:
            context.close()
            browser_._observations.clear()


if __name__ == "__main__":
    main()
