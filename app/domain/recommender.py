"""Deterministic catalog filtering + ranking. The LLM passes structured criteria
and only justifies the result; it never picks products from raw data (which could
hallucinate SKUs/specs). Scoring: a use-case profile + a stock and budget nudge.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel

from app.config import get_settings

_GRAPHIC_GPU_KEYWORDS = ("rtx", "radeon", "apple m")

# Map the many ways users/models name a category to our canonical catalog value.
_CATEGORY_SYNONYMS = {
    "laptop": "laptop", "laptops": "laptop", "portatil": "laptop",
    "portátil": "laptop", "portatiles": "laptop", "portátiles": "laptop",
    "notebook": "laptop", "computador": "laptop", "computadora": "laptop",
    "computador portatil": "laptop",
    "televisor": "televisor", "televisores": "televisor", "tv": "televisor",
    "tele": "televisor", "smart tv": "televisor",
    "celular": "celular", "celulares": "celular", "telefono": "celular",
    "teléfono": "celular", "smartphone": "celular", "movil": "celular",
    "accesorio": "accesorio", "accesorios": "accesorio",
}


def _canonical_category(category: str | None) -> str | None:
    if not category:
        return None
    return _CATEGORY_SYNONYMS.get(category.strip().lower(), category.strip().lower())


class Product(BaseModel):
    product_id: str
    nombre: str
    categoria: str
    precio_cop: int
    marca: str
    specs: dict
    use_cases: list[str]
    stock: int


class ScoredProduct(BaseModel):
    product: Product
    score: float
    reasons: list[str]


@lru_cache
def _load_catalog() -> list[Product]:
    path: Path = get_settings().products_path
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [Product(**p) for p in raw]


def get_product(product_id: str) -> Product | None:
    return next((p for p in _load_catalog() if p.product_id == product_id), None)


def _score_graphic_design(p: Product) -> tuple[float, list[str]]:
    score, reasons = 0.0, []
    gpu = str(p.specs.get("gpu", "")).lower()
    ram = int(p.specs.get("ram_gb", 0) or 0)
    pantalla = str(p.specs.get("pantalla", "")).lower()

    if any(k in gpu for k in _GRAPHIC_GPU_KEYWORDS) and "integrada" not in gpu:
        score += 3
        reasons.append("GPU dedicada para acelerar render y edición")
    if ram >= 16:
        score += 2
        reasons.append(f"{ram}GB de RAM para trabajar con archivos pesados")
    if "oled" in pantalla or "srgb" in pantalla or "dci-p3" in pantalla:
        score += 2
        reasons.append("pantalla con buena fidelidad de color")
    return score, reasons


# Registry of use-case scorers. Extend by adding a profile here.
_PROFILES = {
    "diseño gráfico": _score_graphic_design,
    "diseno grafico": _score_graphic_design,
}


def recommend(
    *,
    category: str | None = None,
    budget_cop: int | None = None,
    use_case: str | None = None,
    limit: int = 3,
) -> list[ScoredProduct]:
    """Return up to `limit` real, in-budget products ranked for the use case."""
    candidates = _load_catalog()

    canonical = _canonical_category(category)
    if canonical:
        candidates = [p for p in candidates if p.categoria == canonical]
    if budget_cop is not None:
        candidates = [p for p in candidates if p.precio_cop <= budget_cop]

    # Use case is not a hard filter: it drives ranking via the scorer below, so a
    # near-miss product can still surface as an alternative instead of vanishing.
    scorer = _PROFILES.get((use_case or "").lower())
    scored: list[ScoredProduct] = []
    for p in candidates:
        base, reasons = (scorer(p) if scorer else (0.0, []))
        # Tie-breakers: in-stock availability and lower price as a mild nudge.
        nudge = (0.5 if p.stock > 0 else -5) - p.precio_cop / 1e9
        scored.append(ScoredProduct(product=p, score=base + nudge, reasons=reasons))

    scored.sort(key=lambda s: s.score, reverse=True)
    return scored[:limit]
