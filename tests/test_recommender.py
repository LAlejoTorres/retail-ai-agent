"""Deterministic catalog filtering/ranking (scenario 1 backbone)."""
from __future__ import annotations

from app.domain.recommender import recommend


def test_budget_filter_excludes_over_budget():
    results = recommend(category="laptop", budget_cop=5000000, use_case="diseño gráfico")
    ids = {r.product.product_id for r in results}
    # MacBook Air M2 (5.899M) is over budget and must not appear.
    assert "laptop_005" not in ids
    assert all(r.product.precio_cop <= 5000000 for r in results)


def test_graphic_design_prefers_dedicated_gpu():
    results = recommend(category="laptop", budget_cop=5000000, use_case="diseño gráfico")
    top = results[0].product
    # Top pick must have a dedicated GPU (not integrated).
    assert "integrada" not in str(top.specs["gpu"]).lower()


def test_category_synonyms_resolve():
    # "portátiles" must resolve to the canonical "laptop" category.
    assert recommend(category="portátiles", budget_cop=5000000) != []


def test_no_match_returns_empty():
    assert recommend(category="televisor", budget_cop=100000) == []
