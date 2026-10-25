"""Talk to the AI model using the settings saved in .env."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

# Find .env beside this file, even if you start Python from another folder.
load_dotenv(Path(__file__).with_name(".env"))
_client = None


# Ask the AI whether to open a website or reply to the user.
def get_reply(message):
    # Keep the connection so later messages can reuse it.
    global _client

    api_key = os.getenv("LLM_API_KEY")
    base_url = os.getenv("LLM_BASE_URL")
    model = os.getenv("LLM_MODEL")
    if not api_key or not base_url or not model:
        raise RuntimeError("Set LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL in .env.")

    if _client is None:
        _client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30,
            max_retries=0,  # Do not repeat failed requests automatically.
        )

    try:
        response = _client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": (
                    "You are ChexsaAI. Return one JSON object, with no extra text. "
                    'To open a website, return {"action":"navigate","url":"https://example.com"}. '
                    'For conversation or missing information, return {"action":"reply","text":"Your reply"}. '
                    "Only opening websites is supported so far. Do not claim you clicked, "
                    "typed, sent anything, or completed other tasks. Reply clearly and briefly."
                )},
                {"role": "user", "content": message},
            ],
            response_format={"type": "json_object"},  # Ask for JSON instead of plain text.
            max_completion_tokens=1024,  # Put a limit on tokens generated per reply.
        )
    except RateLimitError:
        raise RuntimeError("The API usage limit was reached. Try again later.") from None
    except APIError:
        # Show a useful error without printing API credentials or raw server details.
        raise RuntimeError("Could not get an AI reply. Check your API settings and connection.") from None

    # The API returns a list of answers; [0] gets the first one.
    reply = response.choices[0].message.content
    if not reply or not reply.strip():
        raise RuntimeError("The AI returned an empty reply.")

    # Turn the JSON text into a Python dictionary, then check it before doing anything.
    try:
        action = json.loads(reply)
    except json.JSONDecodeError:
        raise RuntimeError("The AI returned an unreadable action. Nothing was run.") from None
    if not isinstance(action, dict):
        raise RuntimeError("The AI returned an invalid action. Nothing was run.")

    if action.get("action") == "navigate" and set(action) == {"action", "url"}:
        url = action["url"]
        if isinstance(url, str) and not any(char.isspace() for char in url):
            try:
                address = urlsplit(url)
                if address.scheme in ("http", "https") and address.hostname:
                    return action
            except ValueError:
                pass
    elif action.get("action") == "reply" and set(action) == {"action", "text"}:
        if isinstance(action["text"], str) and action["text"].strip():
            return action

    raise RuntimeError("The AI returned an unsupported action or invalid details. Nothing was run.")
