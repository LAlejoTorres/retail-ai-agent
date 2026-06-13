"""Human-escalation tool.

The agent calls this when a case is out of scope (legal, fraud, aggression,
safety) or when it cannot resolve a request. In the LangGraph flow this is the
seam where a real human-in-the-loop interrupt happens.
"""
from __future__ import annotations

import uuid

from app.tools.base import ToolResponse

_VALID_REASONS = {
    "falla_electrica_o_seguridad",
    "reclamo_legal_o_fraude",
    "cliente_agresivo",
    "fuera_de_politica",
    "no_resuelto",
    "otro",
}


def escalate_to_human(reason: str, context: str = "") -> ToolResponse:
    """Hand the conversation off to a human advisor."""
    normalized = reason if reason in _VALID_REASONS else "otro"
    case_id = f"ESC-{uuid.uuid4().hex[:6].upper()}"
    return ToolResponse(
        success=True,
        data={"case_id": case_id, "reason": normalized, "context": context},
        message=(
            f"He escalado tu caso a un asesor humano (referencia {case_id}). "
            "Te contactarán a la brevedad."
        ),
        requires_human=True,
    )
