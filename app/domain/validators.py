"""Deterministic validation of new-customer data.

These rules come straight from the test spec and must be enforced in code, never
delegated to the LLM. The agent may *extract* the fields conversationally, but
whether they are valid is decided here.

    identificacion : 4-11 numeric digits
    nombre_completo: 1-100 chars, letters/spaces/accents/ñ only
    telefono       : exactly 10 digits, starts with 3 or 6
    correo         : valid email, must contain @
"""
from __future__ import annotations

import re

from pydantic import BaseModel

_RE_ID = re.compile(r"^\d{4,11}$")
_RE_NOMBRE = re.compile(r"^[A-Za-zÁÉÍÓÚáéíóúÑñÜü ]{1,100}$")
_RE_TELEFONO = re.compile(r"^[36]\d{9}$")
_RE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FieldError(BaseModel):
    field: str
    message: str


class ValidationResult(BaseModel):
    valid: bool
    errors: list[FieldError] = []

    @property
    def error_map(self) -> dict[str, str]:
        return {e.field: e.message for e in self.errors}


def validate_identificacion(value: str) -> str | None:
    if not _RE_ID.match(value or ""):
        return "La identificación debe tener entre 4 y 11 dígitos numéricos."
    return None


def validate_nombre(value: str) -> str | None:
    if not _RE_NOMBRE.match(value or ""):
        return ("El nombre debe tener entre 1 y 100 caracteres y solo letras, "
                "espacios y tildes.")
    return None


def validate_telefono(value: str) -> str | None:
    if not _RE_TELEFONO.match(value or ""):
        return "El teléfono debe tener exactamente 10 dígitos e iniciar en 3 o 6."
    return None


def validate_correo(value: str) -> str | None:
    if not _RE_CORREO.match(value or ""):
        return "El correo no tiene un formato válido (debe contener @ y dominio)."
    return None


_VALIDATORS = {
    "identificacion": validate_identificacion,
    "nombre_completo": validate_nombre,
    "telefono": validate_telefono,
    "correo": validate_correo,
}


def validate_customer_payload(payload: dict[str, str]) -> ValidationResult:
    """Validate all new-customer fields and collect every error at once."""
    errors: list[FieldError] = []
    for field, validator in _VALIDATORS.items():
        message = validator(payload.get(field, ""))
        if message:
            errors.append(FieldError(field=field, message=message))
    return ValidationResult(valid=not errors, errors=errors)
