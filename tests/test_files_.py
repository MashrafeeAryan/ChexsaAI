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


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_create_and_preserve, test_reject_invalid_files, test_text_formats, test_word_documents,
    ))
