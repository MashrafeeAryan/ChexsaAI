"""Real Chrome tests. Run explicitly; no accounts, model keys, or real email used."""

import functools
import http.server
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from chexsa_browser.backend import BrowserBackend
from chexsa_browser.models import ActionRequest
from chexsa_browser.models import TaskSpec
from chexsa_browser.agent import BrowserAgent
from chexsa_browser.journal import TaskJournal
from chexsa_browser.session import BrowserSession


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class ScriptedMailModel:
    """Test the model contract deterministically, using ONLY the bounded model view."""
    inputs = {"recipient": "fixture@example.test", "subject": "Hello", "body": "Hello, how are you?"}

    def plan(self, request, observation, state=None):
        return TaskSpec(request, dict(self.inputs), ["Open compose", "Fill draft", "Verify and send"], ["Fresh sending confirmation"])

    def visible(self, observation):
        data = json.loads(observation.context)
        return data, data["controls"]["elements"] + data.get("discovery", {}).get("elements", [])

    def choose(self, state, observation):
        if state.submission != "none":
            return ActionRequest("finish", {"response": "Email sent"})
        data, controls = self.visible(observation)
        if not any("dialog New message" in r["label"] for r in data["regions"]):
            name, query = "Compose", "Compose"
            action, arguments = "click", {}
        else:
            fields = [("recipient", "Recipients"), ("subject", "Subject"), ("body", "Message body")]
            done = {item.get("arguments", {}).get("text") for item in state.history if item.get("action") == "type" and item.get("status") == "ok"}
            remaining = next(((key, name) for key, name in fields if self.inputs[key] not in done), None)
            if remaining:
                key, name = remaining
                query = name
                action, arguments = "type", {"text": self.inputs[key]}
                if key == "recipient":
                    arguments["press_enter"] = True
            else:
                name, query = "Send", "Send dialog New message"
                action, arguments = "click", {}
        element = next((e for e in controls if e["name"] == name and (name != "Send" or "New message" in e.get("context", ""))), None)
        if element is None:
            return ActionRequest("find_elements", {"query": query})
        return ActionRequest(action, {**arguments, "ref": element["ref"]}, {"kind": "submission" if name == "Send" else "value"})

    def preflight(self, state, observation):
        data, controls = self.visible(observation)
        by_name = {e["name"]: e for e in controls}
        # Bounded controls include the three draft fields; the send button may need search.
        return {"ready": True, "region_ref": data["focused_region"], "subject_ref": by_name["Subject"]["ref"], "body_ref": by_name["Message body"]["ref"], "recipient_ref": "", "recipient_text": self.inputs["recipient"], "reason": "Draft values inspected"}

    def verify(self, state, before, after, result=None):
        view = after.context
        sent = "Message sent" in view
        failed = "Message could not be sent" in view
        return {"complete": sent, "failed": failed, "progress": "Email sending confirmed" if sent else "", "reason": "Application refused sending" if failed else "Waiting for confirmation", "evidence": ["Message sent"] if sent else (["Message could not be sent"] if failed else [])}


class BrowserIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        handler = functools.partial(QuietHandler, directory=str(Path(__file__).parent / "fixtures"))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        cls.session = BrowserSession()
        cls.session.connect()

    @classmethod
    def tearDownClass(cls):
        cls.session.close()
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)

    def setUp(self):
        self.page = self.session.get_page().context.new_page()
        self.session.select(self.page)
        self.backend = BrowserBackend(self.session, context_budget=4000)
        self.page.goto(self.base + "/controls.html")
        self.backend.observe()

    def tearDown(self):
        if not self.page.is_closed():
            self.page.close()
        pages = self.session.pages()
        if pages:
            self.session.select(pages[-1])

    def element(self, name, role=None):
        matches = [e for e in self.backend.observation.elements if e.name == name and (role is None or e.role == role)]
        self.assertEqual(len(matches), 1, (name, [(e.role, e.name) for e in matches]))
        return matches[0]

    def act(self, action, **arguments):
        if os.environ.get("CHEXSA_FIXTURE_DIAGNOSTICS") == "1" and action == "capture_screenshot":
            self._fixture_images = []
            if not getattr(self.page, "_fixture_traced", False):
                original_screenshot = self.page.screenshot
                def trace_screenshot(**options):
                    image = original_screenshot(**options)
                    self._fixture_images.append(image)
                    self._fixture_images = self._fixture_images[-12:]
                    return image
                self.page.screenshot = trace_screenshot
                self.page._fixture_traced = True
        result = self.backend.execute(ActionRequest(action, arguments))
        if result.status != "ok" and getattr(self, "_fixture_images", None):
            directory = Path(".chexsa/fixture-diagnostics") / self._testMethodName
            directory.mkdir(parents=True, exist_ok=True)
            for index, image in enumerate(self._fixture_images):
                (directory / f"frame-{index}.png").write_bytes(image)
            (directory / "observed.png").write_bytes(self.backend.observation.screenshot)
            (directory / "metadata.json").write_text(json.dumps({"ticket": self.backend.visual.ticket, "viewport": self.backend.visual._viewport(), "result": str(result)}, indent=2), encoding="utf-8")
        self.assertEqual(result.status, "ok", result)
        return result

    def test_duplicate_refs_survive_reordering_without_guessing(self):
        buttons = [e for e in self.backend.observation.elements if e.role == "button" and e.name == "Send"]
        self.assertEqual(len(buttons), 2)
        first, second = buttons
        self.page.evaluate("document.querySelector('#first').before(document.querySelector('#second'))")
        self.act("click", ref=second.ref)
        self.assertEqual(self.page.locator("#second").get_attribute("data-clicked"), "yes")
        self.assertIsNone(self.page.locator("#first").get_attribute("data-clicked"))
        self.act("click", ref=first.ref)
        self.assertEqual(self.page.locator("#first").get_attribute("data-clicked"), "yes")

    def test_stale_replaced_and_unknown_targets(self):
        old = self.element("Name").ref
        self.backend.observe()
        self.assertEqual(self.backend.execute(ActionRequest("type", {"ref": old, "text": "wrong"})).code, "stale_target")
        current = self.element("Name").ref
        self.page.evaluate("document.querySelector('input[aria-label=Name]').outerHTML='<input aria-label=Name>'")
        self.assertEqual(self.backend.execute(ActionRequest("type", {"ref": current, "text": "wrong"})).code, "target_detached")
        self.assertEqual(self.page.get_by_role("textbox", name="Name", exact=True).input_value(), "")
        self.assertEqual(self.backend.execute(ActionRequest("click", {"ref": "invented"})).code, "stale_target")

    def test_closed_observed_tab_recovers_an_open_tab_without_retargeting(self):
        old_ref = self.element("Name").ref
        previous = self.page
        self.page = previous.context.new_page()
        self.page.goto(self.base + "/controls.html")
        self.page.bring_to_front()
        previous.close()
        result = self.backend.execute(ActionRequest("type", {"ref": old_ref, "text": "wrong tab"}))
        self.assertEqual(result.code, "page_closed")
        self.assertFalse(result.executed)
        self.backend.observe()
        self.assertIs(self.session.get_page(), self.page)
        result = self.backend.execute(ActionRequest("type", {"ref": old_ref, "text": "wrong tab"}))
        self.assertEqual(result.code, "stale_target")
        self.assertEqual(self.page.get_by_label("Name", exact=True).input_value(), "")
        self.act("type", ref=self.element("Name").ref, text="Recovered correctly")

    def test_profile_preserves_site_login_state_after_browser_restart(self):
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        with tempfile.TemporaryDirectory() as directory:
            sessions = []
            try:
                for run in range(3):
                    session = BrowserSession(cdp_url=f"http://127.0.0.1:{port}", auto_launch=True, profile_dir=Path(directory) / "profile", profile_name="Profile 2" if run < 2 else "Default", headless=True)
                    sessions.append(session)
                    # Reuse this test class's Playwright driver for an isolated Chrome.
                    session._launch()
                    session.browser = self.session.playwright.chromium.connect_over_cdp(session.cdp_url)
                    session.ensure_page()
                    current = session.get_page()
                    current.goto(self.base + "/frame.html")
                    if run == 0:
                        current.context.add_cookies([{"name": "fixture_login", "value": "saved-login", "url": self.base, "expires": time.time() + 3600}])
                        current.evaluate("localStorage.setItem('fixture-account','saved-account')")
                    elif run == 1:
                        cookies = {cookie["name"]: cookie["value"] for cookie in current.context.cookies(self.base)}
                        self.assertEqual(cookies["fixture_login"], "saved-login")
                        self.assertEqual(current.evaluate("localStorage.getItem('fixture-account')"), "saved-account")
                    else:
                        self.assertNotIn("fixture_login", {cookie["name"] for cookie in current.context.cookies(self.base)})
                        self.assertIsNone(current.evaluate("localStorage.getItem('fixture-account')"))
                    session.clients[session.page_id].send("Browser.close")
                    session.launched_process.wait(timeout=15)
                    session.close()
            finally:
                for session in sessions:
                    try:
                        if session.browser and session.browser.is_connected():
                            session.clients[session.page_id].send("Browser.close")
                    finally:
                        session.close()
                        if session.launched_process:
                            session.launched_process.wait(timeout=15)

    def test_same_node_renamed_and_empty_observation_are_safe(self):
        send = next(e for e in self.backend.observation.elements if e.role == "button" and e.name == "Send")
        self.page.locator("#first").evaluate("e=>e.textContent='Delete'")
        self.assertEqual(self.backend.execute(ActionRequest("click", {"ref": send.ref})).code, "stale_target")
        self.assertIsNone(self.page.locator("#first").get_attribute("data-clicked"))
        self.page.set_content("<p>No controls</p>")
        self.backend.observe()
        self.assertFalse(self.backend.registry.refs)

    def test_cross_origin_frame_controls(self):
        url = self.base.replace("127.0.0.1", "localhost") + "/frame.html"
        with self.page.expect_event("framenavigated", predicate=lambda frame: "localhost" in frame.url):
            self.page.locator("iframe").evaluate("(e,url)=>e.src=url", url)
        frame = next(frame for frame in self.page.frames if "localhost" in frame.url)
        frame.wait_for_load_state("domcontentloaded")
        self.backend.observe()
        self.act("type", ref=self.element("Frame value").ref, text="Cross origin")
        self.act("click", ref=self.element("Frame action").ref)
        self.assertEqual(frame.get_by_role("textbox").input_value(), "Cross origin")
        self.assertEqual(frame.get_by_role("button").get_attribute("data-clicked"), "yes")
        # The same Frame object may move between renderer processes over its lifetime.
        for destination in (self.base + "/frame.html", url):
            with self.page.expect_event("framenavigated", predicate=lambda frame: frame.url == destination):
                self.page.locator("iframe").evaluate("(e,url)=>e.src=url", destination)
            frame = next(frame for frame in self.page.frames if frame.url == destination)
            frame.wait_for_load_state("domcontentloaded")
            self.backend.observe()
            self.act("type", ref=self.element("Frame value").ref, text="Navigated frame")
            self.assertEqual(frame.get_by_role("textbox").input_value(), "Navigated frame")

    def test_form_actions_shadow_dom_frame_and_upload(self):
        self.act("type", ref=self.element("Name").ref, text="Literal {text} + unicode café")
        self.act("select_option", ref=self.element("Colour", "combobox").ref, option="Red")
        self.act("check", ref=self.element("Choice").ref)
        self.act("uncheck", ref=self.element("Choice").ref)
        self.act("click", ref=self.element("Shadow action").ref)
        self.act("type", ref=self.element("Frame value").ref, text="Inside frame")
        self.act("click", ref=self.element("Frame action").ref)
        self.assertEqual(self.page.frame_locator("iframe").get_by_role("textbox").input_value(), "Inside frame")
        self.assertEqual(self.page.frame_locator("iframe").get_by_role("button").get_attribute("data-clicked"), "yes")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.txt"
            path.write_text("fixture attachment", encoding="utf-8")
            self.act("upload_file", ref=self.element("Upload").ref, file_path=str(path))
        self.assertEqual(self.page.get_by_label("Name", exact=True).input_value(), "Literal {text} + unicode café")
        self.assertFalse(self.page.get_by_label("Choice").is_checked())
        self.assertEqual(self.page.get_by_label("Colour").input_value(), "Red")

    def test_large_page_search_regions_and_autocomplete(self):
        self.page.goto(self.base + "/mail.html?rows=350")
        observation = self.backend.observe()
        self.assertGreater(len(observation.elements), 700)
        self.assertLessEqual(len(observation.context), 4000)
        self.assertEqual(self.act("find_elements", query="Open message 349").data["elements"][0]["name"], "Open message 349")
        self.act("click", ref=self.element("Compose").ref)
        observation = self.backend.observe()
        self.assertIn("Recipients", observation.context)
        self.assertNotIn("Open message 349", observation.context)
        self.act("type", ref=self.element("Recipients").ref, text="fixture@example.test", press_enter=True)
        self.backend.observe()
        self.assertIn("fixture@example.test", self.backend.observation.context)

    def test_navigation_tabs_scroll_and_batch(self):
        self.act("batch", actions=[{"action": "type", "arguments": {"ref": self.element("Name").ref, "text": "batch"}}, {"action": "check", "arguments": {"ref": self.element("Choice").ref}}])
        self.act("scroll", amount=500)
        self.page.wait_for_timeout(100)
        self.assertGreater(self.page.evaluate("scrollY"), 0)
        old_ref = self.element("Name").ref
        self.act("navigate", url=self.base + "/frame.html")
        self.assertEqual(self.backend.execute(ActionRequest("type", {"ref": old_ref, "text": "wrong"})).code, "stale_target")
        self.act("go_back")
        old_page_id = self.session.page_id
        self.backend.observe()
        self.act("new_tab", url=self.base + "/frame.html")
        opened = self.session.get_page()
        try:
            self.backend.observe()
            self.act("switch_tab", page_id=old_page_id)
            self.backend.observe()
            self.act("switch_tab", page_id=self.session.page_identifier(opened))
            self.act("close_tab")
        finally:
            if not opened.is_closed():
                opened.close()
            self.session.select(self.page)

    def test_unsafe_batch_has_no_partial_side_effects(self):
        request = ActionRequest("batch", {"actions": [{"action": "type", "arguments": {"ref": self.element("Name").ref, "text": "should not run"}}, {"action": "click", "arguments": {"ref": "invented"}}]})
        self.assertEqual(self.backend.execute(request).code, "unsafe_batch")
        self.assertEqual(self.page.get_by_label("Name", exact=True).input_value(), "")

    def test_batch_stops_when_an_input_navigates(self):
        self.page.get_by_label("Name", exact=True).evaluate("(e,url)=>e.addEventListener('input',()=>location.assign(url))", self.base + "/frame.html")
        result = self.backend.execute(ActionRequest("batch", {"actions": [{"action": "type", "arguments": {"ref": self.element("Name").ref, "text": "navigate"}}, {"action": "check", "arguments": {"ref": self.element("Choice").ref}}]}))
        self.assertEqual(result.code, "batch_interrupted")
        self.assertEqual(len(result.data["results"]), 1)

    def test_visual_click_typing_and_stale_images(self):
        image = self.act("capture_screenshot").data
        bounds = self.page.locator("#visual").bounding_box()
        self.act("click_coordinates", x=bounds["x"] + 30, y=bounds["y"] + 20, screenshot_id=image["screenshot_id"])
        self.assertTrue(self.page.evaluate("window.visualClicked"))
        self.backend.observe()
        image = self.act("capture_screenshot").data
        bounds = self.page.get_by_label("Name", exact=True).bounding_box()
        self.act("click_coordinates", x=bounds["x"] + 20, y=bounds["y"] + 10, screenshot_id=image["screenshot_id"])
        self.backend.observe()  # Focus identity may survive a new semantic observation.
        self.act("type_focused", text="Visual typing", screenshot_id=image["screenshot_id"])
        self.assertEqual(self.page.get_by_label("Name", exact=True).input_value(), "Visual typing")
        self.backend.observe()
        image = self.act("capture_screenshot").data
        self.page.evaluate("document.querySelector('#status').textContent='Page changed'")
        result = self.backend.execute(ActionRequest("click_coordinates", {"x": 20, "y": 20, "screenshot_id": image["screenshot_id"]}))
        self.assertEqual(result.code, "stale_screenshot")

    def test_coordinate_space_is_css_pixels_at_high_dpi(self):
        context = self.session.browser.new_context(viewport={"width": 900, "height": 700}, device_scale_factor=2)
        original = self.page
        try:
            self.page = context.new_page()
            self.session.select(self.page)
            self.page.goto(self.base + "/controls.html")
            self.backend = BrowserBackend(self.session)
            self.backend.observe()
            image = self.act("capture_screenshot").data
            self.assertEqual(image["width"], 900)
            self.assertTrue(self.backend.observation.screenshot.startswith(b"\x89PNG\r\n\x1a\n"))
            bounds = self.page.locator("#visual").bounding_box()
            self.act("click_coordinates", x=bounds["x"] + 20, y=bounds["y"] + 20, screenshot_id=image["screenshot_id"])
            self.assertTrue(self.page.evaluate("window.visualClicked"))
        finally:
            context.close()
            self.page = original
            self.session.select(original)

    def test_twenty_consecutive_verified_email_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = TaskJournal(Path(directory) / "tasks.db")
            try:
                for run in range(20):
                    with self.subTest(run=run + 1):
                        self.page.goto(self.base + "/mail.html?rows=150")
                        agent = BrowserAgent(self.backend, ScriptedMailModel(), journal=journal, emit=lambda text: None)
                        result = agent.run_task("Send hello to fixture@example.test")
                        self.assertEqual(result.status, "success", result)
                        self.assertEqual(self.page.evaluate("window.sendCount"), 1)
                        self.assertEqual(self.page.evaluate("window.lastMail"), {"to": "fixture@example.test", "subject": "Hello", "body": "Hello, how are you?"})
                        self.assertEqual(self.page.locator("#wrong").inner_text(), "")
                        self.assertEqual(journal.load(result.task_id).status, "success")
            finally:
                journal.close()

    def test_failed_uncertain_and_delayed_sends(self):
        for mode, expected, count in (("failure", "failed", 0), ("uncertain", "uncertain", 1), ("delay", "success", 1)):
            with self.subTest(mode=mode):
                self.page.goto(self.base + "/mail.html?mode=" + mode)
                result = BrowserAgent(self.backend, ScriptedMailModel(), emit=lambda text: None).run_task("Send hello to fixture@example.test")
                self.assertEqual(result.status, expected, result)
                self.assertEqual(self.page.evaluate("window.sendCount"), count)


if __name__ == "__main__":
    unittest.main(verbosity=2)
