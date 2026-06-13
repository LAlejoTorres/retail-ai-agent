"""Warranty tools: coverage check and support-ticket creation.

Warranty validity is DERIVED from end_date vs today on every read, so it can
never drift from a stale status column.
"""
from __future__ import annotations

import uuid
from datetime import date

from app.data.db import get_connection
from app.tools.base import ToolResponse

# Symptoms the warranty policy says must go to a human (electrical / safety).
# Stems chosen so paraphrases ("no enciende" / "dejó de encender") all match.
_ESCALATION_SIGNALS = (
    "encend", "enciend", "prend", "no arranca", "quemad", "humo", "chispa",
    "olor a quemado", "se calienta", "sobrecalienta", "hinchad", "explot",
    "descarga", "corto", "no funciona", "muerto", "no responde",
)


def _warranty_status(end_date: str) -> str:
    return "activa" if date.fromisoformat(end_date) >= date.today() else "vencida"


def check_warranty(
    customer_id: str, product_id: str | None = None, order_id: str | None = None
) -> ToolResponse:
    """Check warranty coverage for a customer's product/order."""
    clauses = ["customer_id = ?"]
    params: list[str] = [customer_id]
    if product_id:
        clauses.append("product_id = ?")
        params.append(product_id)
    if order_id:
        clauses.append("order_id = ?")
        params.append(order_id)

    with get_connection() as conn:
        row = conn.execute(
            f"SELECT * FROM warranties WHERE {' AND '.join(clauses)} "
            "ORDER BY end_date DESC LIMIT 1",
            params,
        ).fetchone()

    if row is None:
        return ToolResponse.ok(
            data={"found": False},
            message="No encontré una garantía registrada con esos datos.",
        )

    status = _warranty_status(row["end_date"])
    return ToolResponse.ok(
        data={
            "found": True,
            "warranty_id": row["warranty_id"],
            "product_id": row["product_id"],
            "status": status,
            "end_date": row["end_date"],
            "coverage": row["coverage"],
        },
        message=f"Garantía {row['warranty_id']}: {status} (cubre hasta "
                f"{row['end_date']}).",
    )


def create_warranty_ticket(
    customer_id: str,
    issue_description: str,
    product_id: str | None = None,
    order_id: str | None = None,
) -> ToolResponse:
    """Create a support ticket for a warranty issue in a single call.

    The tool resolves the product from the customer's ACTIVE warranty when
    `product_id` is omitted, and enforces deterministically that a ticket is only
    created when there is an active warranty — these invariants do not depend on
    the model chaining tools correctly. Flags `requires_human` when the reported
    symptom is electrical/safety-related, per the warranty policy.
    """
    with get_connection() as conn:
        if product_id:
            row = conn.execute(
                "SELECT product_id, end_date FROM warranties "
                "WHERE customer_id = ? AND product_id = ? "
                "ORDER BY end_date DESC LIMIT 1",
                (customer_id, product_id),
            ).fetchone()
        else:
            # No product given: use the customer's most recent warranty.
            row = conn.execute(
                "SELECT product_id, end_date FROM warranties WHERE customer_id = ? "
                "ORDER BY end_date DESC LIMIT 1",
                (customer_id,),
            ).fetchone()

    if row is None:
        return ToolResponse.fail(
            "No encontré una garantía registrada para ese cliente; no puedo crear "
            "un ticket de garantía."
        )
    if _warranty_status(row["end_date"]) != "activa":
        return ToolResponse.fail(
            f"La garantía está vencida (cubrió hasta {row['end_date']}); no es posible "
            "crear un ticket de garantía. Puedo ofrecerte servicio técnico pago como "
            "alternativa."
        )
    product_id = row["product_id"]

    needs_human = any(s in issue_description.lower() for s in _ESCALATION_SIGNALS)
    ticket_id = f"TKT-{uuid.uuid4().hex[:6].upper()}"
    status = "escalado" if needs_human else "abierto"

    with get_connection() as conn:
        conn.execute(
            "INSERT INTO support_tickets "
            "(ticket_id, customer_id, product_id, order_id, issue_description, "
            " status, escalated) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ticket_id, customer_id, product_id, order_id, issue_description,
             status, int(needs_human)),
        )

    return ToolResponse.ok(
        data={
            "ticket_id": ticket_id,
            "status": status,
            "escalated": needs_human,
        },
        message=f"Ticket {ticket_id} creado.",
        # propagate to the agent so it tells the user a human will follow up
    ).model_copy(update={"requires_human": needs_human})
