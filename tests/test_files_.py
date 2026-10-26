"""Test real temporary files without models, editors, or code execution."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import files_


# New files preserve their code; code with side effects must never run here.
def test_create_and_preserve():
    with TemporaryDirectory() as directory, patch.object(files_, "OUTPUT_DIR", Path(directory)):
        text = "raise RuntimeError('must not run')\n# Caf\u00e9\n"
        path = Path(files_.write_file("example.py", text))
        assert path == Path(directory).resolve() / "example.py"
        assert path.read_text(encoding="utf-8") == text
        with unittest.TestCase().assertRaises(FileExistsError):
            files_.write_file(str(path), "print('replacement')")
        assert path.read_text(encoding="utf-8") == text


# Bad syntax and non-Python filenames must fail before a file is created.
def test_reject_invalid_files():
    with TemporaryDirectory() as directory:
        for name, content, error in (("bad.py", "def broken(", SyntaxError), ("bad.exe", "pass", ValueError)):
            path = Path(directory) / name
            with unittest.TestCase().assertRaises(error):
                files_.write_file(str(path), content)
            assert not path.exists()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(unittest.FunctionTestCase(test) for test in (
        test_create_and_preserve, test_reject_invalid_files,
    ))
