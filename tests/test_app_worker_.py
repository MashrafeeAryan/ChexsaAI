"""Exercise background tasks using fake engines and no UI or model calls."""

from queue import Queue
from threading import Event, Thread, get_ident
import unittest

from app_runtime_ import run_worker


class AppWorkerTests(unittest.TestCase):
    """The worker retains engine state and never moves actions onto the UI thread."""

    def test_requests_reuse_one_thread_and_state(self):
        """Two requests reuse their selected app state and the same execution thread."""
        jobs, events = Queue(), Queue()
        cancel, shutdown = Event(), Event()
        calls = []

        def run(text, state):
            calls.append(get_ident())
            state["count"] = state.get("count", 0) + 1
            return str(state["count"])

        worker = Thread(
            target=run_worker,
            args=(jobs, events, cancel, shutdown),
            kwargs={"handlers": {"desktop": run}},
        )
        worker.start()
        try:
            self.assertEqual(events.get(timeout=3)["kind"], "ready")
            for expected in ("1", "2"):
                jobs.put({"kind": "task", "mode": "desktop", "text": "example"})
                self.assertEqual(events.get(timeout=3)["kind"], "started")
                self.assertEqual(events.get(timeout=3)["text"], expected)
            self.assertEqual(calls[0], calls[1])
            self.assertNotEqual(calls[0], get_ident())
        finally:
            shutdown.set()
            worker.join(timeout=3)
        self.assertFalse(worker.is_alive())

    def test_stop_before_queued_action(self):
        """Stop cannot be lost when pressed just before the worker takes a job."""
        jobs, events = Queue(), Queue()
        cancel, shutdown = Event(), Event()
        cancel.set()
        calls = []
        jobs.put({"kind": "task", "mode": "desktop", "text": "example"})
        worker = Thread(
            target=run_worker,
            args=(jobs, events, cancel, shutdown),
            kwargs={"handlers": {"desktop": lambda *args: calls.append(args)}},
        )
        worker.start()
        try:
            self.assertEqual(events.get(timeout=3)["kind"], "ready")
            self.assertEqual(events.get(timeout=3)["kind"], "cancelled")
            self.assertEqual(calls, [])
        finally:
            shutdown.set()
            worker.join(timeout=3)
