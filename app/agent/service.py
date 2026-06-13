"""Turn orchestration: run the graph for one user message and assemble the
response, the structured session memory, and the decision trace.
"""
from __future__ import annotations

import json
import re
import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import graph
from app.agent.memory import SessionMemory, get_store
from app.agent.trace import ToolCallTrace, TurnTrace

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _clean(text: str) -> str:
    """Strip any stray Qwen3 <think> block as a safety net."""
    return _THINK.sub("", text or "").strip()


def _turn_slice(messages: list) -> list:
    """Messages produced during the current turn (after the last human message)."""
    last_human = max(
        (i for i, m in enumerate(messages) if isinstance(m, HumanMessage)),
        default=-1,
    )
    return messages[last_human + 1:]


def _build_trace(session_id: str, user_message: str, turn_msgs: list) -> TurnTrace:
    # Map tool_call_id -> parsed ToolResponse from this turn's ToolMessages.
    results: dict[str, dict] = {}
    for m in turn_msgs:
        if isinstance(m, ToolMessage):
            try:
                results[m.tool_call_id] = json.loads(m.content)
            except json.JSONDecodeError:
                results[m.tool_call_id] = {"success": False, "requires_human": False}

    calls: list[ToolCallTrace] = []
    final_text = ""
    for m in turn_msgs:
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", []) or []:
                r = results.get(tc["id"], {})
                calls.append(
                    ToolCallTrace(
                        name=tc["name"],
                        args=tc["args"],
                        success=bool(r.get("success", False)),
                        requires_human=bool(r.get("requires_human", False)),
                        message=r.get("message", ""),
                        data=r.get("data", {}) or {},
                    )
                )
            if m.content:
                final_text = _clean(m.content)

    return TurnTrace(
        session_id=session_id,
        user_message=user_message,
        tools_called=calls,
        requires_human=any(c.requires_human for c in calls),
        final_response=final_text,
    )


class ChatResult:
    def __init__(self, response: str, memory: SessionMemory, trace: TurnTrace):
        self.response = response
        self.memory = memory
        self.trace = trace


def chat(session_id: str, message: str) -> ChatResult:
    started = time.perf_counter()
    config = {"configurable": {"thread_id": session_id}}
    try:
        state = graph.invoke(
            {"messages": [HumanMessage(content=message)], "session_id": session_id},
            config,
        )
    except Exception:
        # Final safety net: a turn should never surface as a 500. Degrade to a
        # friendly message and an empty trace.
        memory = get_store().get(session_id)
        trace = TurnTrace(
            session_id=session_id,
            user_message=message,
            final_response="",
            latency_ms=int((time.perf_counter() - started) * 1000),
        )
        return ChatResult(
            response="Disculpa, ocurrió un problema temporal. ¿Puedes intentarlo de "
                     "nuevo?",
            memory=memory,
            trace=trace,
        )

    turn_msgs = _turn_slice(state["messages"])
    trace = _build_trace(session_id, message, turn_msgs)
    trace.latency_ms = int((time.perf_counter() - started) * 1000)

    memory = get_store().get(session_id)
    memory.last_intent = trace.tool_names[0] if trace.tool_names else memory.last_intent
    return ChatResult(response=trace.final_response, memory=memory, trace=trace)
