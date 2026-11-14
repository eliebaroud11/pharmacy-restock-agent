"""SQLite storage for stock, suppliers, orders and the audit log.

This stands in for the pharmacy's real management system for now.
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(os.environ.get("PHARMA_DB", Path(__file__).resolve().parent.parent / "pharmacy.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS suppliers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    contact TEXT
);
CREATE TABLE IF NOT EXISTS medicines (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    min_stock INTEGER NOT NULL,
    target_stock INTEGER NOT NULL,
    supplier_id INTEGER REFERENCES suppliers(id)
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY,
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    batch_no TEXT NOT NULL,
    expiry TEXT NOT NULL,           -- YYYY-MM-DD
    qty INTEGER NOT NULL,
    order_id INTEGER REFERENCES orders(id)
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    supplier_id INTEGER NOT NULL REFERENCES suppliers(id),
    status TEXT NOT NULL,           -- draft | pending_delivery | received | needs_review | cancelled
    reason TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    received_at TEXT
);
CREATE TABLE IF NOT EXISTS order_lines (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders(id),
    medicine_id INTEGER NOT NULL REFERENCES medicines(id),
    qty INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,            -- 'agent' or the pharmacist's name
    action TEXT NOT NULL,
    details TEXT
);
"""


def connect(path=None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(conn, actor: str, action: str, details=None) -> None:
    conn.execute(
        "INSERT INTO audit_log (at, actor, action, details) VALUES (?, ?, ?, ?)",
        (now(), actor, action, json.dumps(details, ensure_ascii=False) if details is not None else None),
    )


def stock_summary(conn):
    """One row per medicine with total quantity and nearest expiry."""
    return conn.execute(
        """
        SELECT m.id, m.name, m.min_stock, m.target_stock, s.name AS supplier,
               COALESCE(SUM(b.qty), 0) AS qty,
               MIN(CASE WHEN b.qty > 0 THEN b.expiry END) AS nearest_expiry
        FROM medicines m
        LEFT JOIN suppliers s ON s.id = m.supplier_id
        LEFT JOIN batches b ON b.medicine_id = m.id
        GROUP BY m.id ORDER BY m.name
        """
    ).fetchall()


def order_with_lines(conn, order_id: int):
    order = conn.execute(
        "SELECT o.*, s.name AS supplier, s.contact FROM orders o JOIN suppliers s ON s.id = o.supplier_id WHERE o.id = ?",
        (order_id,),
    ).fetchone()
    if order is None:
        return None, []
    lines = conn.execute(
        "SELECT ol.medicine_id, m.name, ol.qty FROM order_lines ol JOIN medicines m ON m.id = ol.medicine_id WHERE ol.order_id = ? ORDER BY m.name",
        (order_id,),
    ).fetchall()
    return order, lines
