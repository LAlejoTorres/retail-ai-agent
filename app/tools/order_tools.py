"""Order tools: status, estimated delivery, address change."""
from __future__ import annotations

from app.data.db import get_connection
from app.tools.base import ToolResponse

# Address may only change while the order has not shipped (see envios policy).
_MUTABLE_STATUSES = {"preparacion"}


def _fetch_order(conn, order_id: str | None, customer_id: str | None):
    if order_id:
        return conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
    if customer_id:
        # Most recent order for the customer.
        return conn.execute(
            "SELECT * FROM orders WHERE customer_id = ? "
            "ORDER BY updated_at DESC, order_id DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
    return None


def get_order_status(
    order_id: str | None = None, customer_id: str | None = None
) -> ToolResponse:
    """Get an order's current status. Needs an order_id or a customer_id."""
    if not order_id and not customer_id:
        return ToolResponse.fail(
            "Necesito tu número de pedido o tu identificación para consultarlo."
        )
    with get_connection() as conn:
        row = _fetch_order(conn, order_id, customer_id)
    if row is None:
        return ToolResponse.ok(
            data={"found": False},
            message="No encontré un pedido con esos datos.",
        )
    return ToolResponse.ok(
        data={
            "found": True,
            "order_id": row["order_id"],
            "status": row["status"],
            "estimated_delivery": row["estimated_delivery"],
            "delivery_address": row["delivery_address"],
        },
        message=f"Pedido {row['order_id']}: estado '{row['status']}'.",
    )


def get_estimated_delivery(order_id: str) -> ToolResponse:
    """Estimated delivery date for an order."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT order_id, status, estimated_delivery FROM orders "
            "WHERE order_id = ?",
            (order_id,),
        ).fetchone()
    if row is None:
        return ToolResponse.fail("No encontré ese pedido.")
    return ToolResponse.ok(
        data={
            "order_id": row["order_id"],
            "status": row["status"],
            "estimated_delivery": row["estimated_delivery"],
        }
    )


def update_delivery_address(order_id: str, new_address: str) -> ToolResponse:
    """Change the delivery address. Allowed only before the order ships."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            return ToolResponse.fail("No encontré ese pedido.")
        if row["status"] not in _MUTABLE_STATUSES:
            return ToolResponse.fail(
                "El pedido ya salió de bodega; no puedo cambiar la dirección por "
                "este canal. Lo escalo a un asesor.",
                requires_human=True,
            )
        conn.execute(
            "UPDATE orders SET delivery_address = ?, "
            "updated_at = datetime('now') WHERE order_id = ?",
            (new_address, order_id),
        )
    return ToolResponse.ok(
        data={"order_id": order_id, "delivery_address": new_address},
        message="Dirección de entrega actualizada.",
    )
