"""Own a CDP connection without closing the user's browser on disconnect."""

import os
import shutil
import subprocess
import socket
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

from .models import BrowserError


class BrowserSession:
    def __init__(self, cdp_url=None, auto_launch=False, profile_dir=None, headless=False, profile_name="Default"):
        if not profile_name or profile_name in (".", "..") or any(char in profile_name for char in "/\\:"):
            raise ValueError("Chrome profile must be a folder name such as Default or Profile 1.")
        self.auto_launch = auto_launch
        self.profile_dir = Path(os.path.expandvars(str(profile_dir))).expanduser() if profile_dir else None
        self.profile_name = profile_name
        self._explicit_cdp = bool(cdp_url)
        self.cdp_url = cdp_url or self._profile_endpoint() or "http://127.0.0.1:9222"
        self.headless = headless
        self.launched_process = None
        self.playwright = None
        self.browser = None
        self.page = None
        self.page_id = ""
        self.clients = {}
        self.epochs = {}
        self._frame_clients = {}
        self._page_ids = {}
        self._root_frames = {}

    def _profile_endpoint(self):
        if self.profile_dir is None:
            return None
        try:
            lines = (self.profile_dir / "DevToolsActivePort").read_text(encoding="utf-8").splitlines()
            port = int(lines[0])
            if 1 <= port <= 65535 and re.fullmatch(r"/devtools/browser/[A-Za-z0-9_-]+", lines[1]):
                return f"ws://127.0.0.1:{port}{lines[1]}"
        except (OSError, ValueError, IndexError):
            pass
        # A configured profile must never attach to an unrelated Chrome on 9222.
        return self._fresh_endpoint()

    @staticmethod
    def _fresh_endpoint():
        with socket.socket() as available:
            available.bind(("127.0.0.1", 0))
            return f"http://127.0.0.1:{available.getsockname()[1]}"

    def connect(self):
        if self.browser and self.browser.is_connected():
            return
        if self.playwright:
            self.close()
        self.playwright = sync_playwright().start()
        try:
            self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_url)
        except Exception:
            if not self.auto_launch:
                self.close()
                raise BrowserError("not_connected", "Could not attach to Chrome. Enable remote debugging in that Chrome profile or configure CHEXSA_CDP_URL; alternatively enable auto launch.")
            if self.cdp_url.startswith(("ws:", "wss:")):
                if self._explicit_cdp:
                    self.close()
                    raise BrowserError("not_connected", "The configured Chrome debugging session is unavailable. Open that profile and enable remote debugging again.")
                self.cdp_url = self._fresh_endpoint()
            self._launch()
            self.browser = self.playwright.chromium.connect_over_cdp(self.cdp_url)
        self.ensure_page()

    def _launch(self):
        parsed = urlparse(self.cdp_url)
        if parsed.hostname not in ("localhost", "127.0.0.1"):
            raise BrowserError("not_connected", "Auto launch only supports local Chrome.")
        candidates = [shutil.which("chrome"), str(Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Google/Chrome/Application/chrome.exe"), str(Path(os.environ.get("PROGRAMFILES(X86)", "C:/Program Files (x86)")) / "Google/Chrome/Application/chrome.exe")]
        executable = next((p for p in candidates if p and Path(p).exists()), None)
        if not executable:
            raise BrowserError("not_connected", "Chrome was not found.")
        profile = self.profile_dir or Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Chexsa" / "chrome"
        standard = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Google" / "Chrome" / "User Data"
        if profile.resolve() == standard.resolve():
            raise BrowserError("not_connected", "For your normal Chrome profile, enable remote debugging at chrome://inspect/#remote-debugging and allow the connection. Chrome does not support launching its standard data directory with a debugging flag.")
        profile.mkdir(parents=True, exist_ok=True)
        command = [executable, f"--remote-debugging-port={parsed.port or 9222}", f"--user-data-dir={profile}", f"--profile-directory={self.profile_name}", "--no-first-run", "--no-default-browser-check"]
        if self.headless:
            command.append("--headless=new")
        command.append("about:blank")
        self.launched_process = subprocess.Popen(command, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urlopen(self.cdp_url + "/json/version", timeout=1):
                    return
            except OSError:
                time.sleep(.2)
        raise BrowserError("not_connected", "Chrome did not become available within 15 seconds. If this profile is already open without debugging, close that profile's Chrome and retry, or configure its existing CDP endpoint.")

    def get_page(self):
        if self.page is None or self.page.is_closed():
            raise BrowserError("page_closed", "The selected tab closed. Observe again to select an open tab.")
        return self.page

    def ensure_page(self):
        """Recover a live tab only at observation boundaries, never during an action."""
        if self.browser is None or not self.browser.is_connected():
            self.connect()
        if self.page is not None and not self.page.is_closed():
            return self.page
        for _ in range(3):
            pages = self.pages()
            preferred = [page for page in pages if page.url.startswith(("http:", "https:", "file:", "about:"))] or pages
            ordered = list(reversed(preferred))
            for page in ordered:
                try:
                    if page.evaluate("document.hasFocus()"):
                        ordered = [page] + [other for other in ordered if other is not page]
                        break
                except Exception:
                    continue  # A startup tab may disappear while Chrome opens another tab.
            for page in ordered:
                try:
                    self.select(page)
                    return self.get_page()
                except Exception:
                    continue
            try:
                self.select(self.browser.contexts[0].new_page())
                return self.get_page()
            except Exception:
                continue
        raise BrowserError("page_closed", "Chrome has no available tab. Open a tab and retry the task.")

    def select(self, page):
        self.page = page
        self.page_id = self.page_identifier(page)

    def page_identifier(self, page):
        if page not in self._page_ids:
            client = page.context.new_cdp_session(page)
            target = client.send("Target.getTargetInfo")["targetInfo"]["targetId"]
            self._page_ids[page] = target
            self._remember(target, client)
        return self._page_ids[page]

    def _remember(self, target, client):
        if target in self.clients:
            try:
                self.clients[target].send("Target.getTargetInfo")
                client.detach()
                return
            except Exception:
                self.clients.pop(target, None)
        self.clients[target] = client
        self.epochs[target] = 0
        client.send("Page.enable")
        self._root_frames[target] = client.send("Page.getFrameTree")["frameTree"]["frame"]["id"]
        client.on("Page.frameNavigated", lambda event: self._frame_changed(target, event["frame"]["id"]))
        client.on("Page.frameDetached", lambda event: self._frame_changed(target, event["frameId"]))

    def _frame_changed(self, target, frame_id):
        # Unrelated subframe navigation must not invalidate a live main-page field.
        # Detached child nodes still fail the recorded-node connectivity check.
        if frame_id == self._root_frames.get(target):
            self._changed(target)

    def _changed(self, target):
        self.epochs[target] = self.epochs.get(target, 0) + 1

    def targets(self):
        page = self.get_page()
        found = {self.page_id}
        previous = set(self._frame_clients.values())
        current = {}
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            try:
                # A Frame can move to a different renderer/CDP target on navigation.
                client = page.context.new_cdp_session(frame)
                target = client.send("Target.getTargetInfo")["targetInfo"]["targetId"]
                current[frame] = target
                self._remember(target, client)
                found.add(target)
            except Exception:
                # Same-process frames are already in the parent target's snapshot.
                pass
        self._frame_clients = current
        for obsolete in previous - found - set(self._page_ids.values()):
            old = self.clients.pop(obsolete, None)
            self.epochs.pop(obsolete, None)
            self._root_frames.pop(obsolete, None)
            if old:
                try:
                    old.detach()
                except Exception:
                    pass
        return [(target, self.clients[target]) for target in sorted(found)]

    def tabs(self):
        tabs = []
        for index, page in enumerate(self.pages()):
            try:
                tabs.append({"index": index, "page_id": self.page_identifier(page), "title": page.title(), "url": page.url})
            except Exception:
                if not page.is_closed():
                    raise
        return tabs

    def pages(self):
        for page, target in list(self._page_ids.items()):
            if page.is_closed():
                self._page_ids.pop(page)
                self.clients.pop(target, None)
                self.epochs.pop(target, None)
                self._root_frames.pop(target, None)
        return [page for context in self.browser.contexts for page in context.pages if not page.is_closed()]

    def close(self):
        if self.playwright:
            self.playwright.stop()
        self.playwright = self.browser = self.page = None
        self.page_id = ""
        self.epochs.clear()
        self.clients.clear()
        self._frame_clients.clear()
        self._page_ids.clear()
        self._root_frames.clear()
