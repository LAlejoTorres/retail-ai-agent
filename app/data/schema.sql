-- Transactional store for the retail agent.
-- Products live in products.json (static catalog); everything that changes
-- per customer/interaction lives here.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    identificacion   TEXT PRIMARY KEY,           -- 4-11 digits
    nombre_completo  TEXT NOT NULL,
    telefono         TEXT NOT NULL,              -- 10 digits, starts with 3 or 6
    correo           TEXT NOT NULL,
    tipo             TEXT NOT NULL DEFAULT 'frecuente',  -- 'frecuente' | 'nuevo'
    created_at       TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orders (
    order_id            TEXT PRIMARY KEY,
    customer_id         TEXT NOT NULL REFERENCES customers(identificacion),
    product_id          TEXT NOT NULL,
    status              TEXT NOT NULL,           -- preparacion | en_transito | entregado | retrasado
    estimated_delivery  TEXT,                    -- ISO date
    delivery_address    TEXT NOT NULL,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS warranties (
    warranty_id   TEXT PRIMARY KEY,
    customer_id   TEXT NOT NULL REFERENCES customers(identificacion),
    product_id    TEXT NOT NULL,
    order_id      TEXT REFERENCES orders(order_id),
    start_date    TEXT NOT NULL,                 -- ISO date
    end_date      TEXT NOT NULL,                 -- ISO date
    coverage      TEXT NOT NULL
    -- status is DERIVED from end_date vs today, never trusted from a column.
);

CREATE TABLE IF NOT EXISTS support_tickets (
    ticket_id          TEXT PRIMARY KEY,
    customer_id        TEXT NOT NULL REFERENCES customers(identificacion),
    product_id         TEXT,
    order_id           TEXT,
    issue_description  TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'abierto',  -- abierto | escalado | cerrado
    escalated          INTEGER NOT NULL DEFAULT 0,
    created_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_warranties_customer ON warranties(customer_id);
CREATE INDEX IF NOT EXISTS idx_tickets_customer ON support_tickets(customer_id);
