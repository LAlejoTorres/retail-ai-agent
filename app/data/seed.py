"""Idempotently (re)create and seed the SQLite store.

Run:  python -m app.data.seed

Seed data is intentionally shaped so each required scenario has both a clean
"happy path" and an edge case:
  - Sales: laptops that fit / exceed a 5M COP graphic-design budget.
  - Orders: an in-transit order (Ana) and a delivered one (Carlos).
  - Warranty: an ACTIVE warranty (Ana's TV -> ticket + escalation) and an
    EXPIRED one (Carlos's laptop -> graceful rejection).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from app.config import get_settings

CUSTOMERS = [
    # identificacion, nombre, telefono, correo, tipo
    ("12345678", "Ana Pérez", "3001234567", "ana.perez@example.com", "frecuente"),
    ("87654321", "Carlos Gómez", "3107654321", "carlos.gomez@example.com", "frecuente"),
]

ORDERS = [
    # order_id, customer_id, product_id, status, estimated_delivery, address
    ("ORD-1001", "12345678", "tv_001", "en_transito", "2026-06-16",
     "Calle 100 #15-20, Bogotá"),
    ("ORD-1002", "87654321", "laptop_001", "entregado", "2024-08-10",
     "Cra 43A #5-10, Medellín"),
    ("ORD-1003", "12345678", "phone_001", "preparacion", "2026-06-20",
     "Calle 100 #15-20, Bogotá"),
]

WARRANTIES = [
    # warranty_id, customer_id, product_id, order_id, start, end, coverage
    ("WAR-5001", "12345678", "tv_001", "ORD-1001", "2026-05-01", "2027-05-01",
     "Defectos de fábrica y fallas de componentes electrónicos"),
    ("WAR-5002", "87654321", "laptop_001", "ORD-1002", "2024-08-10", "2025-08-10",
     "Defectos de fábrica"),
]


def seed(db_path: Path | None = None) -> Path:
    settings = get_settings()
    db_path = db_path or settings.sqlite_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    schema = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(schema)
        # Fresh seed each run for reproducible demos.
        for table in ("support_tickets", "warranties", "orders", "customers"):
            conn.execute(f"DELETE FROM {table}")

        conn.executemany(
            "INSERT INTO customers "
            "(identificacion, nombre_completo, telefono, correo, tipo) "
            "VALUES (?, ?, ?, ?, ?)",
            CUSTOMERS,
        )
        conn.executemany(
            "INSERT INTO orders "
            "(order_id, customer_id, product_id, status, estimated_delivery, "
            " delivery_address) VALUES (?, ?, ?, ?, ?, ?)",
            ORDERS,
        )
        conn.executemany(
            "INSERT INTO warranties "
            "(warranty_id, customer_id, product_id, order_id, start_date, "
            " end_date, coverage) VALUES (?, ?, ?, ?, ?, ?, ?)",
            WARRANTIES,
        )
        conn.commit()
    finally:
        conn.close()

    return db_path


if __name__ == "__main__":
    path = seed()
    print(f"Seeded SQLite store at {path}")
