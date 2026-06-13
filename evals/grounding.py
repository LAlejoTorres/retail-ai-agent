"""Grounding check: the core anti-hallucination assertion.

For a given turn, every "hard fact" the agent states in natural language — IDs
(ORD/WAR/TKT/ESC) and prices — must be traceable to a tool result from that
turn. If the agent mentions a price or a ticket number that no tool returned,
it invented it, and the check fails.
"""
from __future__ import annotations

import json
import re

from app.agent.trace import TurnTrace

_ID_PATTERN = re.compile(r"\b(?:ORD|WAR|TKT|ESC)-[A-Z0-9]+\b", re.IGNORECASE)
# Colombian price formats: 4.299.000 / 4,299,000 / $4899000
_PRICE_PATTERN = re.compile(r"\$?\s?\d{1,3}(?:[.,]\d{3})+\b")


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s)


def _tool_evidence(trace: TurnTrace) -> str:
    """All tool inputs and outputs from the turn, as one searchable string.

    Args are included because a value the agent echoes (e.g. a budget the user
    gave) is legitimately grounded in what the agent passed to the tool.
    """
    return json.dumps(
        [{"args": c.args, "data": c.data} for c in trace.tools_called],
        ensure_ascii=False,
    ).lower()


def check_grounding(
    trace: TurnTrace, prior_evidence: str = ""
) -> tuple[bool, list[str]]:
    """Return (grounded, violations).

    `prior_evidence` carries tool inputs/outputs from EARLIER turns of the same
    session, so a reference the agent legitimately created before (e.g. an ESC/TKT
    id) and repeats now is not flagged as invented. A truly hallucinated id still
    appears in no turn's evidence and fails.
    """
    evidence = _tool_evidence(trace) + " " + prior_evidence
    evidence_digits = _digits(evidence)
    response = trace.final_response
    violations: list[str] = []

    for ref_id in _ID_PATTERN.findall(response):
        if ref_id.lower() not in evidence:
            violations.append(f"ID no respaldado por herramienta: {ref_id}")

    for price in _PRICE_PATTERN.findall(response):
        pd = _digits(price)
        # Ignore small numbers (e.g. years already excluded by 1.000+ grouping).
        if len(pd) >= 6 and pd not in evidence_digits:
            violations.append(f"Precio no respaldado por herramienta: {price.strip()}")

    return (not violations, violations)
