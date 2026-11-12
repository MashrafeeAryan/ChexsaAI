"""Exercise Canvas with fixture accounts and no network requests."""

from unittest import FunctionTestCase, TestSuite, TestCase

from plugins import canvas_ as canvas


def test_assignment_link():
    """A token should only go to the school the user set."""
    school = "https://school.example"
    assert canvas.assignment_path(school + "/courses/3/assignments/9?view=1", school) == "/courses/3/assignments/9"
    for url in (
        "https://other.example/courses/3/assignments/9",
        "https://user@school.example/courses/3/assignments/9",
        school + "/courses/3/quizzes/9",
        "http://school.example/courses/3/assignments/9",
    ):
        with TestCase().assertRaises(ValueError):
            canvas.assignment_path(url, school)



def test_read_assignment_and_refuse_redirect():
    """Read the right assignment without following a login or other redirect."""
    import httpx

    path = "/courses/3/assignments/9"
    school = "https://school.example"
    requests = []

    def reply(request):
        requests.append(request)
        assert request.headers["Authorization"] == "Bearer fixture"
        if len(requests) == 1:
            return httpx.Response(200, json={"id": 9, "name": "Practice", "description": "<p>Write a note.</p><p>Two lines.</p>"})
        return httpx.Response(302, headers={"Location": "https://other.example/"})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        details = canvas.assignment_details(client, school, "fixture", path)
        assert canvas.assignment_text(details["description"]) == "Write a note.\nTwo lines."
        with TestCase().assertRaisesRegex(RuntimeError, "HTTP 302"):
            canvas.assignment_details(client, school, "fixture", path)
    assert len(requests) == 2
    assert requests[0].url.path == "/api/v1" + path



def test_draft_saves_a_supported_file():
    """Save model text locally and stop when required material is missing."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    import files_

    with TemporaryDirectory() as folder, patch.object(files_, "OUTPUT_DIR", Path(folder)):
        details = {"id": 9, "allowed_extensions": ["txt"]}
        with patch.object(canvas, "draft_text", return_value={"draft": "Practice response", "question": ""}):
            path = Path(canvas.save_draft(details, lambda: None))
        assert path.suffix == ".txt" and path.read_text(encoding="utf-8") == "Practice response"
        with patch.object(canvas, "draft_text", return_value={"draft": "", "question": "Please supply the reading."}):
            with TestCase().assertRaisesRegex(ValueError, "supply the reading"):
                canvas.save_draft(details, lambda: None)
        assert list(Path(folder).iterdir()) == [path]



def test_review_binds_the_file_and_assignment():
    """Review only an allowed file and keep credentials out of saved state."""
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as folder:
        path = Path(folder) / "response.txt"
        path.write_bytes(b"Fixture response")
        details = {"submission_types": ["online_upload"], "allowed_extensions": ["txt"]}
        review = canvas.prepare_review("https://school.example", "private-fixture", "/courses/3/assignments/9", details, path)
        assert review["file"] == path.resolve() and not review["attempted"]
        assert "private-fixture" not in repr(review)
        with TestCase().assertRaisesRegex(ValueError, "allowed file type"):
            canvas.prepare_review("https://school.example", "token", "/courses/3/assignments/9", {**details, "allowed_extensions": ["pdf"]}, path)
        with TestCase().assertRaisesRegex(ValueError, "locked"):
            canvas.check_assignment({**details, "locked_for_user": True})


def load_tests(loader, tests, pattern):
    return TestSuite(FunctionTestCase(test) for name, test in globals().items() if name.startswith("test_"))
