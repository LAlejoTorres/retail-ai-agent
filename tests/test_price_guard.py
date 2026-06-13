"""Tests del guard determinista de precios (red anti-alucinación).

Cubre el caso real observado (un dígito cambiado al re-escribir un precio del
catálogo) y los límites: no adivinar, no tocar números que no son precios.
"""
from __future__ import annotations

from app.agent.price_guard import (
    collect_grounded_ids,
    collect_grounded_prices,
    correct_ids,
    correct_prices,
)

GROUNDED = {1699000, 4299000}


def test_corrige_sustitucion_de_un_digito():
    # 1.699.900 -> 1.699.000 (el dígito de las centenas de mil cambiado)
    out, fixes = correct_prices("El Galaxy A55 cuesta $1.699.900.", GROUNDED)
    assert "$1.699.000" in out
    assert fixes == [(1699900, 1699000)]


def test_corrige_transposicion_adyacente():
    # 4.299.000 -> 4.929.000 (dos dígitos adyacentes intercambiados)
    out, fixes = correct_prices("Precio: 4.929.000 COP", GROUNDED)
    assert "4.299.000" in out
    assert fixes == [(4929000, 4299000)]


def test_no_toca_precio_correcto():
    out, fixes = correct_prices("Vale $1.699.000.", GROUNDED)
    assert out == "Vale $1.699.000."
    assert fixes == []


def test_no_adivina_si_no_hay_cercano():
    # 9.999.999 no está cerca (más de un dígito) de ningún precio real.
    out, fixes = correct_prices("Cuesta 9.999.999 pesos.", GROUNDED)
    assert "9.999.999" in out
    assert fixes == []


def test_no_corrige_si_es_ambiguo():
    # 1.234.000 está a un dígito de dos precios -> no se toca.
    grounded = {1234001, 1234002}
    out, fixes = correct_prices("Son 1.234.000.", grounded)
    assert "1.234.000" in out
    assert fixes == []


def test_preserva_estilo_separador_y_dolar():
    out, _ = correct_prices("1,699,900", {1699000})
    assert out == "1,699,000"  # mantiene la coma como separador
    out2, _ = correct_prices("$1699900", {1699000})
    assert out2 == "$1699000"  # sin agrupar y con $


def test_ignora_numeros_que_no_son_precios():
    # Teléfono (sin separadores ni $) y un año: no deben tocarse.
    text = "Tu teléfono 3001234567 y el año 2026 siguen igual."
    out, fixes = correct_prices(text, GROUNDED)
    assert out == text
    assert fixes == []


def test_noop_sin_precios_verificables():
    out, fixes = correct_prices("Cuesta $1.699.900.", set())
    assert out == "Cuesta $1.699.900."
    assert fixes == []


def test_collect_grounded_prices_anidado():
    data = {
        "products": [
            {"product_id": "p1", "precio_cop": 1699000, "stock": 5},
            {"product_id": "p2", "precio_cop": 4299000},
        ],
        "total": 5998000,
    }
    assert collect_grounded_prices(data) == {1699000, 4299000, 5998000}


def test_collect_ignora_booleans_y_no_precios():
    data = {"escalated": True, "ram_gb": 8, "precio_cop": 1699000}
    assert collect_grounded_prices(data) == {1699000}


# ── Guard de IDs de referencia ────────────────────────────────────────────────
def test_corrige_ticket_id_mal_citado():
    # El modelo cita un TKT distinto al que devolvió la herramienta -> se corrige.
    out, fixes = correct_ids("Tu ticket es TKT-390EA4.", {"TKT-45D298"})
    assert out == "Tu ticket es TKT-45D298."
    assert fixes == [("TKT-390EA4", "TKT-45D298")]


def test_no_toca_id_correcto():
    out, fixes = correct_ids("Pedido ORD-1001 en camino.", {"ORD-1001"})
    assert out == "Pedido ORD-1001 en camino." and fixes == []


def test_no_corrige_id_si_hay_varios_del_mismo_prefijo():
    # Dos órdenes válidas -> no se puede saber a cuál se refería: no se toca.
    out, fixes = correct_ids("Pedido ORD-9999.", {"ORD-1001", "ORD-1002"})
    assert "ORD-9999" in out and fixes == []


def test_no_inventa_id_de_prefijo_sin_evidencia():
    # No hay ningún TKT en evidencia -> no se corrige (no fabricamos).
    out, fixes = correct_ids("Ticket TKT-ABCDEF.", {"ORD-1001"})
    assert "TKT-ABCDEF" in out and fixes == []


def test_collect_grounded_ids_anidado():
    data = {"ticket_id": "TKT-45D298", "order_id": "ORD-1001",
            "extra": ["WAR-5001"]}
    assert collect_grounded_ids(data) == {"TKT-45D298", "ORD-1001", "WAR-5001"}
