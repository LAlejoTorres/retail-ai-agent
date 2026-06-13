"""Warranty tools: coverage check and support-ticket creation.

Warranty validity is DERIVED from end_date vs today on every read, so it can
never drift from a stale status column.
"""
from __future__ import annotations

import uuid
from datetime import date

from app.data.db import get_connection
from app.domain.recommender import get_product
from app.tools.base import ToolResponse

# Symptoms the warranty policy says must go to a human (electrical / safety).
# Stems chosen so paraphrases ("no enciende" / "dejó de encender") all match.
_ESCALATION_SIGNALS = (
    "encend", "enciend", "prend", "no arranca", "quemad", "humo", "chispa",
    "olor a quemado", "se calienta", "sobrecalienta", "hinchad", "explot",
    "descarga", "corto", "no funciona", "muerto", "no responde",
)

# Palabras con que el cliente nombra cada categoría, para resolver de qué producto
# habla cuando tiene varias garantías activas (p. ej. "mi televisor no enciende").
_CATEGORY_KEYWORDS = {
    "televisor": ("televis", "tv", "tele", "pantalla", "smart tv"),
    "laptop": ("portátil", "portatil", "laptop", "computador", "notebook", "pc"),
    "celular": ("celular", "teléfono", "telefono", "móvil", "movil", "smartphone"),
    "accesorio": ("accesorio", "audíf", "audif", "auricular", "cargador", "funda"),
}


def _resolve_product_from_issue(active_pids: list[str], issue: str) -> str | None:
    """Pick the product the issue text refers to, by category keyword. Returns the
    single matching product_id, or None if zero/ambiguous (caller decides)."""
    issue_l = issue.lower()
    matches = [
        pid for pid in active_pids
        if (p := get_product(pid))
        and any(kw in issue_l for kw in _CATEGORY_KEYWORDS.get(p.categoria, ()))
    ]
    return matches[0] if len(matches) == 1 else None


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
    """Create a support ticket for a warranty issue. Only creates one when there is
    an ACTIVE warranty (enforced here, not trusted to the model). Resolves the product
    from the active warranty, or from the issue text when several are active (refusing
    to guess if ambiguous), links the ticket to that warranty's order_id, and flags
    `requires_human` for electrical/safety symptoms.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT warranty_id, product_id, order_id, end_date FROM warranties "
            "WHERE customer_id = ? ORDER BY end_date DESC",
            (customer_id,),
        ).fetchall()

    if product_id:
        rows = [r for r in rows if r["product_id"] == product_id]

    if not rows:
        return ToolResponse.fail(
            "No encontré una garantía registrada para ese cliente; no puedo crear "
            "un ticket de garantía."
        )

    active = [r for r in rows if _warranty_status(r["end_date"]) == "activa"]
    if not active:
        latest = rows[0]
        return ToolResponse.fail(
            f"La garantía está vencida (cubrió hasta {latest['end_date']}); no es "
            "posible crear un ticket de garantía. Puedo ofrecerte servicio técnico "
            "pago como alternativa."
        )

    if product_id:
        product_id = active[0]["product_id"]
    elif len(active) == 1:
        product_id = active[0]["product_id"]
    else:
        # Varias garantías activas: resolvemos el producto por la categoría de la
        # falla; si es ambiguo, no adivinamos (mejor pedir aclaración).
        active_pids = [r["product_id"] for r in active]
        resolved = _resolve_product_from_issue(active_pids, issue_description)
        if resolved is None:
            return ToolResponse.fail(
                "Tienes varias garantías activas y no sé a cuál producto te refieres. "
                "¿Sobre cuál de ellos quieres abrir el caso?"
            )
        product_id = resolved

    # Liga el ticket a la compra: usa el order_id de la garantía resuelta (un order_id
    # explícito del agente tiene prioridad).
    resolved_warranty = next(r for r in active if r["product_id"] == product_id)
    warranty_id = resolved_warranty["warranty_id"]
    order_id = order_id or resolved_warranty["order_id"]

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
            "product_id": product_id,
            "order_id": order_id,
            "warranty_id": warranty_id,
        },
        message=f"Ticket {ticket_id} creado.",
        # propagate to the agent so it tells the user a human will follow up
    ).model_copy(update={"requires_human": needs_human})
