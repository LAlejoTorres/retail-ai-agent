"""Session memory: structured "working memory" the agent carries across turns.

Two layers, kept separate on purpose:
  - Conversation history (the message list) is owned by the LangGraph state.
  - `SessionMemory` below is the *structured* slot memory the business cares
    about (customer, budget, products consulted, last order, preferences). It is
    what we render in the UI side-panel to prove the agent retains context.

The store is hidden behind `MemoryStore` so the in-memory implementation used in
the demo can be swapped for Redis/SQLite later without touching callers.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, Field


class CustomerSlot(BaseModel):
    identificacion: str | None = None
    nombre_completo: str | None = None
    tipo: str | None = None  # 'nuevo' | 'frecuente'


class Preferences(BaseModel):
    uso: str | None = None              # e.g. "diseño gráfico"
    marca_preferida: str | None = None
    prioridad: str | None = None        # "rendimiento" | "portabilidad" | "precio"


class SessionMemory(BaseModel):
    """Everything the agent should remember for one session."""

    session_id: str
    customer: CustomerSlot = Field(default_factory=CustomerSlot)
    last_intent: str | None = None
    products_consulted: list[str] = Field(default_factory=list)
    budget_cop: int | None = None
    last_order_id: str | None = None
    last_ticket_id: str | None = None
    preferences: Preferences = Field(default_factory=Preferences)

    def note_product(self, product_id: str) -> None:
        if product_id not in self.products_consulted:
            self.products_consulted.append(product_id)


class MemoryStore(ABC):
    """Abstract session store. Swap implementations without touching callers."""

    @abstractmethod
    def get(self, session_id: str) -> SessionMemory: ...

    @abstractmethod
    def save(self, memory: SessionMemory) -> None: ...

    @abstractmethod
    def reset(self, session_id: str) -> None: ...


class InMemoryStore(MemoryStore):
    """Process-local dict store. Fine for a single-process demo."""

    def __init__(self) -> None:
        self._data: dict[str, SessionMemory] = {}

    def get(self, session_id: str) -> SessionMemory:
        if session_id not in self._data:
            self._data[session_id] = SessionMemory(session_id=session_id)
        return self._data[session_id]

    def save(self, memory: SessionMemory) -> None:
        self._data[memory.session_id] = memory

    def reset(self, session_id: str) -> None:
        self._data.pop(session_id, None)


# Single shared store instance for the app process.
_store = InMemoryStore()


def get_store() -> MemoryStore:
    return _store
