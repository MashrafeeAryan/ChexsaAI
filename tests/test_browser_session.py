"""Tab recovery must happen before observation, never by retargeting an action."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from chexsa_browser.models import BrowserError
from chexsa_browser.session import BrowserSession


def page(name, closed=False, focused=False):
    value = Mock()
    value.name, value.url = name, "https://fixture.example.test/" + name
    value.is_closed.return_value = closed
    value.evaluate.return_value = focused
    return value


class BrowserSessionTests(unittest.TestCase):
    def test_unrelated_subframe_navigation_keeps_main_page_refs_valid(self):
        session = BrowserSession()
        session.epochs["target"] = 4
        session._root_frames["target"] = "main"
        session._frame_changed("target", "advertising-frame")
        self.assertEqual(session.epochs["target"], 4)
        session._frame_changed("target", "main")
        self.assertEqual(session.epochs["target"], 5)

    def session(self, pages):
        session = BrowserSession()
        session.browser = Mock()
        session.browser.is_connected.return_value = True
        session.browser.contexts = [SimpleNamespace(pages=pages, new_page=Mock())]
        session.page_identifier = lambda item: item.name
        return session

    def test_closed_tab_is_recovered_only_when_observing(self):
        old, current = page("old", closed=True), page("current", focused=True)
        session = self.session([old, current])
        session.select(old)
        with self.assertRaises(BrowserError):
            session.get_page()
        self.assertIs(session.page, old)
        self.assertIs(session.ensure_page(), current)
        self.assertEqual(session.page_id, "current")

    def test_empty_browser_gets_a_new_tab(self):
        session = self.session([])
        new = page("new")
        session.browser.contexts[0].new_page.return_value = new
        self.assertIs(session.ensure_page(), new)
        session.browser.contexts[0].new_page.assert_called_once()

    def test_startup_tab_closing_during_focus_check_is_skipped(self):
        current, disappearing = page("current", focused=True), page("startup")
        disappearing.evaluate.side_effect = RuntimeError("Target closed")
        session = self.session([current, disappearing])
        self.assertIs(session.ensure_page(), current)

    def test_live_selected_tab_stays_selected(self):
        selected, other = page("selected"), page("other", focused=True)
        session = self.session([selected, other])
        session.select(selected)
        self.assertIs(session.ensure_page(), selected)

    def test_disconnected_browser_reconnects_before_observation(self):
        session = self.session([])
        session.browser.is_connected.return_value = False
        current = page("reconnected")
        def reconnect():
            session.browser.is_connected.return_value = True
            session.select(current)
        session.connect = Mock(side_effect=reconnect)
        self.assertIs(session.ensure_page(), current)
        session.connect.assert_called_once()

    @patch("chexsa_browser.session.urlopen")
    @patch("chexsa_browser.session.subprocess.Popen")
    @patch("chexsa_browser.session.Path.mkdir")
    @patch("chexsa_browser.session.Path.exists", return_value=True)
    @patch("chexsa_browser.session.shutil.which", return_value="chrome.exe")
    def test_launch_uses_persistent_profile_and_skips_first_run(self, which, exists, mkdir, launch, urlopen):
        session = BrowserSession(profile_dir="fixture-profile")
        session._launch()
        arguments = launch.call_args.args[0]
        self.assertIn("--user-data-dir=fixture-profile", arguments)
        self.assertIn("--profile-directory=Default", arguments)
        self.assertIn("--no-first-run", arguments)
        self.assertIn("--no-default-browser-check", arguments)
        self.assertNotIn("--guest", arguments)
        self.assertNotIn("--incognito", arguments)
