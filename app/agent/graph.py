"""The agent as a LangGraph state machine.

Flow:  agent ─(tool_calls?)─> tools ─> agent ─> ... ─> END

The model decides whether to answer directly or call tools (native tool calling
is the router — no hand-coded intent switch). The custom tools node executes
each call, updates structured session memory, and records the result so the
service can build a decision trace. A per-session checkpointer keeps the
conversation history across turns.
"""
from __future__ import annotations

import json
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.memory import SessionMemory, get_store
from app.agent.prompts import build_system_prompt
from app.agent.toolset import LC_TOOLS, execute
from app.agent.llm import get_chat_model


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    session_id: str


_model = get_chat_model().bind_tools(LC_TOOLS)
_system = SystemMessage(content=build_system_prompt())


def _agent_node(state: AgentState) -> dict:
    messages = [_system, *state["messages"]]
    try:
        response = _model.invoke(messages)
    except Exception:
        # Strict providers (e.g. Groq) reject a malformed tool call with a 400.
        # Re-sampling usually yields a valid call; if it still fails, degrade
        # gracefully instead of crashing the turn.
        try:
            response = _model.invoke(messages)
        except Exception:
            response = AIMessage(
                content="Disculpa, tuve un inconveniente procesando esa solicitud. "
                        "¿Podrías reformularla, por favor?"
            )
    return {"messages": [response]}


def _update_memory(mem: SessionMemory, name: str, args: dict, resp_data: dict) -> None:
    """Fold a tool result into the structured session memory."""
    if name == "find_customer_by_id" and resp_data.get("found"):
        c = resp_data["customer"]
        mem.customer.identificacion = c["identificacion"]
        mem.customer.nombre_completo = c["nombre_completo"]
        mem.customer.tipo = c.get("tipo", "frecuente")
    elif name == "register_customer" and resp_data.get("customer"):
        c = resp_data["customer"]
        mem.customer.identificacion = c["identificacion"]
        mem.customer.nombre_completo = c["nombre_completo"]
        mem.customer.tipo = "nuevo"
    elif name == "search_products":
        if args.get("budget_cop"):
            mem.budget_cop = int(args["budget_cop"])
        if args.get("use_case"):
            mem.preferences.uso = args["use_case"]
        for p in resp_data.get("products", []):
            mem.note_product(p["product_id"])
    elif name == "get_order_status" and resp_data.get("found"):
        mem.last_order_id = resp_data["order_id"]
    elif name == "create_warranty_ticket" and resp_data.get("ticket_id"):
        mem.last_ticket_id = resp_data["ticket_id"]


def _tools_node(state: AgentState) -> dict:
    last: AIMessage = state["messages"][-1]
    store = get_store()
    mem = store.get(state["session_id"])
    tool_messages: list[ToolMessage] = []

    for call in last.tool_calls:
        resp = execute(call["name"], call["args"])
        _update_memory(mem, call["name"], call["args"], resp.data)
        tool_messages.append(
            ToolMessage(
                content=json.dumps(resp.model_dump(), ensure_ascii=False),
                name=call["name"],
                tool_call_id=call["id"],
            )
        )

    store.save(mem)
    return {"messages": tool_messages}


def _route(state: AgentState) -> str:
    last = state["messages"][-1]
    return "tools" if getattr(last, "tool_calls", None) else END


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("agent", _agent_node)
    g.add_node("tools", _tools_node)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _route, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=MemorySaver())


# Compiled once at import; checkpointer persists per-session history in-process.
graph = build_graph()
