"""Read your messages in the terminal and show Chexsa's replies."""

# AppSession keeps the AI, browser, and current task together.
from app_runtime import AppSession


def main():
    app = AppSession()
    try:
        print("Chexsa\nType 'exit' or 'quit' to close. Ctrl+C cancels a running task.\n")
        while True:
            try:
                request = input("You > ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nGoodbye.")
                break
            if request.lower() in ("exit", "quit"):
                break
            if not request:
                continue
            try:
                # Send your message to the part of Chexsa that will handle it.
                response = app.run(request)
                # Show the task status when the browser handled your request.
                agent = app.browser_agent if app.last_mode == "browser" else None
                if agent and agent.last_result:
                    print(f"Chexsa [{agent.last_result.status}] > {response}")
                else:
                    print(f"Chexsa > {response}")
                # Show the ID that identifies this task in the saved history.
                if agent and agent.state:
                    print(f"[TASK] {agent.state.id}")
            except KeyboardInterrupt:
                print("\nChexsa > Task cancelled.")
            except Exception as error:
                print(f"Chexsa > Could not run the request: {error}")
    finally:
        # Close connections even if something went wrong.
        app.close()


# Start the chat when this file is run directly.
if __name__ == "__main__":
    main()
