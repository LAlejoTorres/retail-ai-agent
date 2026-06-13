"""Tool-layer behavior against the seeded store."""
from __future__ import annotations

from app.agent.toolset import _coerce_args
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


def test_address_change_blocked_after_shipping():
    # ORD-1001 is en_transito -> cannot change address, must escalate.
    resp = order_tools.update_delivery_address("ORD-1001", "Otra dirección 123")
    assert resp.success is False
    assert resp.requires_human is True
