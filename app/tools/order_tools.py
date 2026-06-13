"""Order tools: checkout/order creation, status, estimated delivery, address change."""
from __future__ import annotations

import unicodedata
import uuid
from datetime import date, timedelta

from app.data.db import get_connection
from app.domain.recommender import get_product
from app.tools.base import ToolResponse

# Address may only change while the order has not shipped (see envios policy).
_MUTABLE_STATUSES = {"preparacion"}


def _resolve_payment(method: str | None) -> tuple[str, bool] | None:
    """Mapea un método de pago en lenguaje libre a (etiqueta, ¿requiere enlace?).
    Tolera frases y tildes: "tarjeta de crédito" == "tarjeta_credito". Card/PSE usan
    enlace seguro; contra entrega no. NUNCA se reciben datos de tarjeta. None si no
    se reconoce."""
    if not method:
        return None
    t = unicodedata.normalize("NFKD", method).encode("ascii", "ignore").decode().lower()
    if "pse" in t:
        return "PSE", True
    if "credito" in t:
        return "tarjeta de crédito", True
    if "debito" in t:
        return "tarjeta de débito", True
    if any(w in t for w in ("contra", "entrega", "efectivo")):
        return "pago contra entrega", False
    if "tarjeta" in t:
        return "tarjeta", True
    return None


def create_order(
    customer_id: str,
    product_id: str,
    payment_method: str | None = None,
    delivery_address: str | None = None,
) -> ToolResponse:
    """Crea el pedido y le adjunta una garantía de fábrica. Para tarjeta/PSE devuelve
    un enlace de pago seguro (mock); nunca maneja datos de tarjeta. El cliente debe
    existir y el producto estar en stock."""
    with get_connection() as conn:
        cust = conn.execute(
            "SELECT identificacion FROM customers WHERE identificacion = ?",
            (customer_id,),
        ).fetchone()
    if cust is None:
        return ToolResponse.fail(
            "El cliente debe estar registrado antes de comprar. Regístralo primero."
        )

    product = get_product(product_id)
    if product is None:
        return ToolResponse.fail(
            "Ese producto no existe en el catálogo; no puedo crear el pedido."
        )
    if product.stock <= 0:
        return ToolResponse.fail(f"El {product.nombre} está agotado por ahora.")

    # El método de pago es una regla de negocio: se valida aquí, no en el prompt.
    resolved = _resolve_payment(payment_method)
    if resolved is None:
        return ToolResponse.fail(
            "Necesito un método de pago válido para crear el pedido: tarjeta de "
            "crédito, tarjeta de débito, PSE o pago contra entrega."
        )
    method_label, needs_link = resolved

    order_id = f"ORD-{uuid.uuid4().hex[:4].upper()}"
    warranty_id = f"WAR-{uuid.uuid4().hex[:4].upper()}"
    est = (date.today() + timedelta(days=5)).isoformat()
    start = date.today().isoformat()
    end = (date.today() + timedelta(days=365)).isoformat()

    with get_connection() as conn:
        if not delivery_address:
            prev = conn.execute(
                "SELECT delivery_address FROM orders WHERE customer_id = ? "
                "ORDER BY updated_at DESC LIMIT 1",
                (customer_id,),
            ).fetchone()
            delivery_address = prev["delivery_address"] if prev else "Por confirmar"
        conn.execute(
            "INSERT INTO orders (order_id, customer_id, product_id, status, "
            "estimated_delivery, delivery_address) VALUES (?, ?, ?, 'preparacion', ?, ?)",
            (order_id, customer_id, product_id, est, delivery_address),
        )
        conn.execute(
            "INSERT INTO warranties (warranty_id, customer_id, product_id, order_id, "
            "start_date, end_date, coverage) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (warranty_id, customer_id, product_id, order_id, start, end,
             "Garantía de fábrica (1 año)"),
        )

    data = {
        "order_id": order_id,
        "product_id": product_id,
        "product_name": product.nombre,
        "precio_cop": product.precio_cop,
        "payment_method": method_label,
        "estimated_delivery": est,
        "delivery_address": delivery_address,
        "warranty_id": warranty_id,
    }
    # Card/PSE -> secure payment link (mock). Cash on delivery -> no link.
    if needs_link:
        data["payment_link"] = f"https://pago.tecni.co/checkout/{uuid.uuid4().hex[:10]}"
    return ToolResponse.ok(data=data, message=f"Pedido {order_id} creado.")


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


def update_delivery_address(
    order_id: str, new_address: str, customer_id: str
) -> ToolResponse:
    """Change the delivery address. Requires the customer's id (must own the
    order) and is allowed only before the order ships."""
    if not customer_id:
        return ToolResponse.fail(
            "Para cambiar la dirección necesito la identificación del titular "
            "del pedido."
        )
    with get_connection() as conn:
        row = conn.execute(
            "SELECT status, customer_id FROM orders WHERE order_id = ?", (order_id,)
        ).fetchone()
        if row is None:
            return ToolResponse.fail("No encontré ese pedido.")
        if row["customer_id"] != str(customer_id):
            # Titularidad: nadie cambia la dirección de un pedido ajeno (anti-IDOR).
            return ToolResponse.fail(
                "La identificación no coincide con el titular del pedido; no "
                "puedo cambiar la dirección."
            )
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
