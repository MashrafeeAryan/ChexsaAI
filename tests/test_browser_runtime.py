import unittest
from unittest.mock import MagicMock, patch

from chexsa_browser.runtime import create_browser_agent


class RuntimeTests(unittest.TestCase):
    @patch("chexsa_browser.runtime.TaskJournal")
    @patch("chexsa_browser.runtime.BrowserBackend")
    def test_saved_chrome_profile_settings_reach_session(self, backend_type, journal_type):
        with patch.dict("os.environ", {"CHEXSA_CHROME_USER_DATA_DIR": "saved-profile-root", "CHEXSA_CHROME_PROFILE": "Profile 2", "CHEXSA_CDP_URL": "http://127.0.0.1:45678"}):
            create_browser_agent(MagicMock())
        options = backend_type.call_args.kwargs
        self.assertEqual(options["profile_dir"], "saved-profile-root")
        self.assertEqual(options["profile_name"], "Profile 2")
        self.assertEqual(options["cdp_url"], "http://127.0.0.1:45678")

    @patch("chexsa_browser.runtime.TaskJournal")
    @patch("chexsa_browser.runtime.BrowserBackend")
    def test_setup_uses_fixed_limits_and_connects_journal(self, backend_type, journal_type):
        with patch.dict("os.environ", {"CHEXSA_MAX_STEPS": "1", "CHEXSA_TIMEOUT": "1", "CHEXSA_MAX_FAILURES": "1", "CHEXSA_CONTEXT_CHARS": "2000"}):
            backend, agent = create_browser_agent(MagicMock())
        self.assertEqual((agent.max_steps, agent.timeout, agent.max_failures), (50, 600, 3))
        self.assertEqual(backend_type.call_args.kwargs["context_budget"], 6000)
        self.assertIs(agent.backend, backend)
        self.assertIs(agent.journal, journal_type.return_value)
        backend.connect.assert_called_once()

    @patch("chexsa_browser.runtime.TaskJournal")
    @patch("chexsa_browser.runtime.BrowserBackend")
    def test_connect_failure_releases_resources(self, backend_type, journal_type):
        backend_type.return_value.connect.side_effect = RuntimeError("no Chrome")
        with self.assertRaises(RuntimeError):
            create_browser_agent(MagicMock())
        backend_type.return_value.close.assert_called_once()
