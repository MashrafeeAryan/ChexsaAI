"""No browser or desktop setup is needed until a request selects that mode."""

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app_runtime import AppSession


class AppRuntimeTests(unittest.TestCase):
    @patch("app_runtime.LLM")
    def test_per_run_model_override_stays_lazy(self, factory):
        session = AppSession(model="test-model")
        factory.assert_not_called()
        factory.return_value.choose_mode.return_value = "chat"
        session.run("Hello")
        factory.assert_called_once_with(model="test-model")
    @patch("app_runtime.LLM")
    @patch("app_runtime.create_browser_agent")
    @patch("app_runtime.create_desktop_agent")
    def test_start_and_close_create_no_model_or_app(self, desktop, browser, model):
        session = AppSession()
        session.close()
        for factory in (model, browser, desktop):
            factory.assert_not_called()

    @patch("app_runtime.create_browser_agent")
    @patch("app_runtime.create_desktop_agent")
    def test_chat_does_not_open_apps(self, desktop, browser):
        llm = Mock()
        llm.choose_mode.return_value = "chat"
        llm.reply.return_value = "Hello"
        session = AppSession(llm)
        self.assertEqual(session.run("Hi"), "Hello")
        llm.reply.assert_called_once_with("Hi")
        desktop.assert_not_called()
        browser.assert_not_called()

    @patch("app_runtime.create_browser_agent")
    @patch("app_runtime.create_desktop_agent")
    def test_desktop_request_does_not_open_chrome(self, desktop, browser):
        llm = Mock()
        llm.choose_mode.return_value = "desktop"
        session = AppSession(llm)
        session.run("Open Word")
        session.run("Write Hello")
        desktop.assert_called_once_with(llm)
        browser.assert_not_called()
        desktop.return_value.run.assert_any_call("Open Word")

    @patch("app_runtime.create_browser_agent")
    def test_browser_is_created_after_routing_and_reused(self, factory):
        llm, backend, agent = Mock(), Mock(), Mock()
        agent.state = None
        factory.return_value = backend, agent
        def choose(request):
            if request == "First browser task":
                factory.assert_not_called()
            return "browser"
        llm.choose_mode.side_effect = choose
        session = AppSession(llm, max_steps=12, timeout=30)
        session.run("First browser task")
        session.run("Second browser task")
        factory.assert_called_once_with(llm, max_steps=12, timeout=30)
        session.close()
        backend.close.assert_called_once()

    @patch("app_runtime.create_browser_agent")
    def test_browser_clarification_stays_with_pending_task(self, factory):
        llm, backend, agent = Mock(), Mock(), Mock()
        llm.choose_mode.return_value = "browser"
        agent.state = None
        factory.return_value = backend, agent
        session = AppSession(llm)
        session.run("Send an email")
        agent.state = SimpleNamespace(status="blocked", question="Who is the recipient?")
        llm.choose_mode.reset_mock()
        session.run("fixture@example.test")
        llm.choose_mode.assert_not_called()
        agent.run.assert_called_with("fixture@example.test")

    @patch("app_runtime.create_browser_agent")
    def test_unknown_route_does_not_default_to_opening_chrome(self, browser):
        llm = Mock()
        llm.choose_mode.return_value = "unclear"
        with self.assertRaises(ValueError):
            AppSession(llm).run("Something")
        browser.assert_not_called()
