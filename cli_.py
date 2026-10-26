"""Command-line input for ChexsaAI."""

from agent_ import run_agent
from browser_ import close_browser


def main():
    print("ChexsaAI")
    print("Type 'exit' or 'quit' to close.\n")

    browser = {}
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
                response = run_agent(message, browser)
                print(f"Chexsa > {response}")
            except KeyboardInterrupt:
                print("\nChexsa > Request cancelled.")
            except RuntimeError as error:
                print(f"Chexsa > {error}")
            except Exception:
                # Keep the chat open without showing private connection details.
                print("Chexsa > Could not complete the request. Check your connection and Chrome.")
    finally:
        # Release the browser connection when the chat ends.
        if browser.get("playwright") is not None:
            close_browser(browser["playwright"])


# Start the chat only when you run this file directly.
if __name__ == "__main__":
    main()
