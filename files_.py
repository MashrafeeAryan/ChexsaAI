"""Create text, code, and Word files directly, without opening an editor or running the code."""

import ast
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import os
import re
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
        if target.suffix.lower() == ".docx":
            _check_word_closed(target)
        if check is not None:
            check()
        if target.read_bytes() != before:
            raise RuntimeError("The file changed before saving. Read it again.")
        if check is not None:
            check()
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
    suffix = target.suffix.lower()
    if suffix not in (".txt", ".md", ".py", ".docx"):
        raise ValueError("Choose a .txt, .md, .py, or .docx file.")
    if not isinstance(old, str) or not old or not isinstance(new, str):
        raise ValueError("Give the exact old text and its replacement.")
    before = target.read_bytes()
    if version is not None and sha256(before).hexdigest() != version:
        raise RuntimeError("The file changed since it was read. Read it again.")

    if suffix == ".docx":
        _check_word_closed(target)
        after = _edit_word(before, old, new)
        _replace_file(target, before, after, check)
        return sha256(after).hexdigest()

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


def _check_word_closed(target):
    """Stop when Word's owner file shows that the document may be open."""
    names = ("~$" + target.name, "~$" + target.name[2:])
    if any(target.with_name(name).exists() for name in names):
        raise RuntimeError("Save and close this document in Word before editing it.")


def _edit_word(before, old, new):
    """Edit one plain text span inside a Word run and preserve its formatting."""
    from docx import Document
    from docx.oxml.ns import qn

    if any(char in old or char in new for char in "\r\n"):
        raise ValueError("Edit one Word paragraph at a time.")

    document = Document(BytesIO(before))
    if document.settings.element.find(qn("w:documentProtection")) is not None:
        raise ValueError("This Word document has editing protection.")
    paragraphs = document.paragraphs
    expected = [paragraph.text for paragraph in paragraphs]
    _unique_position("\n".join(expected), old)

    for index, paragraph in enumerate(paragraphs):
        for run in paragraph.runs:
            if old not in run.text:
                continue
            # Replacing a run's text must never delete a picture, field, or other object.
            if any(child.tag not in (qn("w:rPr"), qn("w:t")) for child in run._element):
                raise ValueError("Choose a plain text span in this Word paragraph.")
            run.text = run.text.replace(old, new, 1)
            expected[index] = expected[index].replace(old, new, 1)

            buffer = BytesIO()
            document.save(buffer)
            buffer.seek(0)
            if [paragraph.text for paragraph in Document(buffer).paragraphs] != expected:
                raise RuntimeError("The Word edit could not be verified.")
            return buffer.getvalue()

    raise ValueError("The Word text crosses formatting runs. Edit one run at a time.")


def copy_file_text(source, destination, *, section='', version=None, check=None):
    """Copy saved text into a new text or Word file. Return the verified path."""
    source = Path(source).resolve()
    formats = (".txt", ".md", ".docx")
    if source.suffix.lower() not in formats or Path(destination).suffix.lower() not in formats:
        raise ValueError("Choose .txt, .md, or .docx for the source and the new file.")

    before = source.read_bytes()
    if version is not None and sha256(before).hexdigest() != version:
        raise RuntimeError("The source changed since it was read. Read it again.")
    if source.suffix.lower() == ".docx":
        from docx import Document

        paragraphs = Document(BytesIO(before)).paragraphs
        content = _word_section(paragraphs, section) if section.strip() else "\n".join(
            paragraph.text for paragraph in paragraphs
        )
    else:
        content = before.decode("utf-8-sig")
        if section.strip():
            if source.suffix.lower() != ".md":
                raise ValueError("Named sections need a Word or Markdown heading.")
            lines = content.splitlines()
            content = _heading_text(lines, _markdown_headings(lines), section)

    if source.read_bytes() != before:
        raise RuntimeError("The source changed before copying. Try again.")
    if check is not None:
        check()
    return write_file(destination, content)


def _markdown_headings(lines):
    """Find headings and skip examples inside code blocks."""
    headings = []
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if fence:
            if marker and marker[1].startswith(fence) and not marker[2].strip():
                fence = None
            continue
        if marker:
            fence = marker[1]
            continue
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+)$", line)
        if heading:
            title = re.sub(r"[ \t]+#+[ \t]*$", "", heading[2]).strip()
            headings.append((index, len(heading[1]), title))
    return headings


def _heading_text(lines, headings, section):
    """Return the body below one exact heading, including any subheadings."""
    title = section.strip().casefold()
    matches = [(index, level) for index, level, label in headings if label.casefold() == title]
    if len(matches) != 1:
        raise ValueError("The section must match one heading. Give its exact name.")
    start, level = matches[0]
    end = next((i for i, depth, _ in headings if i > start and depth <= level), len(lines))
    content = "\n".join(lines[start + 1:end]).strip("\n")
    if not content.strip():
        raise ValueError("That section is empty.")
    return content


def _word_section(paragraphs, section):
    """Copy a Word heading's body or one paragraph after a plain label."""
    lines = [paragraph.text for paragraph in paragraphs]
    headings = []
    for index, paragraph in enumerate(paragraphs):
        style = re.fullmatch(r"Heading ([1-9])", paragraph.style.name or "")
        if style:
            headings.append((index, int(style[1]), paragraph.text.strip()))

    title = section.strip().casefold()
    if any(label.casefold() == title for _, _, label in headings):
        return _heading_text(lines, headings, section)

    # Chexsa's own Word files may use a normal paragraph as a heading.
    matches = [index for index, line in enumerate(lines) if line.strip().casefold() == title]
    if len(matches) != 1:
        raise ValueError("Give the exact name of one Word heading or label.")
    heading_rows = {index for index, _, _ in headings}
    for index in range(matches[0] + 1, len(lines)):
        if index in heading_rows:
            break
        if lines[index].strip():
            return lines[index]
    raise ValueError("There is no text after that label.")
