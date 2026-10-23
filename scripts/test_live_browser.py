"""Opt-in real-model CLI smoke test using an empty, isolated Chrome profile.

Uses the configured API (and its quota). Never opens personal tabs or real email.
Run: python scripts/test_live_browser.py [--email] [--runs 2] [--headed]
"""

import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
from chexsa_browser.journal import TaskJournal
from chexsa_browser.session import BrowserSession


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def inspect_page(endpoint, expected, fixture_url):
    session = BrowserSession(cdp_url=endpoint)
    session.connect()
    try:
        page = session.get_page()
        url, title = page.url, page.title()
        parts = urlparse(url)
        if expected == "home":
            passed = parts.hostname in ("youtube.com", "www.youtube.com") and parts.path in ("", "/") and "YouTube" in title
        elif expected == "search":
            passed = parts.hostname in ("youtube.com", "www.youtube.com") and parts.path == "/results" and parse_qs(parts.query).get("search_query") == ["python tutorial"]
        else:
            if not url.startswith(fixture_url):
                return False, {"url": url, "title": title}
            actual = page.evaluate("({count: window.sendCount, mail: window.lastMail, wrong: document.querySelector('#wrong').textContent})")
            passed = actual == {"count": 1, "mail": {"to": "fixture@example.test", "subject": "Hello", "body": "Hello, how are you?"}, "wrong": ""}
            return passed, {"url": url, "actual": actual}
        return passed, {"url": url, "title": title}
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", action="store_true", help="Also send one email on the local fake mail page only")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--only", choices=("chat", "home", "search", "details", "email"))
    parser.add_argument("--model", help="Temporarily test another model; does not edit .env")
    parser.add_argument("--diagnostics", action="store_true", help="Print model JSON decisions from these isolated test pages")
    args = parser.parse_args()
    sys.stdout.reconfigure(errors="backslashreplace")
    if args.runs < 1:
        parser.error("--runs must be positive")
    load_dotenv(ROOT / ".env")
    results = []
    handler = functools.partial(QuietHandler, directory=str(ROOT / "tests" / "fixtures"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    fixture_url = f"http://127.0.0.1:{server.server_port}/mail.html"
    try:
        with tempfile.TemporaryDirectory(prefix="chexsa-live-test-") as temporary:
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            endpoint = f"http://127.0.0.1:{port}"
            env = {**os.environ, "CHEXSA_CDP_URL": endpoint, "CHEXSA_AUTO_LAUNCH": "0", "CHEXSA_STATE_DIR": temporary, "CHEXSA_TRACE_SCREENSHOTS": "0", "PYTHONIOENCODING": "utf-8"}
            if args.model:
                env["LLM_MODEL"] = args.model
            launcher = BrowserSession(cdp_url=endpoint, profile_dir=Path(temporary) / "chrome", headless=not args.headed)
            launcher._launch()
            try:
                cases = [("Hello", None), ("open youtube", "home"), ("open youtube and search for python tutorial", "search"), ("Send an email to fixture@example.test", "details")]
                if args.email or args.only == "email":
                    cases.append((f'Open {fixture_url}?rows=2000 and send an email to fixture@example.test with subject Hello and body "Hello, how are you?"', "email"))
                if args.only:
                    cases = [(request, expected) for request, expected in cases if (expected or "chat") == args.only]
                # A routing mistake must fail this test before any personal desktop
                # information can be observed or sent to the configured model.
                entry = "import app_runtime\ndef forbid_desktop(*args, **kwargs):\n raise RuntimeError('Live browser test forbids desktop access')\napp_runtime.create_desktop_agent = forbid_desktop\nimport cli\ncli.main(['--max-steps', '20', '--timeout', '150'])"
                if args.diagnostics:
                    diagnostic = "import json\nfrom chexsa_browser.model import BrowserModel\noriginal = BrowserModel._ask\ndef trace(self, *args, **kwargs):\n result = original(self, *args, **kwargs)\n print('[MODEL JSON]', json.dumps(result, ensure_ascii=True), flush=True)\n return result\nBrowserModel._ask = trace\n"
                    entry = diagnostic + entry
                for run in range(args.runs):
                    for request, expected in cases:
                        print(f"[LIVE] Run {run + 1}: {request}", flush=True)
                        started = time.monotonic()
                        process = subprocess.run([sys.executable, "-u", "-c", entry], input=request + "\nexit\n", text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=ROOT, env=env, timeout=210)
                        print(process.stdout, flush=True)
                        outcome = {"request": request, "seconds": round(time.monotonic() - started, 2), "run": run + 1, "model": env.get("LLM_MODEL"), "provider": env.get("LLM_PROVIDER")}
                        if expected == "details":
                            passed = "Chexsa [blocked]" in process.stdout and "What message should I send?" in process.stdout and "[BROWSER]" not in process.stdout
                        elif expected:
                            actual_ok, actual = inspect_page(endpoint, expected, fixture_url)
                            outcome.update(actual=actual)
                            journal = TaskJournal(Path(temporary) / "tasks.sqlite3")
                            try:
                                tasks = journal.recent(1)
                                state = journal.load(tasks[0]["id"]) if tasks else None
                                outcome["metrics"] = state.metrics if state else {}
                            finally:
                                journal.close()
                            passed = actual_ok and "Chexsa [success]" in process.stdout
                        else:
                            passed = "Chexsa > " in process.stdout and "Could not run" not in process.stdout and "[BROWSER]" not in process.stdout and "[AGENT]" not in process.stdout
                        outcome["passed"] = passed and process.returncode == 0
                        results.append(outcome)
                        print(json.dumps(outcome, ensure_ascii=True), flush=True)
                        if not outcome["passed"]:
                            raise RuntimeError("Live smoke test failed; actual page and reported outcome must both pass.")
            finally:
                cleanup = BrowserSession(cdp_url=endpoint)
                try:
                    cleanup.connect()
                    cleanup.browser.new_browser_cdp_session().send("Browser.close")
                except Exception:
                    pass
                finally:
                    cleanup.close()
                    if launcher.launched_process.poll() is None:
                        launcher.launched_process.terminate()
                    launcher.launched_process.wait(timeout=15)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        report = ROOT / ".chexsa" / "live-smoke.json"
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"[LIVE] Report: {report}", flush=True)


if __name__ == "__main__":
    main()
