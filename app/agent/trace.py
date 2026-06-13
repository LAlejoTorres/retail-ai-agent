"""Per-turn decision trace: what the agent decided and did. Powers the UI trace
panel and the grounding assertion in the eval harness.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ToolCallTrace(BaseModel):
    name: str
    args: dict
    success: bool
    requires_human: bool = False
    message: str = ""
    data: dict = Field(default_factory=dict)  # tool result payload (for grounding)


class TurnTrace(BaseModel):
    session_id: str
    user_message: str
    tools_called: list[ToolCallTrace] = Field(default_factory=list)
    requires_human: bool = False
    final_response: str = ""
    latency_ms: int = 0

    @property
    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools_called]

    @property
    def used_tools(self) -> bool:
        return bool(self.tools_called)
