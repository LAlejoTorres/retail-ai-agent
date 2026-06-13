"""Tool-layer behavior against the seeded store."""
from __future__ import annotations

from app.agent.toolset import _coerce_args
from app.data.db import get_connection
from app.data.seed import seed
from app.tools import catalog_tools, customer_tools, order_tools, warranty_tools


def test_nullish_strings_coerced_to_none():
    # Models (esp. via strict providers) sometimes emit "null"/"none" strings.
    args = _coerce_args({"category": "celular", "budget_cop": "null", "use_case": "NONE"})
    assert args["budget_cop"] is None
    assert args["use_case"] is None
    assert args["category"] == "celular"


def test_search_products_tolerates_string_budget():
    # Budget arriving as a string must not crash and must still filter.
    resp = catalog_tools.search_products(category="laptop", budget_cop="5000000")
    assert resp.success is True
    assert all(p["precio_cop"] <= 5000000 for p in resp.data["products"])


def test_find_existing_and_missing_customer():
    assert customer_tools.find_customer_by_id("12345678").data["found"] is True
    assert customer_tools.find_customer_by_id("00000000").data["found"] is False


def test_register_rejects_invalid_data():
    resp = customer_tools.register_customer("12", "Ana123", "700", "bad")
    assert resp.success is False
    assert "errors" in resp.data


def test_order_status_requires_an_identifier():
    assert order_tools.get_order_status().success is False


def test_order_status_by_id():
    resp = order_tools.get_order_status(order_id="ORD-1001")
    assert resp.data["status"] == "en_transito"


def test_warranty_status_is_derived_from_dates():
    active = warranty_tools.check_warranty("12345678", "tv_001")
    expired = warranty_tools.check_warranty("87654321", "laptop_001")
    assert active.data["status"] == "activa"
    assert expired.data["status"] == "vencida"


def test_electrical_fault_ticket_escalates():
    resp = warranty_tools.create_warranty_ticket(
        "12345678", "El televisor dejó de encender", product_id="tv_001"
    )
    assert resp.requires_human is True
    assert resp.data["escalated"] is True


def test_ticket_rejected_for_expired_warranty():
    # Carlos's laptop warranty is expired -> ticket creation must be refused.
    resp = warranty_tools.create_warranty_ticket(
        "87654321", "No enciende", product_id="laptop_001"
    )
    assert resp.success is False


def test_ticket_resolves_product_from_active_warranty():
    # No product_id given: tool resolves it from the customer's active warranty.
    resp = warranty_tools.create_warranty_ticket("12345678", "No enciende")
    assert resp.success is True
    assert resp.data["ticket_id"]


def test_ticket_is_linked_to_the_purchase_order():
    # Regresión: el ticket debe quedar trazable al pedido real. La garantía de Ana
    # (WAR-5001 -> ORD-1001) es la prueba de compra; el order_id NO debe quedar vacío.
    seed()
    resp = warranty_tools.create_warranty_ticket(
        "12345678", "El televisor dejó de encender"
    )
    assert resp.success is True
    assert resp.data["order_id"] == "ORD-1001"
    with get_connection() as c:
        row = c.execute(
            "SELECT order_id, product_id FROM support_tickets WHERE ticket_id = ?",
            (resp.data["ticket_id"],),
        ).fetchone()
    assert row["order_id"] == "ORD-1001"   # persistido, no NULL
    assert row["product_id"] == "tv_001"


def test_ticket_resolves_right_product_among_multiple_active_warranties():
    # Ana has an active TV warranty (seed). A purchase adds an active PHONE warranty.
    # "mi televisor no enciende" (no product_id) must NOT attach to the new phone.
    seed()  # isolate: start from baseline (Ana -> only the TV warranty active)
    order_tools.create_order("12345678", "phone_001", payment_method="tarjeta_credito")
    resp = warranty_tools.create_warranty_ticket(
        "12345678", "Mi televisor dejó de encender"
    )
    assert resp.success is True
    # The ticket landed on the TV, resolved from the issue text — not the phone.
    with get_connection() as c:
        row = c.execute(
            "SELECT product_id FROM support_tickets WHERE ticket_id = ?",
            (resp.data["ticket_id"],),
        ).fetchone()
    assert row["product_id"] == "tv_001"


def test_ticket_ambiguous_when_multiple_active_and_no_category_hint():
    # Two active warranties + an issue text that names no category -> refuse to guess.
    seed()
    order_tools.create_order("12345678", "phone_001", payment_method="tarjeta_credito")
    resp = warranty_tools.create_warranty_ticket("12345678", "No enciende")
    assert resp.success is False


def test_create_order_rejects_missing_or_unknown_payment_method():
    # Payment is a hard rule: no method / an invented one must not create an order.
    seed()
    assert order_tools.create_order("12345678", "phone_001").success is False
    assert order_tools.create_order(
        "12345678", "phone_001", payment_method="bitcoin"
    ).success is False


def test_create_order_accepts_natural_payment_phrasing():
    # Regresión: "tarjeta de crédito" (con "de" y tilde) es una opción ofrecida y
    # debe aceptarse, no solo la forma canónica "tarjeta_credito".
    seed()
    for phrasing in ("tarjeta de crédito", "Tarjeta de Credito", "pago con PSE"):
        resp = order_tools.create_order("12345678", "phone_001", payment_method=phrasing)
        assert resp.success is True, phrasing
        assert resp.data["payment_link"].startswith("https://")


def test_create_order_creates_order_and_warranty_with_link():
    # Ana (frequent) buys a phone with credit card -> order + warranty + payment link.
    resp = order_tools.create_order("12345678", "phone_001", payment_method="tarjeta_credito")
    assert resp.success is True
    assert resp.data["order_id"].startswith("ORD-")
    assert resp.data["warranty_id"].startswith("WAR-")
    assert resp.data["payment_link"].startswith("https://")
    # The new order is now trackable and the warranty is active.
    status = order_tools.get_order_status(order_id=resp.data["order_id"])
    assert status.data["status"] == "preparacion"
    war = warranty_tools.check_warranty("12345678", "phone_001")
    assert war.data["status"] == "activa"


def test_create_order_cash_on_delivery_has_no_link():
    resp = order_tools.create_order("12345678", "phone_001", payment_method="contra_entrega")
    assert resp.success is True
    assert "payment_link" not in resp.data


def test_create_order_rejects_unregistered_customer():
    assert order_tools.create_order("00000000", "phone_001").success is False


def test_create_order_rejects_unknown_product():
    assert order_tools.create_order("12345678", "nope_999").success is False


def test_address_change_blocked_after_shipping():
    # ORD-1001 is en_transito -> cannot change address, must escalate.
    resp = order_tools.update_delivery_address(
        "ORD-1001", "Otra dirección 123", customer_id="12345678"
    )
    assert resp.success is False
    assert resp.requires_human is True


def test_address_change_requires_order_ownership():
    # ORD-1003 está en preparación (mutable) pero pertenece a 12345678: otra
    # identificación no puede cambiar la dirección (anti-IDOR).
    resp = order_tools.update_delivery_address(
        "ORD-1003", "Calle Falsa 123", customer_id="87654321"
    )
    assert resp.success is False
    assert resp.requires_human is False
