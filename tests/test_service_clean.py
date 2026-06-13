"""Pruebas del saneamiento de la salida del modelo (service._clean) y de la
ventana de historial (graph._window). Determinísticas, sin LLM."""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.agent.graph import (
    _window, _MAX_TURNS, _salvage_tool_calls, _fabricated_registration,
    _sanitize_search_args, _user_gave_budget,
)
from app.agent.service import _clean
from app.tools.catalog_tools import _parse_budget


def test_clean_strips_think_block():
    assert _clean("<think>razonando...</think>Hola, ¿en qué te ayudo?") == \
        "Hola, ¿en qué te ayudo?"


def test_clean_strips_leading_json_error_blob():
    raw = (
        '{"error": "No se puede proporcionar información en formato JSON."}\n'
        "Respuesta en texto:\n"
        "Sus datos registrados son: Identificación 1036662704."
    )
    assert _clean(raw) == "Sus datos registrados son: Identificación 1036662704."


def test_clean_strips_fenced_json_block():
    raw = '```json\n{"nombre": "Ana"}\n```\nTus datos: Ana Pérez.'
    assert _clean(raw) == "Tus datos: Ana Pérez."


def test_clean_handles_nested_braces():
    raw = '{"a": {"b": 1}} Tu pedido va en camino.'
    assert _clean(raw) == "Tu pedido va en camino."


def test_clean_keeps_json_only_reply():
    # Si TODA la respuesta es JSON no hay texto que rescatar: mejor no vaciarla.
    raw = '{"error": "formato"}'
    assert _clean(raw) == raw


def test_clean_plain_text_untouched():
    assert _clean("Hola, claro que sí.") == "Hola, claro que sí."


class _FakeBadRequest(Exception):
    """Mimics openai.BadRequestError carrying a Groq tool_use_failed body."""
    def __init__(self, failed_generation: str):
        super().__init__("400 tool_use_failed")
        self.body = {"error": {"code": "tool_use_failed",
                               "failed_generation": failed_generation}}


def test_salvage_recovers_llama_function_syntax():
    exc = _FakeBadRequest(
        'Lo siento, pero puedo buscar para ti.\n'
        '<function=search_products{"category": "laptops", "budget_cop": "400000"}</function>'
    )
    calls = _salvage_tool_calls(exc)
    assert len(calls) == 1
    assert calls[0]["name"] == "search_products"
    assert calls[0]["args"]["category"] == "laptops"
    assert calls[0]["type"] == "tool_call"


def test_salvage_recovers_gt_before_json_variant():
    # Variante con '>' antes del JSON (causó un 400 sin recuperar en checkout sin ID).
    exc = _FakeBadRequest(
        '<function=create_order>{"customer_id": null, "product_id": "tv_002", '
        '"payment_method": "PSE"}</function>'
    )
    calls = _salvage_tool_calls(exc)
    assert len(calls) == 1
    assert calls[0]["name"] == "create_order"
    assert calls[0]["args"]["product_id"] == "tv_002"
    assert calls[0]["args"]["customer_id"] is None


def test_salvage_handles_unicode_args():
    exc = _FakeBadRequest(
        '<function=search_policies{"query": "m\\u00e9todos de pago"}</function>'
    )
    calls = _salvage_tool_calls(exc)
    assert calls[0]["name"] == "search_policies"
    assert "métodos" in calls[0]["args"]["query"]


def test_salvage_recovers_qwen_toolcall_syntax():
    # Qwen shape, with NESTED arguments object (brace-counting must not truncate).
    exc = _FakeBadRequest(
        '<tool_call>\n{"name": "find_customer_by_id", '
        '"arguments": {"identificacion": "87654321"}}\n</tool_call>'
    )
    calls = _salvage_tool_calls(exc)
    assert len(calls) == 1
    assert calls[0]["name"] == "find_customer_by_id"
    assert calls[0]["args"] == {"identificacion": "87654321"}


def test_salvage_returns_empty_when_no_tag():
    assert _salvage_tool_calls(_FakeBadRequest("solo texto, sin función")) == []


# ── Guard contra registro con PII inventada ───────────────────────────────────
_REAL_ARGS = {"identificacion": "55667788", "nombre_completo": "Pedro Ramírez",
              "telefono": "3015556677", "correo": "pedro@mail.com"}


def test_registration_with_user_provided_data_is_allowed():
    user_text = ("mi identificación es 55667788, nombre pedro ramírez, "
                 "teléfono 301 555 6677, correo pedro@mail.com").lower()
    assert _fabricated_registration(_REAL_ARGS, user_text) is False


def test_fabricated_registration_is_blocked():
    # El usuario solo dijo "sí, procedamos" — el modelo inventó todos los datos.
    assert _fabricated_registration(_REAL_ARGS, "sí, procedamos") is True


def test_partial_fabrication_blocked_invented_email():
    user_text = "id 55667788 telefono 3015556677"  # nunca dio correo
    assert _fabricated_registration(_REAL_ARGS, user_text) is True


# ── Guard contra presupuesto inventado ────────────────────────────────────────
def test_invented_budget_is_stripped():
    # El usuario solo pidió ver celulares; el modelo inventó budget_cop.
    out = _sanitize_search_args(
        {"category": "celular", "budget_cop": 5000000}, "que celulares tienen")
    assert out["budget_cop"] is None


def test_real_budget_in_words_is_kept():
    out = _sanitize_search_args(
        {"category": "laptop", "budget_cop": 5000000},
        "necesito un portatil por menos de 5 millones")
    assert out["budget_cop"] == 5000000


def test_no_budget_arg_untouched():
    out = _sanitize_search_args({"category": "celular"}, "que celulares tienen")
    assert "budget_cop" not in out or out.get("budget_cop") is None


def test_budget_hint_not_triggered_by_names_or_common_words():
    # "mil" / "cop" are word-bounded: they must NOT fire inside "Camilo" or "familia",
    # otherwise an invented budget would leak through unstripped.
    assert _user_gave_budget("hola, soy camilo y busco un celular para la familia") is False
    out = _sanitize_search_args(
        {"category": "celular", "budget_cop": 800000},
        "hola, soy camilo y busco un celular para la familia",
    )
    assert out["budget_cop"] is None


def test_budget_hint_fires_on_real_signals():
    assert _user_gave_budget("tengo hasta 2 millones") is True
    assert _user_gave_budget("unos 500 mil pesos") is True


def test_parse_budget_applies_word_multipliers():
    # The classic bug: "5 millones" must not be read as 5.
    assert _parse_budget("5 millones") == 5_000_000
    assert _parse_budget("500 mil") == 500_000
    assert _parse_budget("5000000") == 5_000_000
    assert _parse_budget(3_000_000) == 3_000_000
    assert _parse_budget("null") is None


def _turn(i: int) -> list:
    return [
        HumanMessage(content=f"pregunta {i}"),
        AIMessage(content="", tool_calls=[
            {"name": "search_products", "args": {}, "id": f"call-{i}"}
        ]),
        ToolMessage(content="{}", name="search_products", tool_call_id=f"call-{i}"),
        AIMessage(content=f"respuesta {i}"),
    ]


def test_window_short_history_unchanged():
    msgs = _turn(1) + _turn(2)
    assert _window(msgs) == msgs


def test_window_trims_to_last_turns_at_human_boundary():
    msgs: list = []
    total = _MAX_TURNS + 4
    for i in range(total):
        msgs.extend(_turn(i))
    out = _window(msgs)
    # Empieza exactamente en un mensaje humano (sin ToolMessages huérfanos)...
    assert isinstance(out[0], HumanMessage)
    assert out[0].content == f"pregunta {total - _MAX_TURNS}"
    # ...y conserva los últimos _MAX_TURNS turnos completos.
    assert sum(isinstance(m, HumanMessage) for m in out) == _MAX_TURNS
    assert not isinstance(out[0], ToolMessage)
