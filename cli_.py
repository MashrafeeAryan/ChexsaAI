"""Command-line input for ChexsaAI."""

from llm_ import get_reply


def main():
    print("ChexsaAI")
    print("Type 'exit' or 'quit' to close.\n")

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
            reply = get_reply(message)
            print(f"Chexsa > {reply}")
        except KeyboardInterrupt:
            print("\nChexsa > Request cancelled.")
        except RuntimeError as error:
            print(f"Chexsa > {error}")
        except Exception:
            # Keep the chat open without showing private connection details.
            print("Chexsa > Could not get a reply. Check your settings and connection.")


# Start the chat only when you run this file directly.
if __name__ == "__main__":
    main()
