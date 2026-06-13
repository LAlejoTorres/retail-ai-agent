"""Customer lookup and registration tools."""
from __future__ import annotations

from app.data.db import get_connection
from app.domain.validators import validate_customer_payload
from app.tools.base import ToolResponse


def find_customer_by_id(identificacion: str) -> ToolResponse:
    """Look up a registered customer by national id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT identificacion, nombre_completo, telefono, correo, tipo "
            "FROM customers WHERE identificacion = ?",
            (identificacion,),
        ).fetchone()

    if row is None:
        return ToolResponse.ok(
            data={"found": False},
            message="No existe un cliente registrado con esa identificación.",
        )
    return ToolResponse.ok(
        data={"found": True, "customer": dict(row)},
        message=f"Cliente encontrado: {row['nombre_completo']}.",
    )


def register_customer(
    identificacion: str, nombre_completo: str, telefono: str, correo: str
) -> ToolResponse:
    """Validate and register a new customer. Validation is deterministic."""
    payload = {
        "identificacion": identificacion,
        "nombre_completo": nombre_completo,
        "telefono": telefono,
        "correo": correo,
    }
    result = validate_customer_payload(payload)
    if not result.valid:
        return ToolResponse.fail(
            message="Datos inválidos. Corrige los campos indicados.",
        ).model_copy(update={"data": {"errors": result.error_map}})

    with get_connection() as conn:
        exists = conn.execute(
            "SELECT 1 FROM customers WHERE identificacion = ?", (identificacion,)
        ).fetchone()
        if exists:
            return ToolResponse.fail(
                "Esa identificación ya está registrada. Si eres tú, podemos "
                "validarte como cliente frecuente."
            )
        conn.execute(
            "INSERT INTO customers "
            "(identificacion, nombre_completo, telefono, correo, tipo) "
            "VALUES (?, ?, ?, ?, 'nuevo')",
            (identificacion, nombre_completo, telefono, correo),
        )

    return ToolResponse.ok(
        data={"customer": {**payload, "tipo": "nuevo"}},
        message=f"Cliente {nombre_completo} registrado correctamente.",
    )
