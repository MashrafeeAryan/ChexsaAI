"""Command-line input for ChexsaAI."""

import sys

from agent_ import run_agent
from desktop_agent_ import run_desktop_agent
from browser_ import close_browser


def main(mode="desktop"):
    """Run a simple chat in desktop or browser mode; routing comes later."""
    if mode not in ("desktop", "browser"):
        print("Choose desktop or browser mode.")
        return
    print(f"ChexsaAI — {mode} mode")
    print("Type 'exit' or 'quit' to close.\n")

    browser = {}
    desktop = {}
    try:
        while True:
            try:
                # strip() removes spaces from the ends of your message.
                message = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                # Leave cleanly if input closes or you press Ctrl+C.
                print("\nGoodbye.")
                break

            # lower() lets EXIT and Quit work too.
            if message.lower() in ("exit", "quit"):
                print("Goodbye.")
                break

            if not message:
                # Skip empty messages and wait for another one.
                continue

            try:
                # Keep both engines separate until we add automatic routing.
                response = run_desktop_agent(message, desktop) if mode == "desktop" else run_agent(message, browser)
                print(f"Chexsa > {response}")
            except KeyboardInterrupt:
                print("\nChexsa > Request cancelled.")
            except RuntimeError as error:
                print(f"Chexsa > {error}")
            except Exception:
                # Keep the chat open without showing private connection details.
                print("Chexsa > Could not complete the request. Check your connection and the selected app.")
    finally:
        # Release the browser connection when the chat ends.
        if browser.get("playwright") is not None:
            close_browser(browser["playwright"])


# Start the chat only when you run this file directly.
if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "desktop")
