"""Command-line input for ChexsaAI."""


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

        # Echo for now; the AI reply will replace this in the next step.
        print(f"Received: {message}")


# Start the chat only when you run this file directly.
if __name__ == "__main__":
    main()
