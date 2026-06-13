"""HTTP routes for the retail agent."""
from __future__ import annotations

from fastapi import APIRouter

from app.agent.memory import get_store
from app.agent.service import chat, reset_session
from app.api.schemas import (
    ChatRequest,
    ChatResponse,
    SessionResponse,
    SimpleResponse,
)

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def post_chat(req: ChatRequest) -> ChatResponse:
    result = chat(req.session_id, req.message)
    return ChatResponse(
        response=result.response, memory=result.memory, trace=result.trace
    )


@router.get("/session/{session_id}", response_model=SessionResponse)
def get_session(session_id: str) -> SessionResponse:
    return SessionResponse(memory=get_store().get(session_id))


@router.post("/reset-session", response_model=SimpleResponse)
def post_reset_session(session_id: str) -> SimpleResponse:
    reset_session(session_id)
    return SimpleResponse(status="reset")


@router.get("/health", response_model=SimpleResponse)
def health() -> SimpleResponse:
    return SimpleResponse(status="ok")
