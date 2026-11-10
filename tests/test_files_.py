"""Test real temporary files without models, editors, or code execution."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import files_


def test_create_and_preserve():
    "Checks that new Python files are saved exactly and existing files are not overwritten."
    with TemporaryDirectory() as directory, patch.object(files_, "OUTPUT_DIR", Path(directory)):
        text = "raise RuntimeError('must not run')\n# Caf\u00e9\n"
        path = Path(files_.write_file("example.py", text))
        assert path == Path(directory).resolve() / "example.py"
        assert path.read_text(encoding="utf-8") == text
        with unittest.TestCase().assertRaises(FileExistsError):
            files_.write_file(str(path), "print('replacement')")
        assert path.read_text(encoding="utf-8") == text


def test_reject_invalid_files():
    "Checks that invalid Python code and unsupported file formats are rejected before saving."
    with TemporaryDirectory() as directory:
        for name, content, error in (("bad.py", "def broken(", SyntaxError), ("bad.exe", "pass", ValueError)):
            path = Path(directory) / name
            with unittest.TestCase().assertRaises(error):
                files_.write_file(str(path), content)
            assert not path.exists()


def test_text_formats():
    "Checks text formats, Unicode, line endings, folders, and empty files."
    with TemporaryDirectory() as directory, patch.object(files_, "OUTPUT_DIR", Path(directory)):
        for name, text in (("notes.txt", "Hello Mashrafee\n"), ("docs/readme.md", "# Notes\n"),
                           ("data.json", '{"name": "Caf\u00e9"}'), ("rows.csv", "a,b\r\n1,2\r\n"),
                           ("empty.txt", "")):
            path = Path(files_.write_file(name, text))
            assert path.read_bytes() == text.encode("utf-8")


def test_word_documents():
    "Checks that Word files are valid packages and preserve their text without overwriting existing documents."
    from zipfile import ZipFile
    from docx import Document
    with TemporaryDirectory() as directory, patch.object(files_, "OUTPUT_DIR", Path(directory)):
        for index, content in enumerate(("AI and education\r\n\r\nCaf\u00e9\tand learning.\r\n", "")):
            path = Path(files_.write_file(f"document{index}.docx", content))
            expected = content.replace("\r\n", "\n")
            with ZipFile(path) as package:
                assert package.testzip() is None
                assert "word/document.xml" in package.namelist()
            assert "\n".join(p.text for p in Document(path).paragraphs) == expected
            assert files_.read_file(path) == expected
            before = path.read_bytes()
            with unittest.TestCase().assertRaises(FileExistsError):
                files_.write_file(str(path), "Replacement")
            assert path.read_bytes() == before


def test_read_only_the_requested_section():
    """Find a whole named function and keep large excerpts bounded."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "example.py"
        path.write_text("def fib(n):\n    return n\n\ndef other():\n    return 7\n", encoding="utf-8")
        result = files_.read_file_section(path, "fib")
        assert result["text"] == "def fib(n):\n    return n"
        assert result["matches"] == 1 and result["first_line"] == 1
        assert files_.read_file_section(path, "missing")["text"] == ""

        note = Path(directory) / "note.txt"
        note.write_text("x" * 8000, encoding="utf-8")
        result = files_.read_file_section(note, "")
        assert len(result["text"]) == 6000 and result["more"]


def test_edit_python_checks_version_matches_and_syntax():
    """Edit only the matched code, keeping CRLF and the original on rejection."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "fib.py"
        path.write_bytes(b"# Keep this\r\ndef fib(n):\r\n    return n\r\n")
        section = files_.read_file_section(path, "fib")
        with unittest.TestCase().assertRaises(SyntaxError):
            files_.edit_file(path, "return n", "return (", section["version"])
        assert path.read_bytes() == b"# Keep this\r\ndef fib(n):\r\n    return n\r\n"
        files_.edit_file(path, section["text"], "def fib(n):\n    return max(n, 0)", section["version"])
        assert path.read_bytes() == b"# Keep this\r\ndef fib(n):\r\n    return max(n, 0)\r\n"
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "changed since"):
            files_.edit_file(path, "max(n, 0)", "n", section["version"])

        note = Path(directory) / "note.txt"
        note.write_text("aaa", encoding="utf-8")
        with unittest.TestCase().assertRaisesRegex(ValueError, "exactly once"):
            files_.edit_file(note, "aa", "b")
        assert note.read_text(encoding="utf-8") == "aaa"


def test_word_edit_preserves_formatting_and_checks_locks():
    """Edit one span while keeping styles and tables, and refuse a locked file."""
    from docx import Document

    with TemporaryDirectory() as directory:
        path = Path(directory) / "report.docx"
        document = Document()
        document.add_heading("Conclusion", level=1)
        paragraph = document.add_paragraph("Keep ")
        paragraph.add_run("the longer conclusion").bold = True
        document.add_table(1, 1).cell(0, 0).text = "Keep the table"
        document.save(path)

        section = files_.read_file_section(path, "Conclusion")
        before = path.read_bytes()
        with unittest.TestCase().assertRaisesRegex(ValueError, "crosses formatting"):
            files_.edit_file(path, "Keep the longer conclusion", "Short")
        lock = path.with_name("~$" + path.name[2:])
        lock.touch()
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "Save and close"):
            files_.edit_file(path, "the longer conclusion", "the short conclusion")
        assert path.read_bytes() == before
        lock.unlink()

        files_.edit_file(path, "the longer conclusion", "the short conclusion", section["version"])
        updated = Document(path)
        assert updated.paragraphs[0].style.name == "Heading 1"
        assert updated.paragraphs[1].text == "Keep the short conclusion"
        assert updated.paragraphs[1].runs[1].bold
        assert updated.tables[0].cell(0, 0).text == "Keep the table"


def test_cancelled_or_changed_file_keeps_original_and_cleans_staging():
    """A stop or an outside edit just before save must leave the target alone."""
    with TemporaryDirectory() as directory:
        path = Path(directory) / "note.txt"
        path.write_text("Original", encoding="utf-8")

        def cancel():
            """Simulate Stop at the final save boundary."""
            raise InterruptedError("Stopped")

        with unittest.TestCase().assertRaises(InterruptedError):
            files_.edit_file(path, "Original", "New", check=cancel)
        assert path.read_text(encoding="utf-8") == "Original"
        assert list(Path(directory).iterdir()) == [path]

        def changed():
            """Simulate another editor saving before Chexsa rechecks the file."""
            path.write_text("Changed elsewhere", encoding="utf-8")

        with unittest.TestCase().assertRaisesRegex(RuntimeError, "changed before saving"):
            files_.edit_file(path, "Original", "New", check=changed)
        assert path.read_text(encoding="utf-8") == "Changed elsewhere"
        assert list(Path(directory).iterdir()) == [path]


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_read_only_the_requested_section,
        test_edit_python_checks_version_matches_and_syntax,
        test_word_edit_preserves_formatting_and_checks_locks,
        test_cancelled_or_changed_file_keeps_original_and_cleans_staging,
        test_create_and_preserve, test_reject_invalid_files, test_text_formats, test_word_documents,
    ))
