"""
OllamaClient.

Thin wrapper around Ollama's local HTTP API. This module has no
imports from `common.database` or any model - it CANNOT reach the
database even by accident, which is the point ("the AI should NOT
directly access or modify the database or any other service's data
store"). Its only output is a validated `Intent` object; everything
that object leads to is decided by app/dispatcher.py, which talks to
the other services over their normal HTTP APIs - the exact same APIs
a human using the UI hits.

Ollama must be reachable (default http://ollama:11434 in
docker-compose, or http://localhost:11434 for local dev) with a model
pulled (`ollama pull gemma3`). No internet is required once the model
is pulled.
"""
import json
import logging

import httpx

from common.config import get_settings

from app.prompts import SYSTEM_PROMPT, build_user_prompt
from app.schemas import Intent, IntentAction

logger = logging.getLogger(__name__)


class OllamaUnavailableError(Exception):
    """Raised when Ollama can't be reached - callers should degrade
    gracefully (e.g. tell the user to use the forms directly) rather
    than crash the request."""


class OllamaClient:
    def __init__(self):
        settings = get_settings()
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    def extract_intent(self, user_message: str, timeout: float = 60.0) -> Intent:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(user_message)},
            ],
            "format": "json",   # Ollama's structured-output mode - constrains to valid JSON
            "stream": False,
            "options": {"temperature": 0.1},  # low temperature - this is extraction, not chat
        }

        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Ollama request failed: %s", exc)
            raise OllamaUnavailableError(
                f"Could not reach Ollama at {self.base_url} (model '{self.model}'). "
                f"Is Ollama running and has the model been pulled?"
            ) from exc

        data = resp.json()
        raw_content = data.get("message", {}).get("content", "")

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning("Ollama returned non-JSON content: %r", raw_content)
            return Intent(
                action=IntentAction.CLARIFY,
                clarifying_question=(
                    "Sorry, I didn't understand that clearly - could you rephrase it as a "
                    "simple statement, e.g. 'Sold 2 bags to Krishna for 2400, he paid 1000'?"
                ),
                raw_user_message=user_message,
            )

        try:
            intent = Intent(**parsed)
        except Exception as exc:  # pydantic ValidationError, TypeError, etc.
            logger.warning("Ollama JSON did not match Intent schema: %s (%r)", exc, parsed)
            return Intent(
                action=IntentAction.CLARIFY,
                clarifying_question="I couldn't fully understand that - could you rephrase it?",
                raw_user_message=user_message,
            )

        intent.raw_user_message = user_message
        return intent

    def answer_freeform(self, system_prompt: str, user_message: str, timeout: float = 60.0) -> str:
        """Unconstrained chat completion - NOT format=json, and its
        return value is plain text handed straight back to the chat UI,
        never parsed as structured data or dispatched anywhere. Used
        only for action == "general_query" (see dispatcher.py); every
        other action goes through extract_intent() above instead."""
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "stream": False,
            "options": {"temperature": 0.4},
        }
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=timeout)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("Ollama freeform request failed: %s", exc)
            raise OllamaUnavailableError(
                f"Could not reach Ollama at {self.base_url} (model '{self.model}')."
            ) from exc
        data = resp.json()
        return data.get("message", {}).get("content", "").strip() or (
            "I couldn't come up with an answer to that - could you rephrase it?"
        )
