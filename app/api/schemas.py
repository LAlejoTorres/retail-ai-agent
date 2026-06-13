"""Request/response models for the HTTP API."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.memory import SessionMemory
from app.agent.trace import TurnTrace


class ChatRequest(BaseModel):
    session_id: str = Field(..., examples=["demo-1"])
    message: str = Field(..., examples=["Quiero saber dónde está mi pedido"])


class ChatResponse(BaseModel):
    response: str
    memory: SessionMemory
    trace: TurnTrace


class SessionResponse(BaseModel):
    memory: SessionMemory


class SimpleResponse(BaseModel):
    status: str = "ok"
