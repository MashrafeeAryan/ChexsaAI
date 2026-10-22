"""Navigation races may retry reads, but must never replay an action."""

import unittest
from unittest.mock import Mock

from chexsa_browser.backend import BrowserBackend
from chexsa_browser.models import BrowserError


class BackendTests(unittest.TestCase):
    def backend(self):
        session = Mock()
        session.ensure_page.return_value.is_closed.return_value = False
        session.browser.is_connected.return_value = True
        return BrowserBackend(session=session)

    def test_observation_retries_frame_replacement(self):
        backend = self.backend()
        for failure in (RuntimeError("Frame with the given frameId is not found"), BrowserError("stale_observation", "Navigation")):
            backend._observe_page = Mock(side_effect=[failure, "fresh observation"])
            self.assertEqual(backend.observe(), "fresh observation")
            self.assertEqual(backend._observe_page.call_count, 2)

    def test_observation_retries_are_bounded(self):
        backend = self.backend()
        backend._observe_page = Mock(side_effect=RuntimeError("Frame with the given frameId is not found"))
        with self.assertRaises(RuntimeError):
            backend.observe()
        self.assertEqual(backend._observe_page.call_count, 3)

    def test_unrelated_collection_errors_are_not_hidden(self):
        backend = self.backend()
        backend._observe_page = Mock(side_effect=ValueError("Unexpected snapshot format"))
        with self.assertRaises(ValueError):
            backend.observe()
        backend._observe_page.assert_called_once()
