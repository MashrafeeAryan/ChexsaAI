"""Talk to the AI model using the settings saved in .env."""

import os
from pathlib import Path

from dotenv import load_dotenv
from openai import APIError, OpenAI, RateLimitError

# Find .env beside this file, even if you start Python from another folder.
load_dotenv(Path(__file__).with_name(".env"))
_client = None


# Send one message to the AI and return its answer.
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
                {"role": "system", "content": "You are ChexsaAI. Reply clearly and briefly."},
                {"role": "user", "content": message},
            ],
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
    return reply.strip()
