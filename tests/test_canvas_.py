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



def test_upload_sends_no_token_to_storage():
    """Only the school gets the token, even when the upload uses another host."""
    import httpx

    requests = []

    def reply(request):
        requests.append(request)
        if len(requests) == 1:
            assert request.url.path.endswith("/submissions/self/files")
            assert b"submit_assignment=false" in request.content
            return httpx.Response(200, json={
                "upload_url": "https://storage.example/upload",
                "upload_params": {"key": "fixture"},
            })
        if len(requests) == 2:
            assert request.url.host == "storage.example"
            assert "Authorization" not in request.headers
            assert b"Fixture bytes" in request.content
            return httpx.Response(303, headers={"Location": "https://school.example/api/v1/files/7"})
        assert request.url.host == "school.example"
        assert request.headers["Authorization"] == "Bearer fixture"
        return httpx.Response(200, json={"id": 7})

    with httpx.Client(transport=httpx.MockTransport(reply)) as client:
        assert canvas.upload_attachment(
            client, "https://school.example", "fixture", "/courses/3/assignments/9",
            "response.txt", b"Fixture bytes", lambda: None,
        ) == 7
    assert len(requests) == 3



def test_submit_verifies_the_file_and_never_replays():
    """A reviewed file is submitted once and its attachment appears on the receipt."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    school, token, assignment = "https://school.example", "fixture", "/courses/3/assignments/9"
    details = {"id": 9, "submission_types": ["online_upload"]}
    with TemporaryDirectory() as folder:
        file = Path(folder) / "draft.txt"
        file.write_bytes(b"Fixture")
        review = canvas.prepare_review(school, token, assignment, details, file)
        with (
            patch.object(canvas, "assignment_details", return_value=details),
            patch.object(canvas, "upload_attachment", return_value=7) as upload,
            patch.object(canvas, "canvas_request") as request,
            patch.object(canvas, "submission_status", side_effect=[{}, {"submitted_at": "fixture time", "attachments": [{"id": 7}]}]),
        ):
            assert canvas.submit_review(None, school, token, review, lambda: None) == "fixture time"
            assert request.call_args.kwargs["json"]["submission"]["file_ids"] == [7]
            with TestCase().assertRaisesRegex(ValueError, "already used"):
                canvas.submit_review(None, school, token, review, lambda: None)
            upload.assert_called_once()

        review = canvas.prepare_review(school, token, assignment, details, file)
        file.write_bytes(b"Changed")
        with patch.object(canvas, "assignment_details", return_value=details):
            with TestCase().assertRaisesRegex(ValueError, "changed after review"):
                canvas.submit_review(None, school, token, review, lambda: None)



def test_canvas_submission_requirements_are_respected():
    """Send the user to Canvas when it asks for a pledge or blocks submissions."""
    allowed = {"submission_types": ["online_upload"]}
    for key, value in (
        ("academic_integrity_pledge", "Fixture pledge"),
        ("require_lockdown_browser", True),
        ("can_submit", False),
    ):
        with TestCase().assertRaises(ValueError):
            canvas.check_assignment({**allowed, key: value})



def test_browser_command_reviews_before_any_upload():
    """Browser chat stages a file, then submits only on the separate command."""
    import json
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    import httpx
    from agent_ import run_agent

    school = "https://school.example"
    url = school + "/courses/3/assignments/9"
    state = {}
    methods = []
    submitted = False

    def reply(request):
        nonlocal submitted
        methods.append(request.method)
        path = request.url.path
        if path.endswith("/assignments/9"):
            return httpx.Response(200, json={"id": 9, "name": "Practice", "submission_types": ["online_upload"]})
        if path.endswith("/self/files"):
            return httpx.Response(200, json={"upload_url": "https://storage.example/file", "upload_params": {}})
        if request.url.host == "storage.example":
            assert b"Fixture answer" in request.content and "Authorization" not in request.headers
            return httpx.Response(201, json={"id": 7})
        if request.method == "POST" and path.endswith("/submissions"):
            assert not submitted
            assert json.loads(request.content)["submission"]["file_ids"] == [7]
            submitted = True
            return httpx.Response(201, json={"assignment_id": 9})
        assert path.endswith("/submissions/self")
        result = {"assignment_id": 9}
        if submitted:
            result.update(submitted_at="fixture time", attachments=[{"id": 7, "display_name": "answer.txt"}])
        return httpx.Response(200, json=result)

    with TemporaryDirectory() as directory:
        file = Path(directory) / "answer.txt"
        file.write_bytes(b"Fixture answer")

        def client(**kwargs):
            return real_client(transport=httpx.MockTransport(reply), **kwargs)

        real_client = httpx.Client
        with (
            patch.dict("os.environ", {"CANVAS_URL": school, "CANVAS_TOKEN": "fixture"}),
            patch.object(canvas.httpx, "Client", side_effect=client),
        ):
            assert "Submit it." in run_agent(f"/canvas attach {url} | {file}", state)
            assert methods == ["GET"] and not submitted
            assert "Canvas confirmed answer.txt" in run_agent("Submit it.", state)
            assert submitted and methods.count("POST") == 3
            with TestCase().assertRaisesRegex(ValueError, "already used"):
                run_agent("Submit it.", state)
            assert "answer.txt" in run_agent("Check my Canvas submission status.", state)



def test_lost_submit_response_never_replays_the_upload():
    """A lost response could mean the file was submitted. Leave the review used."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch

    school, token = "https://school.example", "fixture"
    path = "/courses/3/assignments/9"
    details = {"id": 9, "submission_types": ["online_upload"]}
    with TemporaryDirectory() as folder:
        file = Path(folder) / "answer.txt"
        file.write_bytes(b"Fixture answer")
        review = canvas.prepare_review(school, token, path, details, file)
        with (
            patch.object(canvas, "assignment_details", return_value=details),
            patch.object(canvas, "submission_status", return_value={}),
            patch.object(canvas, "upload_attachment", return_value=7) as upload,
            patch.object(canvas, "canvas_request", side_effect=RuntimeError("Lost response")) as post,
        ):
            with TestCase().assertRaisesRegex(RuntimeError, "could not be verified"):
                canvas.submit_review(None, school, token, review, lambda: None)
            with TestCase().assertRaisesRegex(ValueError, "already used"):
                canvas.submit_review(None, school, token, review, lambda: None)
            upload.assert_called_once()
            post.assert_called_once()



def test_plain_requests_choose_canvas_actions():
    """Choose draft, upload review, and submit from the user's own words."""
    assert canvas.canvas_intent("Can you do this assignment in Canvas?") == ("draft", "")
    assert canvas.canvas_intent("Please submit it.", has_review=True) == ("submit", "")
    assert canvas.canvas_intent("Don't submit it.", has_review=True) is None
    assert canvas.canvas_intent("Can it submit it?", has_review=True) is None
    assert canvas.canvas_intent("Do not do this assignment in Canvas") is None
    assert canvas.canvas_intent("Submit it.", has_assignment=True) == ("choose_file", "")
    assert canvas.canvas_intent("I updated the draft.", has_review=True) == ("review_again", "")
    assert canvas.canvas_intent("Show my Canvas assignment status.") == ("status", "")
    assert canvas.canvas_intent("Open a canvas in Paint") is None
    assert canvas.canvas_intent("What is Canvas?") is None



def test_plain_draft_uses_the_open_assignment():
    """The ordinary request finds an open assignment and saves a draft."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import Mock, patch
    import httpx
    import files_
    import agent_

    school = "https://school.example"
    page = Mock(url=school + "/courses/3/assignments/9")
    page.is_closed.return_value = False
    page.context.pages = [page]
    details = {"id": 9, "name": "Practice", "submission_types": ["online_upload"],
               "allowed_extensions": ["txt"], "description": "<p>Write two lines.</p>"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=details))
    real_client = httpx.Client

    with (
        TemporaryDirectory() as folder,
        patch.dict("os.environ", {"CANVAS_URL": school, "CANVAS_TOKEN": "fixture"}),
        patch.object(canvas.httpx, "Client", side_effect=lambda **kw: real_client(transport=transport, **kw)),
        patch.object(canvas, "draft_text", return_value={"draft": "Draft answer", "question": ""}),
        patch.object(agent_, "open_browser", return_value=(object(), page)),
        patch.object(agent_, "get_reply") as normal_model,
        patch.object(files_, "OUTPUT_DIR", Path(folder)),
    ):
        state = {}
        result = agent_.run_agent("Do this assignment in Canvas", state)
        assert "Submit it." in result
        assert state["_canvas_review"]["file"].read_text(encoding="utf-8") == "Draft answer"
        normal_model.assert_not_called()



def test_desktop_chat_routes_canvas_and_keeps_the_review():
    """Desktop uses Browser for the assignment and its submit follow-up."""
    from queue import Queue
    from threading import Event, Thread
    from app_runtime_ import run_worker

    jobs, events = Queue(), Queue()
    cancel, shutdown = Event(), Event()
    calls = []

    def browser(text, state):
        calls.append(text)
        if len(calls) == 1:
            state["_canvas_review"] = {"file": "fixture.txt"}
        else:
            assert state["_canvas_review"]["file"] == "fixture.txt"
        return "Browser ran"

    worker = Thread(
        target=run_worker,
        args=(jobs, events, cancel, shutdown),
        kwargs={"handlers": {"desktop": lambda *_: "Desktop ran", "browser": browser}},
    )
    worker.start()
    try:
        assert events.get(timeout=3)["kind"] == "ready"
        for text, mode in (
            ("Do this assignment in Canvas", "browser"),
            ("Submit it.", "browser"),
            ("Open Notepad", "desktop"),
        ):
            jobs.put({"kind": "task", "mode": "desktop", "text": text})
            assert events.get(timeout=3)["mode"] == mode
            result = events.get(timeout=3)
            assert result["kind"] == "result" and result["mode"] == mode
        assert len(calls) == 2
    finally:
        shutdown.set()
        worker.join(timeout=3)



def test_canvas_tab_needs_a_clear_target():
    """With two assignments open, use the focused tab or ask for the link."""
    from unittest.mock import Mock
    from agent_ import _canvas_tab

    school = "https://school.example"
    first = Mock(url=school + "/courses/3/assignments/9")
    second = Mock(url=school + "/courses/3/assignments/10")
    for page in (first, second):
        page.is_closed.return_value = False
        page.evaluate.return_value = False
    first.context.pages = [first, second]
    state = {"playwright": object(), "page": first}
    assert _canvas_tab(state, school) == ""
    second.evaluate.return_value = True
    assert _canvas_tab(state, school) == second.url



def test_outline_prompt_uses_only_assignment_context():
    """Ask for an outline in one model call."""
    import json
    from types import SimpleNamespace
    from unittest.mock import Mock, patch

    model = Mock()
    create = model.chat.completions.create
    create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"draft":"Topic and points","question":""}')
    )])
    with patch("llm_.model_client", return_value=(model, "fixture")):
        result = canvas.draft_text(
            {"name": "Practice", "description": "<p>Explain the topic.</p>"},
            outline=True,
        )
    assert result["draft"] == "Topic and points"
    create.assert_called_once()
    messages = create.call_args.kwargs["messages"]
    assert "Write an outline" in messages[0]["content"]
    assert json.loads(messages[1]["content"])["instructions"] == "Explain the topic."



def test_outline_saves_a_real_word_file():
    """A local outline can be saved even when Canvas only accepts PDF."""
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from unittest.mock import patch
    import files_

    details = {"id": 9, "allowed_extensions": ["pdf"]}
    with (
        TemporaryDirectory() as folder,
        patch.object(files_, "OUTPUT_DIR", Path(folder)),
        patch.object(canvas, "draft_text", return_value={"draft": "Topic", "question": ""}),
    ):
        path = Path(canvas.save_outline(details, lambda: None))
        assert path.suffix == ".docx"
        assert files_.read_file(path) == "Topic"



def test_one_request_opens_canvas_and_saves_an_outline():
    """Use the actual Browser entry point and verify the saved Word text."""
    import httpx
    from pathlib import Path
    from tempfile import TemporaryDirectory
    from types import SimpleNamespace
    from unittest.mock import Mock, patch
    import agent_
    import files_

    school = "https://school.example"
    url = school + "/courses/3/assignments/9"
    details = {"id": 9, "name": "Practice", "description": "<p>Explain the topic.</p>",
               "submission_types": ["none"], "allowed_extensions": ["pdf"]}
    requests = []

    def assignment(request):
        requests.append(request.method)
        assert request.url.path == "/api/v1/courses/3/assignments/9"
        return httpx.Response(200, json=details)

    client = httpx.Client
    page = Mock(url=url)
    page.is_closed.return_value = False
    page.context.pages = [page]
    model = Mock()
    create = model.chat.completions.create
    create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        message=SimpleNamespace(content='{"draft":"Heading\\n- Point","question":""}')
    )])

    with (
        TemporaryDirectory() as folder,
        patch.dict("os.environ", {"CANVAS_URL": school, "CANVAS_TOKEN": "fixture"}),
        patch.object(canvas.httpx, "Client", side_effect=lambda **kw: client(transport=httpx.MockTransport(assignment), **kw)),
        patch.object(agent_, "open_browser", return_value=(object(), page)),
        patch.object(agent_, "get_reply") as browser_model,
        patch("llm_.model_client", return_value=(model, "fixture")),
        patch.object(files_, "OUTPUT_DIR", Path(folder)),
    ):
        state = {}
        answer = agent_.run_agent("Open this assignment, read the instructions, and save an outline in Word.", state)
        saved, = Path(folder).glob("*.docx")
        assert str(saved) in answer
        assert files_.read_file(saved) == "Heading\n- Point"
        assert "_canvas_review" not in state
        page.goto.assert_called_once()
        assert page.goto.call_args.args[0] == url
        create.assert_called_once()
        browser_model.assert_not_called()
        assert requests == ["GET"]


def load_tests(loader, tests, pattern):
    return TestSuite(FunctionTestCase(test) for name, test in globals().items() if name.startswith("test_"))
