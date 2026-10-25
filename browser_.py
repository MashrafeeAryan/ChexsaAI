"""Open Chrome and read the current page."""

import os
from pathlib import Path

from playwright.sync_api import Error, sync_playwright


# Connect to Chrome, or open it with Chexsa's saved browser profile.
def open_browser():
    playwright = sync_playwright().start()
    try:
        try:
            # Chrome must allow remote control for this connection to work.
            browser = playwright.chromium.connect_over_cdp(
                "http://127.0.0.1:9222", timeout=2000
            )
            context = browser.contexts[0] if browser.contexts else browser.new_context()
        except Error:
            # Reuse this folder so logins survive when Chexsa opens Chrome again.
            profile = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Chexsa" / "chrome"
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                channel="chrome",
                headless=False,
                args=["--no-first-run", "--no-default-browser-check"],
            )

        # context.pages means the open tabs. Keep tabs that are not closed
        # and show a website, a local file, or a blank page; skip Chrome settings.
        pages = [
            page for page in context.pages
            if not page.is_closed()
            and page.url.startswith(("http://", "https://", "file://", "about:blank"))
        ]
        page = pages[-1] if pages else context.new_page()
        return playwright, page
    except Exception:
        # Stop the connection if startup fails partway through.
        playwright.stop()
        raise


# Open an address in the chosen tab.
def open_page(page, url):
    page.goto(url, wait_until="domcontentloaded", timeout=30000)


# Read the page in a form we can later give to the AI.
def read_page(page):
    return {
        "url": page.url,
        "title": page.title(),
        # Chrome describes visible page content using names like button and textbox.
        "elements": page.locator("body").aria_snapshot(),
    }


# Release Playwright; Chrome launched by this file closes too.
def close_browser(playwright):
    playwright.stop()
