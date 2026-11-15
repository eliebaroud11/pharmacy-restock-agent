"""Add medicines and suppliers from the app (e.g. when the judges bring an invoice with new products)."""
import re
from datetime import date

from .db import log

MAX_STOCK_LEVEL = 100_000
_PHONE = re.compile(r"^\+?[\d\s-]{8,20}$")
_EMAIL = re.compile(r"^[\w.+-]+@[\w-]+(\.[\w-]+)+$")


class CatalogError(ValueError):
    pass


def _int(v, name, lo=0, hi=MAX_STOCK_LEVEL):
    try:
        v = int(v)
    except (TypeError, ValueError):
        raise CatalogError(f"{name} must be a whole number.")
    if not lo <= v <= hi:
        raise CatalogError(f"{name} must be between {lo} and {hi}.")
    return v


def add_supplier(conn, name: str, contact: str, actor: str) -> int:
    name, contact = (name or "").strip(), (contact or "").strip()
    if not 2 <= len(name) <= 80:
        raise CatalogError("Supplier name must be 2 to 80 characters.")
    if contact and not (_PHONE.match(contact) or _EMAIL.match(contact)):
        raise CatalogError("Contact must be a phone number (e.g. +961 1 234 567) or an email address.")
    if conn.execute("SELECT 1 FROM suppliers WHERE lower(name) = lower(?)", (name,)).fetchone():
        raise CatalogError("A supplier with that name already exists.")
    cur = conn.execute("INSERT INTO suppliers (name, contact) VALUES (?, ?)", (name, contact or None))
    log(conn, actor, "added supplier", {"name": name})
    conn.commit()
    return cur.lastrowid


def add_medicine(conn, name: str, supplier_id: int, min_stock, target_stock, actor: str,
                 opening_qty=0, opening_batch="", opening_expiry=None) -> int:
    name = " ".join((name or "").split())
    if not 3 <= len(name) <= 80:
        raise CatalogError("Medicine name must be 3 to 80 characters (include strength and pack, e.g. 'Aspirin 100mg tabs (30)').")
    min_stock = _int(min_stock, "Minimum stock")
    target_stock = _int(target_stock, "Target stock", lo=1)
    if target_stock < min_stock:
        raise CatalogError("Target stock must be at least the minimum stock.")
    if conn.execute("SELECT 1 FROM medicines WHERE lower(name) = lower(?)", (name,)).fetchone():
        raise CatalogError("That medicine is already in the catalog.")
    if not conn.execute("SELECT 1 FROM suppliers WHERE id = ?", (int(supplier_id),)).fetchone():
        raise CatalogError("Choose a supplier.")
    opening_qty = _int(opening_qty, "Opening stock")
    cur = conn.execute("INSERT INTO medicines (name, min_stock, target_stock, supplier_id) VALUES (?, ?, ?, ?)",
                       (name, min_stock, target_stock, int(supplier_id)))
    med_id = cur.lastrowid
    if opening_qty:
        if not opening_expiry or opening_expiry <= date.today():
            raise CatalogError("Opening stock needs a future expiry date.")
        batch = (opening_batch or "OPENING").strip()[:40]
        conn.execute("INSERT INTO batches (medicine_id, batch_no, expiry, qty) VALUES (?, ?, ?, ?)",
                     (med_id, batch, opening_expiry.isoformat(), opening_qty))
    log(conn, actor, "added medicine", {"name": name, "min": min_stock, "target": target_stock, "opening_qty": opening_qty})
    conn.commit()
    return med_id


def update_levels(conn, medicine_id: int, min_stock, target_stock, actor: str):
    min_stock, target_stock = _int(min_stock, "Minimum stock"), _int(target_stock, "Target stock", lo=1)
    if target_stock < min_stock:
        raise CatalogError("Target stock must be at least the minimum stock.")
    conn.execute("UPDATE medicines SET min_stock = ?, target_stock = ? WHERE id = ?", (min_stock, target_stock, int(medicine_id)))
    log(conn, actor, "changed stock levels", {"medicine_id": int(medicine_id), "min": min_stock, "target": target_stock})
    conn.commit()
