"""Create Python files directly, without opening an editor or running the code."""

import ast
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


# Save a new Python file and read it back; existing files are never overwritten.
def write_file(path, content):
    if not isinstance(path, str) or not path.strip() or not isinstance(content, str):
        raise ValueError("Give a file path and Python code as text.")
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = OUTPUT_DIR / target
    target = target.resolve()
    if target.suffix.lower() != ".py":
        raise ValueError("Choose a Python filename ending in .py.")
    ast.parse(content)  # Check Python syntax without executing anything.
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8", newline="") as file:
        file.write(content)  # x means create only; fail if the file already exists.
    if target.read_text(encoding="utf-8") != content.replace("\r\n", "\n").replace("\r", "\n"):
        raise RuntimeError("The saved file could not be verified. Check it before trying again.")
    return str(target)
