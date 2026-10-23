"""Terminal chat with request-based browser and Windows desktop routing."""

import argparse

from chexsa_browser.journal import TaskJournal
from app_runtime import AppSession


def main(argv=None):
    parser = argparse.ArgumentParser(description="Chexsa computer assistant")
    parser.add_argument("--resume", metavar="TASK_ID", help="Observe and reconcile a saved task; never replay its action log")
    parser.add_argument("--tasks", action="store_true", help="List recent local task IDs")
    parser.add_argument("--max-steps", type=int, default=None)
    parser.add_argument("--model", help="Use another model for this run without editing .env")
    parser.add_argument("--timeout", type=int, default=None, help="Task deadline in seconds")
    args = parser.parse_args(argv)
    if args.tasks:
        journal = TaskJournal()
        try:
            for task in journal.recent():
                print(f'{task["id"]}  {task["status"]}  {task["updated"]}')
        finally:
            journal.close()
        return
    if args.max_steps is not None and args.max_steps < 1 or args.timeout is not None and args.timeout < 1:
        parser.error("Step and time limits must be positive.")
    app = AppSession(max_steps=args.max_steps, timeout=args.timeout, model=args.model)
    try:
        if args.resume:
            result = app.resume(args.resume)
            print(f"Chexsa [{result.status}] > {result.message}")
            return
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
                response = app.run(request)
                agent = app.browser_agent if app.last_mode == "browser" else None
                if agent and agent.last_result:
                    print(f"Chexsa [{agent.last_result.status}] > {response}")
                else:
                    print(f"Chexsa > {response}")
                if agent and agent.state:
                    print(f"[TASK] {agent.state.id}")
            except KeyboardInterrupt:
                print("\nChexsa > Task cancelled.")
            except Exception as error:
                print(f"Chexsa > Could not run the request: {error}")
    finally:
        app.close()


if __name__ == "__main__":
    main()
