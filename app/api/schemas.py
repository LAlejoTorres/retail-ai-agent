"""Request/response models for the HTTP API."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.memory import SessionMemory
from app.agent.trace import TurnTrace


class ChatRequest(BaseModel):
    # Límites defensivos: un mensaje gigante desbordaría la ventana de contexto.
    session_id: str = Field(..., min_length=1, max_length=64, examples=["demo-1"])
    message: str = Field(..., min_length=1, max_length=2000,
                         examples=["Quiero saber dónde está mi pedido"])


class ChatResponse(BaseModel):
    response: str
    memory: SessionMemory
    trace: TurnTrace


class SessionResponse(BaseModel):
    memory: SessionMemory


class SimpleResponse(BaseModel):
    status: str = "ok"
