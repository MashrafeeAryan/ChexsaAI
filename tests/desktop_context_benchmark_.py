"""Count desktop prompt tokens with fixed replies and a disposable file."""
import argparse
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
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


def main():
    """Run offline and print counts without recording prompt or file content."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tokenizer", type=Path, required=True)
    tokenizer = Tokenizer.from_file(str(parser.parse_args().tokenizer))
    with TemporaryDirectory() as folder:
        path = Path(folder) / "example.txt"
        for case in ("file", "window", "mixed"):
            full = run_case(case, False, tokenizer, path)
            path.unlink(missing_ok=True)
            compact = run_case(case, True, tokenizer, path)
            path.unlink(missing_ok=True)
            print(json.dumps({"case": case, "full": full, "compact": compact}))


if __name__ == "__main__":
    main()
