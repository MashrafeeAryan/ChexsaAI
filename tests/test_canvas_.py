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


def load_tests(loader, tests, pattern):
    return TestSuite(FunctionTestCase(test) for name, test in globals().items() if name.startswith("test_"))
