"""Single source of truth for the agent's tools: each function is exposed both as a
LangChain StructuredTool (the schema the model sees) and via DISPATCH (direct
execution by the graph), so the two never drift.
"""
from __future__ import annotations

import logging
from collections.abc import Callable

from langchain_core.tools import StructuredTool

from app.tools import (
    catalog_tools,
    customer_tools,
    escalation_tools,
    order_tools,
    policy_tools,
    warranty_tools,
)
from app.tools.base import ToolResponse

# The raw python functions the agent may call.
_FUNCTIONS: list[Callable] = [
    customer_tools.find_customer_by_id,
    customer_tools.register_customer,
    catalog_tools.search_products,
    catalog_tools.get_product_details,
    catalog_tools.compare_products,
    order_tools.create_order,
    order_tools.get_order_status,
    order_tools.get_estimated_delivery,
    order_tools.update_delivery_address,
    warranty_tools.check_warranty,
    warranty_tools.create_warranty_ticket,
    policy_tools.search_policies,
    escalation_tools.escalate_to_human,
]

# name -> callable, used by the graph to execute tools.
DISPATCH: dict[str, Callable[..., ToolResponse]] = {f.__name__: f for f in _FUNCTIONS}

# LangChain tool objects, used only for their schemas when binding to the model.
LC_TOOLS: list[StructuredTool] = [
    StructuredTool.from_function(func=f, name=f.__name__) for f in _FUNCTIONS
]


# Strings some models emit to mean "no value"; normalized to None before dispatch.
_NULLISH = {"null", "none", "", "undefined", "nan", "n/a", "na"}


def _coerce_args(args: dict) -> dict:
    """Normalize nullish string arguments (e.g. "null") to real None."""
    return {
        k: (None if isinstance(v, str) and v.strip().lower() in _NULLISH else v)
        for k, v in args.items()
    }


def execute(name: str, args: dict) -> ToolResponse:
    """Run a tool by name, always returning a ToolResponse (never raising)."""
    func = DISPATCH.get(name)
    if func is None:
        return ToolResponse.fail(f"Herramienta desconocida: {name}.")
    try:
        return func(**_coerce_args(args))
    except Exception as exc:  # tools must fail gracefully, never crash the agent
        logging.getLogger(__name__).exception("Error ejecutando la herramienta %s", name)
        return ToolResponse.fail(f"Error ejecutando {name}: {exc}")
