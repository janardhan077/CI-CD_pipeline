"""
Assistant service.

POST /assistant/chat

Stateless per-call endpoint: the client sends the user's message, and
optionally a previously-returned `intent` + `confirmed: true` to
proceed with a destructive action after the user has explicitly
approved it. IN-ON never re-runs Ollama for a confirmation - once a
transaction reversal has been described, the SAME structured intent is
just re-dispatched with confirmed=True, so nothing about the action
can drift between "what we described" and "what we do."

This service holds no database connection of its own, to any
database - every read and write goes through another service's normal
REST API. See app/clients.py and app/dispatcher.py.

Every successful write response includes `data.affected`: a list of
UI areas the write changed (e.g. ["stock"], ["stock","sales",
"cashbank","credit"]). The frontend uses this to refresh exactly the
right panels after a chat action, instead of a full page reload -
see static/app.js's `refreshAffected()`.
"""
import logging

from fastapi import FastAPI

from common.config import get_settings
from common.errors import register_error_handlers

from app.ollama_client import OllamaClient, OllamaUnavailableError
from app.dispatcher import IntentDispatcher
from app.schemas import ChatRequest, ChatResponse

settings = get_settings()
logging.basicConfig(level=settings.log_level)

app = FastAPI(title="IN-ON Assistant Service", version="0.1.0")
register_error_handlers(app)


@app.get("/health")
def health():
    return {"status": "ok", "service": "assistant-service"}


@app.post("/assistant/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    dispatcher = IntentDispatcher()

    if payload.intent is not None and payload.confirmed:
        # This is a confirmation round-trip - skip Ollama entirely and
        # re-dispatch the exact intent the user already saw and approved.
        result = dispatcher.dispatch(payload.intent, confirmed=True)
        return ChatResponse(status=result.status, message=result.message,
                             intent=payload.intent, data=result.data)

    try:
        client = OllamaClient()
        intent = client.extract_intent(payload.message)
    except OllamaUnavailableError as exc:
        return ChatResponse(
            status="error",
            message=f"{exc} You can still use the Sales/Expenses/Credit/Stock forms directly.",
        )

    result = dispatcher.dispatch(intent, confirmed=False)
    return ChatResponse(status=result.status, message=result.message, intent=intent, data=result.data)
