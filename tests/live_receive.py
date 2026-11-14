"""End-to-end check WITH the AI (uses your API key): order -> approve -> invoice photo -> stock.

Run:  python tests/live_receive.py
Uses an in-memory database, so your demo data is not touched.
"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from pharmacy import db, orders  # noqa: E402
from pharmacy.invoice import read_invoice  # noqa: E402
from pharmacy.receive import receive_delivery  # noqa: E402
from pharmacy.seed import seed  # noqa: E402


def run(case_name):
    cdir = ROOT / "eval" / "cases" / case_name
    case = json.loads((cdir / "case.json").read_text(encoding="utf-8-sig"))
    today = date.fromisoformat(case["today"])
    conn = db.connect(":memory:")
    seed(conn, today=today)
    # The synthetic invoices all come from one supplier, so put every medicine on that supplier
    # (otherwise the app correctly splits the order in two and the invoice covers only half).
    conn.execute("UPDATE medicines SET supplier_id = (SELECT id FROM suppliers WHERE name = ?)", (case["supplier"],))
    ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM medicines")}
    oid = orders.draft_orders(conn, [(ids[l["name"]], l["qty"]) for l in case["order_lines"]])[0]
    orders.approve_order(conn, oid, "Test Pharmacist")

    before = {r["name"]: r["qty"] for r in db.stock_summary(conn)}
    res = read_invoice(cdir / case["invoice_file"], list(ids))
    assert not res.error, res.error
    result = receive_delivery(conn, oid, res.data, "Test Pharmacist", batch_confirmed=True, today=today)
    after = {r["name"]: r["qty"] for r in db.stock_summary(conn)}
    status = db.order_with_lines(conn, oid)[0]["status"]
    changed = {n: after[n] - before[n] for n in after if after[n] != before[n]}
    print(f"{case_name}: {case['description']}")
    print(f"  applied={result['applied']}  order status={status}  stock change={changed}")
    for i in result["issues"]:
        print(f"  issue: {i['type']} - {i['detail']}")
    return result, changed, status


if __name__ == "__main__":
    ok_result, ok_changed, ok_status = run("synthetic_06")   # clean invoice, two batches
    assert ok_result["applied"] and ok_status == "received" and ok_changed, "clean invoice should update stock"
    bad_result, bad_changed, bad_status = run("synthetic_11")  # one item short
    assert not bad_result["applied"] and bad_status == "needs_review" and not bad_changed, "short delivery must not touch stock"
    print("\nLive end-to-end check passed.")
