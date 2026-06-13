"""Catalog tools: search (deterministic recommender), details, comparison."""
from __future__ import annotations

import re

from app.domain.recommender import get_product, recommend
from app.tools.base import ToolResponse


def _parse_budget(value: int | str | None) -> int | None:
    """Tolerate budgets some models emit as strings, applying word multipliers so
    '5 millones' -> 5_000_000 and '500 mil' -> 500_000 (a naive digit grab would
    read those as 5 and 500). Plain numerics ('5000000', '1.500.000') pass through."""
    if value is None or isinstance(value, int):
        return value
    text = str(value).lower()
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    amount = int(digits)
    if "mill" in text:
        amount *= 1_000_000
    elif re.search(r"\bmil\b", text):
        amount *= 1_000
    return amount


def search_products(
    category: str | None = None,
    budget_cop: int | str | None = None,
    use_case: str | None = None,
) -> ToolResponse:
    """Search the catalog by category, budget and use case.

    Returns real, in-budget, ranked products with the reasons behind the ranking.
    The agent must recommend ONLY from this list.
    """
    results = recommend(
        category=category, budget_cop=_parse_budget(budget_cop), use_case=use_case
    )
    if not results:
        return ToolResponse.ok(
            data={"products": [], "total_found": 0},
            message="No hay productos que cumplan esos criterios en el catálogo.",
        )
    products = [
        {
            "product_id": s.product.product_id,
            "nombre": s.product.nombre,
            "precio_cop": s.product.precio_cop,
            "marca": s.product.marca,
            "specs": s.product.specs,
            "stock": s.product.stock,
            "match_reasons": s.reasons,
        }
        for s in results
    ]
    return ToolResponse.ok(
        data={"products": products, "total_found": len(products), "source": "catalog"},
        message=f"Se encontraron {len(products)} opciones.",
    )


def get_product_details(product_id: str) -> ToolResponse:
    """Full details for a single product."""
    p = get_product(product_id)
    if p is None:
        return ToolResponse.fail("Ese producto no existe en el catálogo.")
    return ToolResponse.ok(data={"product": p.model_dump()})


def compare_products(product_ids: list[str]) -> ToolResponse:
    """Compare 2+ products side by side on price and key specs."""
    products = [get_product(pid) for pid in product_ids]
    missing = [pid for pid, p in zip(product_ids, products) if p is None]
    if missing:
        return ToolResponse.fail(
            f"Estos productos no existen en el catálogo: {', '.join(missing)}."
        )
    comparison = [
        {
            "product_id": p.product_id,
            "nombre": p.nombre,
            "precio_cop": p.precio_cop,
            "specs": p.specs,
        }
        for p in products
    ]
    return ToolResponse.ok(data={"comparison": comparison})
