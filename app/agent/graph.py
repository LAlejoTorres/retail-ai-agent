"""The agent as a LangGraph state machine: agent ─(tool_calls?)─> tools ─> agent ─> END.

Native tool calling is the router (no hand-coded intent switch). The tools node
executes each call, updates session memory, and records a decision trace; a
per-session checkpointer keeps history across turns.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from app.agent.memory import SessionMemory, get_store

logger = logging.getLogger(__name__)
from app.agent.prompts import build_system_prompt
from app.agent.toolset import LC_TOOLS, execute
from app.agent.llm import get_chat_model
from app.tools.base import ToolResponse
from app.tools.catalog_tools import _parse_budget


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    session_id: str


_model = get_chat_model().bind_tools(LC_TOOLS)

# Cuántos turnos de historial se envían al modelo. Reenviar todo cada turno sube la
# latencia y puede desbordar el contexto (Ollama trunca por el INICIO, matando el
# system prompt). Se corta en límites de mensaje humano para no huérfanar tool_calls.
_MAX_TURNS = 5


def _window(messages: list) -> list:
    humans = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    if len(humans) <= _MAX_TURNS:
        return messages
    return messages[humans[-_MAX_TURNS]:]


def _memory_context(mem: SessionMemory) -> str:
    """Snapshot compacto de la memoria estructurada, inyectado cada turno para
    que los datos clave sobrevivan aunque los turnos viejos salgan de la ventana."""
    lines: list[str] = []
    c = mem.customer
    if c.identificacion:
        lines.append(
            f"- Cliente: {c.nombre_completo or 'sin nombre'} "
            f"(ID {c.identificacion}, {c.tipo or 'desconocido'})"
        )
    if mem.budget_cop:
        lines.append(f"- Presupuesto mencionado: ${mem.budget_cop:,} COP")
    if mem.products_consulted:
        lines.append(f"- Productos consultados: {', '.join(mem.products_consulted)}")
    if mem.last_order_id:
        lines.append(f"- Último pedido consultado: {mem.last_order_id}")
    if mem.last_ticket_id:
        lines.append(f"- Último ticket creado: {mem.last_ticket_id}")
    prefs = [v for v in (mem.preferences.uso, mem.preferences.marca_preferida,
                         mem.preferences.prioridad) if v]
    if prefs:
        lines.append(f"- Preferencias: {', '.join(prefs)}")
    if not lines:
        return ""
    return "DATOS DE LA SESIÓN (memoria confirmada por herramientas):\n" + "\n".join(lines)


# A model sometimes emits a tool call as TEXT; the strict provider 400s
# (tool_use_failed) and echoes it in `failed_generation`. We recover it. Shapes:
#   Llama:  <function=name>{json-args}</function>  (or <function=name{json-args}>)
#   Qwen:   <tool_call>{"name": ..., "arguments": {json-args}}</tool_call>
# `>?` after the name tolerates both Llama variants; args are taken as the first
# balanced {...} that follows (so nested objects survive).
_FUNC_HEAD = re.compile(r"<function=([A-Za-z_]\w*)\s*>?\s*(?=\{)", re.DOTALL)


def _balanced_json_objects(text: str) -> list[str]:
    """Return every balanced top-level {...} substring (brace-counted, so nested
    objects survive — a plain regex would truncate at the first '}')."""
    objs, depth, start = [], 0, None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                objs.append(text[start:i + 1])
                start = None
    return objs


def _salvage_tool_calls(exc: Exception) -> list[dict]:
    """Extract tool calls from a strict provider's `failed_generation` text."""
    body = getattr(exc, "body", None)
    failed = ""
    if isinstance(body, dict):
        failed = (body.get("error") or {}).get("failed_generation", "") or ""
    if not failed:
        failed = str(exc)

    calls: list[dict] = []
    # Shape 1 — Llama: the JSON *is* the args; take the first balanced {...} after
    # the name.
    for m in _FUNC_HEAD.finditer(failed):
        objs = _balanced_json_objects(failed[m.end():])
        if not objs:
            continue
        try:
            args = json.loads(objs[0])
        except json.JSONDecodeError:
            continue
        calls.append({"name": m.group(1), "args": args})
    # Shape 2 — Qwen: a JSON object with "name" + "arguments"/"parameters".
    if not calls:
        for blob in _balanced_json_objects(failed):
            try:
                obj = json.loads(blob)
            except json.JSONDecodeError:
                continue
            args = obj.get("arguments", obj.get("parameters")) if isinstance(obj, dict) else None
            if isinstance(obj, dict) and isinstance(obj.get("name"), str) and isinstance(args, dict):
                calls.append({"name": obj["name"], "args": args})

    return [{**c, "id": f"salvaged-{i}", "type": "tool_call"}
            for i, c in enumerate(calls)]


# Re-samples on a malformed tool call before degrading. We also salvage the intended
# call from each failed attempt; retries are cheap on Groq.
_MAX_ATTEMPTS = 3


def _invoke_model(messages: list):
    """Invoke the model; recover malformed tool calls and re-sample before degrading.
    A turn must never crash the agent (see CLAUDE.md robustness rule)."""
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return _model.invoke(messages)
        except Exception as exc:
            last_exc = exc
            salvaged = _salvage_tool_calls(exc)
            if salvaged:
                logger.warning("Recuperadas %d tool call(s) malformadas (intento %d)",
                               len(salvaged), attempt)
                return AIMessage(content="", tool_calls=salvaged)
            logger.warning("Fallo del modelo (intento %d/%d)", attempt, _MAX_ATTEMPTS,
                           exc_info=True)
    logger.error("El modelo falló %d veces; turno degradado", _MAX_ATTEMPTS,
                 exc_info=last_exc)
    return AIMessage(
        content="Disculpa, tuve un inconveniente procesando esa solicitud. "
                "¿Podrías reformularla, por favor?"
    )


def _agent_node(state: AgentState) -> dict:
    mem = get_store().get(state["session_id"])
    system = SystemMessage(content=build_system_prompt(_memory_context(mem)))
    messages = [system, *_window(state["messages"])]
    return {"messages": [_invoke_model(messages)]}


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
            # Reuse the tool's parser so a string like "5 millones" can't crash the
            # node and is stored as the same canonical integer the catalog filtered on.
            mem.budget_cop = _parse_budget(args["budget_cop"])
        if args.get("use_case"):
            mem.preferences.uso = args["use_case"]
        for p in resp_data.get("products", []):
            mem.note_product(p["product_id"])
    elif name == "create_order" and resp_data.get("order_id"):
        mem.last_order_id = resp_data["order_id"]
        mem.note_product(resp_data.get("product_id", ""))
    elif name == "get_order_status" and resp_data.get("found"):
        mem.last_order_id = resp_data["order_id"]
    elif name == "create_warranty_ticket" and resp_data.get("ticket_id"):
        mem.last_ticket_id = resp_data["ticket_id"]


def _user_text(state: AgentState) -> str:
    """All text the user has typed this session, lowercased."""
    return " ".join(
        m.content for m in state["messages"] if isinstance(m, HumanMessage)
    ).lower()


# Señales de que el usuario habló de presupuesto. Los tokens cortos ("mil", "cop")
# llevan límite de palabra para no dispararse dentro de "Camilo"/"familia"/"copa".
_BUDGET_RE = re.compile(
    r"presupuesto|mill[oó]n|barat|económ|economic|menos de|m[aá]ximo|gastar|"
    r"pesos|\$|\bhasta\b|\bmil\b|\bcop\b"
)


def _user_gave_budget(user_text: str) -> bool:
    return bool(_BUDGET_RE.search(user_text))


def _sanitize_search_args(args: dict, user_text: str) -> dict:
    """Drop a budget_cop the user never expressed — the model sometimes invents one,
    which would silently filter the catalog and pollute session memory."""
    if args.get("budget_cop") not in (None, "") and not _user_gave_budget(user_text):
        logger.warning("Ignorando budget_cop inventado (el usuario no mencionó "
                       "presupuesto)")
        return {**args, "budget_cop": None}
    return args


def _fabricated_registration(args: dict, user_text: str) -> bool:
    """True if a register_customer call carries PII the user never typed. Guard:
    identificación, teléfono and correo must each appear in what the user wrote."""
    def digits(s: str) -> str:
        return re.sub(r"\D", "", s or "")

    user_digits = digits(user_text)
    ident = digits(str(args.get("identificacion", "")))
    tel = digits(str(args.get("telefono", "")))
    correo = str(args.get("correo", "")).strip().lower()

    if ident and ident not in user_digits:
        return True
    if tel and tel not in user_digits:
        return True
    if correo and correo not in user_text:
        return True
    return False


def _tools_node(state: AgentState) -> dict:
    last: AIMessage = state["messages"][-1]
    store = get_store()
    mem = store.get(state["session_id"])
    tool_messages: list[ToolMessage] = []
    user_text = _user_text(state)

    for call in last.tool_calls:
        args = call["args"]
        if call["name"] == "search_products":
            args = _sanitize_search_args(args, user_text)
        if call["name"] == "register_customer" and _fabricated_registration(
            args, user_text
        ):
            logger.warning("Bloqueado register_customer con datos no provistos por "
                           "el usuario (posible alucinación de PII)")
            resp = ToolResponse.fail(
                "No puedo registrar datos que el cliente no haya proporcionado. "
                "Pídele su identificación, nombre, teléfono y correo reales antes de "
                "registrar."
            )
        else:
            resp = execute(call["name"], args)
        _update_memory(mem, call["name"], args, resp.data)
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
