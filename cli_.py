"""Command-line input for ChexsaAI."""

from browser_ import close_browser, open_browser, open_page
from llm_ import get_reply


def main():
    print("ChexsaAI")
    print("Type 'exit' or 'quit' to close.\n")

    playwright = None
    page = None
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
                action = get_reply(message)
                if action["action"] == "navigate":
                    # Open Chrome only when the AI chooses a browser action.
                    if playwright is None:
                        playwright, page = open_browser()
                    elif page.is_closed():
                        page = page.context.new_page()
                    open_page(page, action["url"])
                    # Report success only after Playwright finishes opening the page.
                    print(f"Chexsa > Opened {page.url}")
                else:
                    print(f"Chexsa > {action['text']}")
            except KeyboardInterrupt:
                print("\nChexsa > Request cancelled.")
            except RuntimeError as error:
                print(f"Chexsa > {error}")
            except Exception:
                # Keep the chat open without showing private connection details.
                print("Chexsa > Could not complete the request. Check your connection and Chrome.")
    finally:
        # Release the browser connection when the chat ends.
        if playwright is not None:
            close_browser(playwright)


# Start the chat only when you run this file directly.
if __name__ == "__main__":
    main()
