"""Count desktop prompt tokens with fixed replies and a disposable file."""
import argparse
import json
import os
import re
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter
from unittest.mock import Mock, patch

from tokenizers import Tokenizer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import desktop_agent_ as agent
from test_desktop_agent_ import _response


def run_case(case, compact, tokenizer, path):
    """Run the same goal with a full or compact window and check the tool effects."""
    busy = {
        "title": "Test editor",
        "elements": "\n".join(
            [f'[{i}] Edit "Field {i}"' for i in range(1, 181)]
            + ['[181] Button "Apply"']
        ),
        "unavailable_controls": 0,
        "window_id": (1,),
    }
    state = {} if case == "file" else {"window": object()}
    requests = {
        "file": "Create a text file containing Hello.",
        "window": "Confirm the changes.",
        "mixed": "Create a text file containing Hello, then click Apply.",
    }
    totals = {"input": 0, "output": 0, "calls": 0, "searches": 0}
    clicked = []

    def choose(**kwargs):
        """Simulate a model that searches if the needed control is absent."""
        payload = json.loads(kwargs["messages"][-1]["content"])
        if case != "window" and not payload["previous_actions"]:
            name = "write_file"
            args = {"path": str(path), "content": "Hello", "done": case == "file"}
        elif clicked:
            name, args = "reply", {"text": "Verified", "done": True}
        elif '[181] Button "Apply"' in payload["window"]["elements"]:
            name, args = "click_control", {"node_id": [181]}
        else:
            assert any(tool["function"]["name"] == "find_controls" for tool in kwargs["tools"])
            name, args = "find_controls", {"query": "Apply", "offset": 0}
            totals["searches"] += 1

        totals["calls"] += 1
        totals["input"] += sum(
            len(tokenizer.encode(message["content"]).ids) for message in kwargs["messages"]
        )
        totals["input"] += len(tokenizer.encode(json.dumps(kwargs["tools"])).ids)
        totals["output"] += len(tokenizer.encode(json.dumps({"name": name, "arguments": args})).ids)
        return _response(name, args)

    def click(observation, node_id):
        """Check that the executor receives the full window and the intended ID."""
        assert observation is busy and node_id == [181]
        clicked.append(node_id)
        return "Fixture confirmed."

    client = Mock()
    client.chat.completions.create.side_effect = choose
    view = agent._window_view if compact else lambda observation, *_: observation
    with (
        patch.dict(os.environ, {"LLM_MODEL": "fixture"}),
        patch.object(agent, "_client", client),
        patch.object(agent, "_window_view", view),
        patch.object(agent, "_observe", return_value=busy),
        patch.object(agent, "click_control", side_effect=click),
    ):
        answer = agent.run_desktop_agent(requests[case], state)
    if case != "window":
        assert path.read_text(encoding="utf-8") == "Hello"
    if case != "file":
        assert answer == "Verified" and clicked == [[181]]
    return totals


def run_handoff(tokenizer, folder, local):
    """Check the same saved text with and without passing it through the model."""
    from docx import Document

    source, target = folder / "report.docx", folder / "summary.txt"
    body = " ".join(
        f"Finding {i}: the fixture team reviewed the result and saved its notes."
        for i in range(1, 65)
    )
    report = Document()
    report.add_heading("Background", level=1)
    for i in range(100):
        report.add_paragraph(f"Background note {i}. This stays in the source.")
    report.add_heading("Conclusion", level=1)
    report.add_paragraph(body)
    report.add_heading("Appendix", level=1)
    report.add_paragraph("Leave this in the source too.")
    report.save(source)
    before = source.read_bytes()
    target.unlink(missing_ok=True)
    totals = {"input": 0, "output": 0, "calls": 0}

    def choose(**kwargs):
        """Count what reaches the fake model and choose the next tool."""
        messages = kwargs["messages"]
        payload = json.loads(messages[-1]["content"])
        names = {tool["function"]["name"] for tool in kwargs["tools"]}
        if local:
            assert "copy_file_text" in names and body not in messages[-1]["content"]
            name, args = "copy_file_text", {
                "source": "report.docx", "destination": "summary.txt",
                "section": "Conclusion", "done": True,
            }
        elif not payload["previous_actions"]:
            assert "copy_file_text" not in names
            name, args = "read_file_section", {"path": "report.docx", "query": "Conclusion"}
        else:
            excerpt = payload["previous_actions"][-1]["result"]["text"]
            content = excerpt.splitlines()[1]
            assert content == body
            name, args = "write_file", {"path": "summary.txt", "content": content, "done": True}

        totals["calls"] += 1
        totals["input"] += sum(len(tokenizer.encode(message["content"]).ids) for message in messages)
        totals["input"] += len(tokenizer.encode(json.dumps(kwargs["tools"])).ids)
        totals["output"] += len(tokenizer.encode(json.dumps({"name": name, "arguments": args})).ids)
        return _response(name, args)

    client = Mock()
    client.chat.completions.create.side_effect = choose
    request = "Copy the Conclusion from report.docx to summary.txt."
    with (
        patch.dict(os.environ, {"LLM_MODEL": "fixture"}),
        patch.object(agent, "_client", client),
        patch.object(agent.files_, "OUTPUT_DIR", folder),
        patch.object(agent, "_COPY_REQUEST", agent._COPY_REQUEST if local else re.compile(r"(?!)")),
    ):
        start = perf_counter()
        answer = agent.run_desktop_agent(request, {"recent_files": [str(source.resolve())]})
        elapsed = perf_counter() - start

    assert str(target.resolve()) in answer
    assert target.read_text(encoding="utf-8") == body and source.read_bytes() == before
    return {
        "method": "local" if local else "through_model",
        "verified": True,
        **totals,
        "local_seconds": round(elapsed, 4),
    }


def main():
    """Run offline and print counts without recording prompt or file content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=Path, required=True)
    parser.add_argument("--handoff", action="store_true", help="Measure copying a Word section.")
    args = parser.parse_args()
    tokenizer = Tokenizer.from_file(str(args.tokenizer))
    with TemporaryDirectory() as folder:
        if args.handoff:
            for local in (False, True):
                print(json.dumps(run_handoff(tokenizer, Path(folder), local)))
            return
        path = Path(folder) / "example.txt"
        for case in ("file", "window", "mixed"):
            full = run_case(case, False, tokenizer, path)
            path.unlink(missing_ok=True)
            compact = run_case(case, True, tokenizer, path)
            path.unlink(missing_ok=True)
            print(json.dumps({"case": case, "full": full, "compact": compact}))


if __name__ == "__main__":
    main()
