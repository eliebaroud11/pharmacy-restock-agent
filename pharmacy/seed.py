"""Fill the database with fictional demo data (no real pharmacy or supplier names)."""
from datetime import date, timedelta

from .db import connect, log

SUPPLIERS = [
    ("Cedar Pharma Distribution", "orders@cedar-pharma.example"),
    ("Byblos Medical Supply", "+961 00 000 000"),
]

# name, min_stock, target_stock, supplier index, [(batch, days_to_expiry, qty), ...]
MEDICINES = [
    ("Paracetamol 500mg tabs (24)", 40, 120, 0, [("PCM-2405", 400, 25)]),
    ("Ibuprofen 400mg tabs (20)", 30, 90, 0, [("IBU-1187", 300, 50)]),
    ("Amoxicillin 500mg caps (16)", 20, 60, 1, [("AMX-3321", 60, 18)]),
    ("Omeprazole 20mg caps (14)", 15, 45, 1, [("OMP-0912", 500, 30)]),
    ("Metformin 850mg tabs (30)", 25, 75, 0, [("MET-5540", 45, 40)]),
    ("Amlodipine 5mg tabs (30)", 20, 60, 1, [("AML-7781", 700, 12)]),
    ("Salbutamol 100mcg inhaler", 10, 30, 0, [("SAL-2210", 250, 14)]),
    ("Cetirizine 10mg tabs (20)", 15, 45, 1, [("CET-4471", 365, 35)]),
    ("Atorvastatin 20mg tabs (30)", 20, 60, 0, [("ATV-6612", 80, 22)]),
    ("Vitamin D3 50000 IU caps (4)", 10, 40, 1, [("VD3-1090", 600, 8)]),
]


def seed(conn=None, today: date | None = None, reset: bool = True):
    conn = conn or connect()
    today = today or date.today()
    if reset:
        # Fixed statements (no string-built SQL). Accounts are never touched by a reset.
        for stmt in ("DELETE FROM audit_log", "DELETE FROM batches", "DELETE FROM order_lines",
                     "DELETE FROM orders", "DELETE FROM medicines", "DELETE FROM suppliers"):
            conn.execute(stmt)
    sup_ids = []
    for name, contact in SUPPLIERS:
        cur = conn.execute("INSERT INTO suppliers (name, contact) VALUES (?, ?)", (name, contact))
        sup_ids.append(cur.lastrowid)
    for name, mn, tgt, si, batches in MEDICINES:
        cur = conn.execute(
            "INSERT INTO medicines (name, min_stock, target_stock, supplier_id) VALUES (?, ?, ?, ?)",
            (name, mn, tgt, sup_ids[si]),
        )
        for batch_no, days, qty in batches:
            conn.execute(
                "INSERT INTO batches (medicine_id, batch_no, expiry, qty) VALUES (?, ?, ?, ?)",
                (cur.lastrowid, batch_no, (today + timedelta(days=days)).isoformat(), qty),
            )
    log(conn, "system", "seeded demo data")
    conn.commit()
    return conn


if __name__ == "__main__":
    seed()
    print("Seeded fictional demo data.")
