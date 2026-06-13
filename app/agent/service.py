"""Turn orchestration: run the graph for one user message and assemble the
response, the structured session memory, and the decision trace.
"""
from __future__ import annotations

import json
import logging
import re
import time

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import graph
from app.agent.memory import SessionMemory, get_store
from app.agent.price_guard import (
    collect_grounded_ids,
    collect_grounded_prices,
    correct_ids,
    correct_prices,
)
from app.agent.trace import ToolCallTrace, TurnTrace
from app.domain.recommender import get_product

logger = logging.getLogger(__name__)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_JSON_FENCE = re.compile(r"```(?:json)?\s*\{.*?\}\s*```", re.DOTALL)
_TEXT_LABEL = re.compile(r"^respuesta en texto( plano| natural)?\s*:?\s*", re.IGNORECASE)


def _strip_leading_json(text: str) -> str:
    """Drop a leading JSON object (e.g. a fake format-"error" blob) when natural
    text follows it; if the reply is ONLY JSON, keep it rather than answer empty."""
    if not text.startswith("{"):
        return text
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                rest = _TEXT_LABEL.sub("", text[i + 1:].strip())
                return rest if rest else text
    return text


def _clean(text: str) -> str:
    """Safety net over the model output: strip stray Qwen3 <think> blocks and
    JSON blobs the format guardrail forbids (fenced or prepended to the reply)."""
    text = _THINK.sub("", text or "")
    text = _JSON_FENCE.sub("", text).strip()
    return _strip_leading_json(text).strip()


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


def reset_session(session_id: str) -> None:
    """Borra la sesión: memoria estructurada Y el hilo del checkpointer (si no, el
    agente seguiría 'recordando' la conversación por el historial de LangGraph)."""
    get_store().reset(session_id)
    try:
        graph.checkpointer.delete_thread(session_id)
    except Exception:
        logger.exception("No se pudo borrar el hilo del checkpointer (%s)", session_id)


class ChatResult:
    def __init__(self, response: str, memory: SessionMemory, trace: TurnTrace):
        self.response = response
        self.memory = memory
        self.trace = trace


def chat(session_id: str, message: str) -> ChatResult:
    started = time.perf_counter()
    # recursion_limit acota el ping-pong agent<->tools (el default de 25 sería lento).
    config = {"configurable": {"thread_id": session_id}, "recursion_limit": 12}
    try:
        state = graph.invoke(
            {"messages": [HumanMessage(content=message)], "session_id": session_id},
            config,
        )
    except Exception:
        # Final safety net: a turn should never surface as a 500. Degrade to a
        # friendly message and an empty trace.
        logger.exception("Fallo no recuperado en el turno (session=%s)", session_id)
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

    # Red de seguridad determinista: corrige precios e IDs de referencia que el modelo
    # re-escribió con un error respecto al valor real de la herramienta. Solo ajusta
    # coincidencias únicas (nunca inventa).
    text = trace.final_response
    text, price_fixes = correct_prices(text, _grounded_prices(trace, memory))
    text, id_fixes = correct_ids(text, _grounded_ids(trace, memory))
    if price_fixes or id_fixes:
        logger.warning("Corregido contra la herramienta — precios=%s ids=%s",
                       price_fixes, id_fixes)
        trace.final_response = text

    return ChatResult(response=trace.final_response, memory=memory, trace=trace)


def _grounded_prices(trace: TurnTrace, memory: SessionMemory) -> set[int]:
    """Precios verificables: los de las herramientas del turno, más los del catálogo
    para los productos consultados en la sesión."""
    prices: set[int] = set()
    for call in trace.tools_called:
        prices |= collect_grounded_prices(call.data)
        prices |= collect_grounded_prices(call.args)
    for pid in memory.products_consulted or []:
        product = get_product(pid)
        if product:
            prices.add(int(product.precio_cop))
    return prices


def _grounded_ids(trace: TurnTrace, memory: SessionMemory) -> set[str]:
    """IDs verificables: los de las herramientas del turno, más el último pedido y
    ticket en memoria (sobreviven aunque su turno salga de la ventana)."""
    ids: set[str] = set()
    for call in trace.tools_called:
        ids |= collect_grounded_ids(call.data)
        ids |= collect_grounded_ids(call.args)
    for ref in (memory.last_order_id, memory.last_ticket_id):
        if ref:
            ids.add(ref.upper())
    return ids
