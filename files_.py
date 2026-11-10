"""Create text, code, and Word files directly, without opening an editor or running the code."""

import ast
from hashlib import sha256
from pathlib import Path
import os
from tempfile import NamedTemporaryFile

OUTPUT_DIR = Path(__file__).resolve().parent / "output"


# Save a new file and read it back; existing files are never overwritten.
def write_file(path, content):
    if not isinstance(path, str) or not path.strip() or not isinstance(content, str):
        raise ValueError("Give a file path and the text to save.")
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = OUTPUT_DIR / target
    target = target.resolve()
    # Word files use a document package; the other supported formats store plain text.
    if target.suffix.lower() not in ("", ".docx", ".py", ".txt", ".md", ".json", ".csv", ".html",
                                     ".css", ".js", ".ts", ".yaml", ".yml", ".xml", ".toml", ".ini", ".log"):
        raise ValueError("Choose a supported text, code, or Word file, such as .txt, .py, or .docx.")
    if target.suffix.lower() == ".py":
        ast.parse(content)  # Check Python syntax without executing anything.
    expected = content.replace("\r\n", "\n").replace("\r", "\n")
    if target.suffix.lower() == ".docx":
        from docx import Document

        document = Document()
        for line in expected.split("\n"):
            document.add_paragraph(line)  # Each line becomes a Word paragraph.
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as file:
            document.save(file)  # Create a real Word package, not renamed text.
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("x", encoding="utf-8", newline="") as file:
            file.write(content)  # x means create only; fail if the file already exists.
    if read_file(target) != expected:
        raise RuntimeError("The saved file could not be verified. Check it before trying again.")
    return str(target)


# Read saved text in the right format so both file creation and completion can verify it.
def read_file(path):
    path = Path(path)
    if path.suffix.lower() == ".docx":
        from docx import Document

        return "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    return path.read_text(encoding="utf-8")


def read_file_section(path, query):
    """Return a small excerpt and its file version. A Python function name selects its body."""
    target = Path(path)
    if target.suffix.lower() not in (".txt", ".md", ".py", ".docx"):
        raise ValueError("Choose a .txt, .md, .py, or .docx file.")
    original = target.read_bytes()
    if target.suffix.lower() == ".docx":
        from io import BytesIO
        from docx import Document

        lines = [paragraph.text for paragraph in Document(BytesIO(original)).paragraphs]
    else:
        lines = original.decode("utf-8-sig").splitlines()

    matches = [i for i, line in enumerate(lines) if query.casefold() in line.casefold()]
    first = matches[0] if matches else 0
    end = min(len(lines), first + (6 if query else 20))
    if query and target.suffix.lower() == ".py":
        try:
            tree = ast.parse(original)
        except SyntaxError:
            tree = None  # Plain text search can still help repair a broken file.
        functions = [
            node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == query
        ] if tree is not None else []
        if len(functions) == 1:
            function = functions[0]
            first = min([function.lineno, *(node.lineno for node in function.decorator_list)]) - 1
            end = function.end_lineno
            matches = [first]

    excerpt = "\n".join(lines[first:end]) if matches or not query else ""
    return {
        "text": excerpt[:6000],
        "first_line": first + 1,
        "matches": len(matches) if query else None,
        "more": len(excerpt) > 6000 or end < len(lines),
        "version": sha256(original).hexdigest(),
    }


def _unique_position(text, old):
    """Find one exact match, including cases where two matches overlap."""
    position = text.find(old)
    if position < 0 or text.find(old, position + 1) >= 0:
        raise ValueError("The old text must match exactly once. Read a more specific section.")
    return position


def _replace_file(target, before, after, check=None):
    """Stage a complete copy, then replace the original after checking its bytes."""
    with NamedTemporaryFile(dir=target.parent, delete=False) as staged:
        temporary = Path(staged.name)
    try:
        temporary.write_bytes(after)
        if temporary.read_bytes() != after:
            raise RuntimeError("Could not verify the staged edit.")
        if check is not None:
            check()
        if target.read_bytes() != before:
            raise RuntimeError("The file changed before saving. Read it again.")
        try:
            os.replace(temporary, target)
        except PermissionError:
            raise RuntimeError("Could not replace the file. Close it or check its permissions.") from None
        if target.read_bytes() != after:
            raise RuntimeError("The saved edit changed before it could be verified.")
    finally:
        temporary.unlink(missing_ok=True)


def edit_file(path, old, new, version=None, check=None):
    """Replace one exact span and return the version of the verified saved file."""
    target = Path(path)
    if target.suffix.lower() not in (".txt", ".md", ".py"):
        raise ValueError("Choose a .txt, .md, or .py file.")
    if not isinstance(old, str) or not old or not isinstance(new, str):
        raise ValueError("Give the exact old text and its replacement.")
    before = target.read_bytes()
    if version is not None and sha256(before).hexdigest() != version:
        raise RuntimeError("The file changed since it was read. Read it again.")

    # Preserve the file's line endings when the model supplies ordinary newlines.
    text = before.decode("utf-8")
    if "\r\n" in text and "\n" not in text.replace("\r\n", ""):
        old = old.replace("\r\n", "\n").replace("\n", "\r\n")
        new = new.replace("\r\n", "\n").replace("\n", "\r\n")
    start = _unique_position(text, old)
    after = (text[:start] + new + text[start + len(old):]).encode("utf-8")
    if target.suffix.lower() == ".py":
        ast.parse(after)
    _replace_file(target, before, after, check)
    return sha256(after).hexdigest()
