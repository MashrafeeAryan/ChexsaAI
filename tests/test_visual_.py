"""Exercise visual actions with synthetic images and fake Windows input."""

import unittest
from unittest.mock import patch

from PIL import Image

import visual_


class VisualTests(unittest.TestCase):
    """Check geometry and input guards without touching the user's desktop."""

    def test_capture_uses_the_window_bounds(self):
        """Only the chosen window region is captured, including negative screen origins."""
        bounds = (-600, 100, 0, 400)
        with (
            patch("visual_.window_bounds", return_value=(42, bounds)),
            patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (600, 300))) as grab,
        ):
            frame = visual_.capture_window(7)
        grab.assert_called_once_with(bbox=bounds, all_screens=True)
        self.assertEqual(frame["bounds"], bounds)
        self.assertEqual(frame["process"], 42)
        self.assertEqual(frame["image"].size, (600, 300))

    def test_capture_rejects_moved_window(self):
        """A window that moves during capture cannot supply action coordinates."""
        with (
            patch("visual_.window_bounds", side_effect=[(42, (0, 0, 10, 10)), (42, (1, 0, 11, 10))]),
            patch("PIL.ImageGrab.grab", return_value=Image.new("RGB", (10, 10))),
            self.assertRaisesRegex(RuntimeError, "moved"),
        ):
            visual_.capture_window(7)
