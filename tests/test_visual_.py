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
            patch("visual_.check_input_idle"),
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


    def test_scroll_uses_signed_wheel_steps_at_the_checked_point(self):
        """Two down steps send a negative wheel delta after target validation."""
        from contextlib import nullcontext
        from ctypes import c_int32

        with (
            patch("visual_.pointer_target", return_value=nullcontext()) as target,
            patch("visual_.send_inputs") as send,
        ):
            visual_.scroll_pointer({}, "view", 4, 5, -2)
        target.assert_called_once_with({}, "view", 4, 5)
        event = send.call_args.args[0][0]
        self.assertEqual(event.mi.dwFlags, visual_.win32con.MOUSEEVENTF_WHEEL)
        self.assertEqual(c_int32(event.mi.mouseData).value, -240)


    def test_literal_input_never_parses_shortcut_text(self):
        """Braces and an emoji become Unicode units, not executable key names."""
        with patch("visual_.send_keyboard") as send:
            visual_.type_literal({}, "view", "{ENTER}😀")
        events = send.call_args.args[2]
        units = [event.ki.wScan for event in events[::2]]
        self.assertEqual(units, [*(ord(char) for char in "{ENTER}"), 0xD83D, 0xDE00])
        self.assertTrue(all(event.ki.wVk == 0 for event in events))

    def test_shortcut_releases_in_reverse_order(self):
        """Ctrl+A is one chord with both keys released in the same batch."""
        with patch("visual_.send_keyboard") as send:
            visual_.press_keys({}, "view", ["CTRL", "A"])
        events, releases = send.call_args.args[2:]
        self.assertEqual([event.ki.wVk for event in events], [17, 65, 65, 17])
        self.assertEqual([event.ki.wVk for event in releases], [65, 17])

    def test_focus_change_or_cancellation_blocks_keyboard_input(self):
        """A late model reply cannot type into a different field or a stopped task."""
        from threading import Event

        frame = {"handle": 7, "focus": 11}
        state = {"frame": frame, "_cancel": Event()}
        with (
            patch("visual_.checked_frame", return_value=frame),
            patch("visual_.keyboard_focus", return_value=12),
            patch("visual_.send_inputs") as send,
        ):
            with self.assertRaisesRegex(RuntimeError, "focus changed"):
                visual_.type_literal(state, "view", "hello")
            state["_cancel"].set()
            with self.assertRaises(InterruptedError):
                visual_.type_literal(state, "view", "hello")
            send.assert_not_called()


    def test_task_observes_again_before_reporting_result(self):
        """Scripted actions use one image each and finish from a new visible result."""
        first = {"id": "first", "image": Image.new("RGB", (20, 20))}
        second = {"id": "second", "image": Image.new("RGB", (20, 20), "white")}
        replies = [
            {"view": "first", "action": "click", "x": 5, "y": 5, "button": "left", "count": 1},
            {"view": "second", "action": "finish", "text": "Saved", "evidence": "Saved label"},
        ]
        state = {}
        with (
            patch("visual_.capture_window", side_effect=[first, second]) as capture,
            patch("visual_.click_pointer") as click,
            patch("visual_.checked_frame") as check,
            patch("visual_.pause_visual"),
        ):
            result = visual_.run_visual_task("Save", 7, state, lambda *_: replies.pop(0))
        self.assertEqual(capture.call_count, 2)
        click.assert_called_once_with(state, "first", x=5, y=5, button="left", count=1)
        check.assert_called_once_with(state, "second")
        self.assertIn("Visible result: Saved label", result)
        self.assertNotIn("frame", state)

    def test_late_or_repeated_decisions_do_not_click(self):
        """Reject stale model coordinates and repeated clicks on an unchanged image."""
        state = {}
        frame = {"id": "current", "image": Image.new("RGB", (20, 20))}
        reply = {"view": "old", "action": "click", "x": 5, "y": 5, "button": "left", "count": 1}
        with (
            patch("visual_.capture_window", return_value=frame),
            patch("visual_.click_pointer") as click,
            patch("visual_.pause_visual"),
        ):
            with self.assertRaisesRegex(RuntimeError, "old screenshot"):
                visual_.run_visual_task("Save", 7, state, lambda *_: reply)
            click.assert_not_called()
            reply["view"] = "current"
            with self.assertRaisesRegex(RuntimeError, "did not show a result"):
                visual_.run_visual_task("Save", 7, state, lambda *_: reply)
            click.assert_called_once()
        self.assertNotIn("frame", state)

    def test_vision_request_contains_current_image_only(self):
        """The API gets a PNG and image dimensions, never Windows objects or old images."""
        from types import SimpleNamespace
        from unittest.mock import Mock
        import json

        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"action":"reply"}'))]
        )
        frame = {"id": "test", "preview": Image.new("RGB", (20, 10)), "handle": object()}
        visual_.vision_reply(client, "fixture-model", "What is shown?", frame, ["click input sent"])
        content = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        data = json.loads(content[0]["text"])
        self.assertEqual((data["width"], data["height"]), (20, 10))
        self.assertEqual(data["view"], "test")
        self.assertNotIn("handle", data)
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))
