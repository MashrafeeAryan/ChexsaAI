"""Command-line input for ChexsaAI."""

from browser_ import click_node, close_browser, open_browser, read_page, type_node
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
                # Read a connected tab afresh; do not use controls from an old message.
                observation = read_page(page) if page is not None and not page.is_closed() else None
                action = get_reply(message, observation)
                if action["action"] in ("navigate", "observe"):
                    # Normal conversation does not launch Chrome.
                    if playwright is None:
                        playwright, page = open_browser()
                    elif page.is_closed():
                        page = page.context.new_page()
                if action["action"] == "observe":
                    # Give the AI a view of the tab before it chooses what to click.
                    observation = read_page(page)
                    action = get_reply(message, observation)

                if action["action"] == "navigate":
                    page.goto(action["url"], wait_until="domcontentloaded", timeout=30000)
                    print(f"Chexsa > Opened {page.url}")
                    read_page(page)
                elif action["action"] == "click":
                    click_node(page, action["backend_node_id"])
                    # Sending a click does not prove the user's whole task succeeded.
                    print(f"Chexsa > Click sent to Chrome node {action['backend_node_id']}.")
                    read_page(page)
                elif action["action"] == "type":
                    type_node(page, action["backend_node_id"], action["text"])
                    print("Chexsa > Text entered and checked in the selected field.")
                    read_page(page)
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
