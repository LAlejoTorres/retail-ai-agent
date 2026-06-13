"""Shared tool-response contract.

Every tool returns the same envelope so the agent loop, the trace, and the tests
can handle results uniformly and errors never become free-form text.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResponse(BaseModel):
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    requires_human: bool = False

    @classmethod
    def ok(cls, data: dict | None = None, message: str = "") -> "ToolResponse":
        return cls(success=True, data=data or {}, message=message)

    @classmethod
    def fail(cls, message: str, requires_human: bool = False) -> "ToolResponse":
        return cls(success=False, message=message, requires_human=requires_human)
