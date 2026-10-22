"""Load the model provider and support chat, request routing, and desktop decisions.

Browser decisions are handled by chexsa_browser.model using the same client.
"""

import json
import os

from dotenv import load_dotenv
from google import genai
from openai import OpenAI

from agent import AgentDecision, StepResult
from desktop_state import DesktopSnapshot


# Load model settings and API keys from .env.
load_dotenv()


# Define the decision format for Windows desktop tasks.
DESKTOP_DECISION_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "launch_app",
                "focus_window",
                "click_control",
                "type_text",
                "press_key",
                "hotkey",
                "select_option",
                "check",
                "uncheck",
                "close_window",
                "none",
            ],
        },
        "arguments": {"type": "object"},
        "done": {"type": "boolean"},
        "response": {"type": "string"},
    },
    "required": ["action", "arguments", "done", "response"],
}


class LLM:
    """Use the selected model provider to make Chexsa decisions."""

    def __init__(self) -> None:
        # These settings choose which provider and model Chexsa uses.
        self.provider = os.getenv("LLM_PROVIDER", "gemini")
        self.model = os.getenv("LLM_MODEL", "gemini-3.8-flash")
        # Compatible endpoints often serve text-only models. Images are opt-in.
        self.supports_vision = os.getenv("LLM_SUPPORTS_VISION", "1" if self.provider == "gemini" else "0").lower() in ("1", "true", "yes")
        self.request_timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "30"))
        if self.request_timeout < 1:
            raise ValueError("LLM_TIMEOUT_SECONDS must be at least 1.")
        self.reasoning_effort = os.getenv("LLM_REASONING_EFFORT", "low" if self.model in ("openai/gpt-oss-120b", "openai/gpt-oss-20b") else "")
        self.client = self._create_client()

    @property
    def request_options(self):
        options = {"timeout": getattr(self, "request_timeout", 30)}
        effort = getattr(self, "reasoning_effort", "")
        if effort:
            options["reasoning_effort"] = effort
        return options

    def _create_client(self):
        """Create the client needed by the selected provider."""

        if self.provider == "gemini":
            api_key = os.getenv("GEMINI_API_KEY")

            if not api_key:
                raise RuntimeError("GEMINI_API_KEY was not found.")

            return genai.Client(api_key=api_key)

        # Groq, OpenRouter, and similar services use the OpenAI API format.
        if self.provider == "openai_compatible":
            api_key = os.getenv("LLM_API_KEY")
            base_url = os.getenv("LLM_BASE_URL")

            if not api_key or not base_url:
                raise RuntimeError(
                    "LLM_API_KEY and LLM_BASE_URL are required."
                )

            return OpenAI(
                api_key=api_key,
                base_url=base_url,
                timeout=self.request_timeout,
                max_retries=0,
            )

        raise ValueError(f"Unknown LLM provider: {self.provider}")


    def choose_mode(self, request: str) -> str:
        """Choose chat, website interaction, or Windows desktop interaction."""

        prompt = (
            "Classify the user's request as chat, browser, or desktop. "
            "Use chat for greetings, explanations, or answers that need no app interaction. "
            "Use browser for interacting with websites or searching the web. "
            "Opening a website includes launching or attaching to Chrome; the browser agent handles that itself. "
            "Use desktop for controlling Windows apps or local computer actions. "
            "Choose by the user's destination and goal, not by the fact that a browser is a Windows app. "
            "Examples: 'open YouTube' -> browser; 'open a website in Chrome' -> browser; "
            "'open YouTube and search for jazz' -> browser; 'open Notepad' -> desktop; "
            "'change Chrome settings' -> desktop; 'hello' -> chat. "
            "Return exactly chat, browser, or desktop with no other text.\n\n"
            f"REQUEST:\n{request}"
        )

        if self.provider == "gemini":
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={"http_options": {"timeout": int(getattr(self, "request_timeout", 30) * 1000)}},
            )
            text = response.text
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                **self.request_options,
            )
            text = response.choices[0].message.content

        mode = (text or "").strip().lower()

        if mode not in ("chat", "browser", "desktop"):
            raise RuntimeError("The model did not choose chat, browser, or desktop. Please retry.")
        return mode

    def reply(self, request):
        """Answer in the terminal without opening a browser or desktop app."""
        prompt = "You are Chexsa. Reply to the user's message directly. Do not claim to have used a browser or computer tool.\n\n" + request
        if self.provider == "gemini":
            response = self.client.models.generate_content(model=self.model, contents=prompt, config={"http_options": {"timeout": int(getattr(self, "request_timeout", 30) * 1000)}})
            text = response.text
        else:
            response = self.client.chat.completions.create(model=self.model, messages=[{"role": "user", "content": prompt}], **self.request_options)
            text = response.choices[0].message.content
        if not text:
            raise RuntimeError("The model returned an empty response.")
        return text

    def decide_desktop(
        self,
        request: str,
        state: DesktopSnapshot,
        history: list[StepResult],
    ) -> AgentDecision:
        """Ask the model for the next desktop action."""

        previous_steps = [
            {
                "action": step.action,
                "arguments": step.arguments,
                "result": str(step.result),
                "error": step.error,
            }
            for step in history
        ]

        prompt = f"""
You control Windows desktop apps for Chexsa.

Return ONLY valid JSON:

{{
  "action": "launch_app | focus_window | click_control | type_text | press_key | hotkey | select_option | check | uncheck | close_window | none",
  "arguments": {{}},
  "done": false,
  "response": ""
}}

Actions:
- launch_app: command
- focus_window: title
- click_control: control_type, name or auto_id, optionally window_title
- type_text: control_type, text, name or auto_id, optionally window_title
- press_key: key
- hotkey: keys
- select_option: name, option, optionally window_title
- check: name, optionally window_title
- uncheck: name, optionally window_title
- close_window: optionally title
- none: task is complete

Rules:
- Choose ONE next desktop action.
- Use only controls and windows you can see, except launch_app.
- For common Windows apps, launch them with a normal executable or Windows command.
- If the user asks for writing, create the requested text inside type_text.
- Set done=true only when the task is complete.
- If an action is still needed, set done=false. Only finish with action="none" after observing the result.
- Never return action="none" with done=false.

USER REQUEST:
{request}

ACTIVE WINDOW:
{state.active_window}

OPEN WINDOWS:
{json.dumps(state.windows, indent=2)}

CONTROLS:
{json.dumps(state.controls, indent=2)}

PREVIOUS STEPS:
{json.dumps(previous_steps, indent=2)}
""".strip()

        if self.provider == "gemini":
            interaction = self.client.interactions.create(
                model=self.model,
                input=prompt,
                response_format={
                    "type": "text",
                    "mime_type": "application/json",
                    "schema": DESKTOP_DECISION_SCHEMA,
                },
            )
            text = interaction.output_text
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                **self.request_options,
            )
            text = response.choices[0].message.content

        if not text:
            raise RuntimeError("The model returned an empty response.")

        decision = json.loads(text)
        action = decision["action"]

        if action == "none":
            action = None

        return AgentDecision(
            action=action,
            arguments=decision["arguments"],
            done=decision["done"],
            response=decision["response"],
        )
