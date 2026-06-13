"""Deterministic customer-validation rules (test spec section 2)."""
from __future__ import annotations

import pytest

from app.domain.validators import validate_customer_payload

VALID = {
    "identificacion": "12345678",
    "nombre_completo": "Ana Pérez",
    "telefono": "3001234567",
    "correo": "ana.perez@example.com",
}


def test_valid_payload_passes():
    assert validate_customer_payload(VALID).valid


@pytest.mark.parametrize(
    "field,bad_value",
    [
        ("identificacion", "12"),          # too short
        ("identificacion", "123456789012"),  # too long
        ("identificacion", "12ab"),         # non-numeric
        ("nombre_completo", "Ana123"),      # digits not allowed
        ("telefono", "7001234567"),         # must start with 3 or 6
        ("telefono", "300123456"),          # only 9 digits
        ("correo", "ana.perez.example.com"),  # missing @
    ],
)
def test_invalid_field_is_rejected(field, bad_value):
    payload = {**VALID, field: bad_value}
    result = validate_customer_payload(payload)
    assert not result.valid
    assert field in result.error_map


def test_all_errors_collected_at_once():
    result = validate_customer_payload(
        {"identificacion": "x", "nombre_completo": "", "telefono": "1", "correo": "x"}
    )
    assert set(result.error_map) == {
        "identificacion", "nombre_completo", "telefono", "correo"
    }
