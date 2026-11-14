"""Offline tests: no API calls. Run:  python -m pytest tests  (or python tests/test_offline.py)"""
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pharmacy import db, orders  # noqa: E402
from pharmacy.alerts import find_alerts  # noqa: E402
from pharmacy.receive import receive_delivery  # noqa: E402
from pharmacy.reconcile import reconcile  # noqa: E402
from pharmacy.seed import seed  # noqa: E402

TODAY = date(2026, 11, 14)


def perfect_invoice(case):
    """What a perfect reader would extract from the case's invoice."""
    exp = case["expected"]
    lines = [{"product_name": r["name"], "catalog_match": r["name"], "batch_no": r["batch_no"],
              "expiry": r["expiry"], "qty": r["qty"], "unit_price": ""} for r in exp["receive"]]
    if "not_ordered" in exp["issue_types"]:
        lines.append({"product_name": "extra", "catalog_match": "NONE", "batch_no": "X", "expiry": "2028-01-01",
                      "qty": 10, "unit_price": ""})
    return {"supplier_name": case["supplier"], "invoice_number": "1", "invoice_date": "", "lines": lines,
            "total": "", "suspicious_text": "suspicious_text" in exp["issue_types"], "notes": ""}


def test_reconcile_matches_expected_for_every_case():
    for cdir in sorted((ROOT / "eval" / "cases").iterdir()):
        case = json.loads((cdir / "case.json").read_text(encoding="utf-8"))
        got = reconcile(case["order_lines"], perfect_invoice(case), today=date.fromisoformat(case["today"]),
                        expected_supplier=case["supplier"])
        assert got["status"] == case["expected"]["status"], cdir.name
        assert {i["type"] for i in got["issues"]} == set(case["expected"]["issue_types"]), (cdir.name, got["issues"])


def test_full_flow_and_lock(tmp_path=None):
    conn = db.connect(":memory:")
    seed(conn, today=TODAY)
    alerts = find_alerts(conn, today=TODAY)
    names = {a["name"] for a in alerts}
    assert "Paracetamol 500mg tabs (24)" in names  # low stock
    assert "Amoxicillin 500mg caps (16)" in names  # near expiry

    picks = [(a["medicine_id"], a["suggested_qty"]) for a in alerts]
    ids = orders.draft_orders(conn, picks, reason="alert")
    oid = ids[0]

    # Lock: no message, no approval without a name.
    try:
        orders.supplier_message(conn, oid)
        raise AssertionError("message available before approval")
    except orders.ApprovalRequired:
        pass
    try:
        orders.approve_order(conn, oid, "  ")
        raise AssertionError("approved without a name")
    except orders.ApprovalRequired:
        pass

    orders.approve_order(conn, oid, "Demo Pharmacist")
    assert "order #" in orders.supplier_message(conn, oid)
    assert find_alerts(conn, today=TODAY)[0]["already_on_order"] in (True, False)

    order, lines = db.order_with_lines(conn, oid)
    inv = {"supplier_name": order["supplier"], "invoice_number": "T1", "invoice_date": "", "total": "",
           "suspicious_text": False, "notes": "",
           "lines": [{"product_name": l["name"], "catalog_match": l["name"], "batch_no": f"B{i}",
                      "expiry": "2028-06-30", "qty": l["qty"], "unit_price": ""} for i, l in enumerate(lines)]}

    try:
        receive_delivery(conn, oid, inv, "Demo Pharmacist", batch_confirmed=False, today=TODAY)
        raise AssertionError("received without batch confirmation")
    except PermissionError:
        pass

    before = {r["name"]: r["qty"] for r in db.stock_summary(conn)}
    res = receive_delivery(conn, oid, inv, "Demo Pharmacist", batch_confirmed=True, today=TODAY)
    assert res["applied"] and res["status"] == "match"
    after = {r["name"]: r["qty"] for r in db.stock_summary(conn)}
    for l in lines:
        assert after[l["name"]] == before[l["name"]] + l["qty"]
    assert db.order_with_lines(conn, oid)[0]["status"] == "received"

    # A short delivery must not touch stock.
    oid2 = orders.draft_orders(conn, [(lines[0]["medicine_id"], 10)])[0]
    orders.approve_order(conn, oid2, "Demo Pharmacist")
    short = {**inv, "lines": [{**inv["lines"][0], "qty": 7}]}
    snap = {r["name"]: r["qty"] for r in db.stock_summary(conn)}
    res = receive_delivery(conn, oid2, short, "Demo Pharmacist", batch_confirmed=True, today=TODAY)
    assert not res["applied"] and res["status"] == "needs_review"
    assert {r["name"]: r["qty"] for r in db.stock_summary(conn)} == snap


if __name__ == "__main__":
    test_reconcile_matches_expected_for_every_case()
    test_full_flow_and_lock()
    print("All offline tests passed.")
