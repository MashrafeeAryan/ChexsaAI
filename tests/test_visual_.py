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


    def test_preview_preserves_aspect_and_maps_negative_origin(self):
        """A smaller screenshot still points to the correct physical screen pixel."""
        image = Image.new("RGB", (3200, 1200))
        preview = visual_.model_image(image)
        self.assertEqual(preview.size, (1600, 600))
        frame = {"preview": preview, "bounds": (-3200, 100, 0, 1300)}
        self.assertEqual(visual_.screen_point(frame, 10, 20), (-3179, 141))
        self.assertEqual(visual_.screen_point(frame, 1599, 599), (-1, 1299))
        for x, y in ((1600, 0), (0, -1), (True, 0), (0, 1.5)):
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                visual_.screen_point(frame, x, y)


    def test_stale_and_changed_screens_are_rejected(self):
        """An older reading or a moved button cannot be used to send input."""
        frame = {
            "id": "current", "handle": 7, "process": 42, "bounds": (0, 0, 60, 60),
            "image": Image.new("RGB", (60, 60)), "captured": visual_.monotonic(),
        }
        state = {"frame": frame}
        with patch("visual_.capture_window") as capture:
            with self.assertRaisesRegex(RuntimeError, "no longer current"):
                visual_.checked_frame(state, "previous")
            capture.assert_not_called()

        changed = frame["image"].copy()
        changed.paste("white", (10, 10, 20, 20))
        with patch("visual_.capture_window", return_value={**frame, "image": changed}):
            with self.assertRaisesRegex(RuntimeError, "visible window changed"):
                visual_.checked_frame(state, "current")

        with patch("visual_.capture_window", return_value={**frame, "bounds": (2, 0, 62, 60)}):
            with self.assertRaisesRegex(RuntimeError, "window moved"):
                visual_.checked_frame(state, "current")


    def test_move_checks_target_and_consumes_the_screenshot(self):
        """A move uses the scaled point, then requires a fresh reading."""
        frame = {"preview": Image.new("RGB", (20, 10)), "bounds": (-40, 0, 0, 20)}
        state = {"frame": frame}
        with (
            patch("visual_.checked_frame", return_value=frame),
            patch("visual_.target_at", return_value=9),
            patch("visual_.win32api.SetCursorPos") as move,
            patch("visual_.win32api.GetCursorPos", return_value=(-29, 11)),
        ):
            visual_.move_pointer(state, "view", 5, 5)
        move.assert_called_once_with((-29, 11))
        self.assertNotIn("frame", state)


    def test_double_click_releases_button_and_does_not_retry(self):
        """A partial Windows input batch sends a release, never another click."""
        from contextlib import nullcontext

        with (
            patch("visual_.pointer_target", return_value=nullcontext()),
            patch("visual_.win32api.GetSystemMetrics", return_value=0),
            patch("pywinauto.win32functions.SendInput", side_effect=[1, 1]) as send,
            self.assertRaisesRegex(RuntimeError, "uncertain"),
        ):
            visual_.click_pointer({}, "view", 5, 5, "right", 2)
        self.assertEqual([call.args[0] for call in send.call_args_list], [4, 1])

    def test_covered_point_cannot_receive_a_click(self):
        """The screenshot bounds alone do not allow clicking another window."""
        frame = {"handle": 7, "process": 42, "bounds": (0, 0, 60, 60)}
        with (
            patch("visual_.window_bounds", return_value=(42, frame["bounds"])),
            patch("visual_.win32gui.WindowFromPoint", return_value=9),
            patch("visual_.win32gui.GetAncestor", return_value=8),
            self.assertRaisesRegex(RuntimeError, "covers"),
        ):
            visual_.target_at(frame, (5, 5))
