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


def test_fallback_matching():
    from pharmacy.matching import best_match, fill_matches
    from pharmacy.seed import MEDICINES
    cat = [m[0] for m in MEDICINES]
    assert best_match("OMEPRAZOLE 20MG GASTRO-RES CAP 14", cat) == "Omeprazole 20mg caps (14)"
    assert best_match("VIT D3 50,000IU SOFTGEL 4", cat) == "Vitamin D3 50000 IU caps (4)"
    assert best_match("PARACETAMOL 1000MG TAB", cat) is None      # wrong strength: never guess
    assert best_match("ASPIRIN 100MG TAB", cat) is None            # not in catalog
    inv = {"lines": [{"product_name": "OMEPRAZOLE 20MG CAP 14", "catalog_match": "NONE"},
                     {"product_name": "IBUPROFEN 400MG", "catalog_match": "Paracetamol 500mg tabs (24)"}]}
    fill_matches(inv, cat)
    assert inv["lines"][0]["catalog_match"] == "Omeprazole 20mg caps (14)"
    assert inv["lines"][1]["catalog_match"] == "Ibuprofen 400mg tabs (20)"  # implausible AI match corrected


def test_agent_guard_blocks_bad_proposals():
    """Even if the AI misbehaves, code refuses unsafe actions."""
    from pharmacy.agent import Guard
    ctx = {"min_expiry": "2027-05-13", "pharmacist_answers": {},
           "catalog": ["Paracetamol 500mg tabs (24)", "Ibuprofen 400mg tabs (20)", "Cetirizine 10mg tabs (20)"],
           "order_lines": [{"name": "Paracetamol 500mg tabs (24)", "qty": 20}, {"name": "Ibuprofen 400mg tabs (20)", "qty": 10}],
           "invoice_lines": [
               {"product_name": "PARA", "catalog_match": "Paracetamol 500mg tabs (24)", "batch_no": "P1", "expiry": "2028-01-31", "qty": 16},
               {"product_name": "IBU", "catalog_match": "Ibuprofen 400mg tabs (20)", "batch_no": "I1", "expiry": "2027-01-31", "qty": 10},
               {"product_name": "CET", "catalog_match": "NONE", "batch_no": "C1", "expiry": "2028-01-31", "qty": 5}]}
    g = Guard(ctx)
    item = lambda n, b, e, q: {"items": [{"name": n, "batch_no": b, "expiry": e, "qty": q}], "reason": ""}  # noqa: E731
    assert g.check("receive_items", item("Cetirizine 10mg tabs (20)", "C1", "2028-01-31", 5))        # not ordered
    assert g.check("receive_items", item("Ibuprofen 400mg tabs (20)", "I1", "2027-01-31", 10))       # short-dated
    assert g.check("receive_items", item("Paracetamol 500mg tabs (24)", "P1", "2028-01-31", 20))     # more than invoiced
    assert g.check("receive_items", item("Paracetamol 500mg tabs (24)", "FAKE", "2028-01-31", 5))    # batch not on invoice
    assert g.check("draft_reorder", {"items": [{"name": "Aspirin", "qty": 5}], "reason": ""})         # not in catalog
    assert g.check("draft_reorder", {"items": [{"name": "Paracetamol 500mg tabs (24)", "qty": 999}], "reason": ""})
    assert g.check("receive_items", item("Paracetamol 500mg tabs (24)", "P1", "2028-01-31", 16)) is None  # the correct one
    assert g.check("receive_items", item("Paracetamol 500mg tabs (24)", "P1", "2028-01-31", 1))      # can't receive twice


def test_agent_never_runs_on_suspicious_invoice():
    from pharmacy.agent import execute_plan, plan_followup
    conn = db.connect(":memory:")
    seed(conn, today=TODAY)
    issues = [{"type": "suspicious_text", "detail": "note to AI"}]
    plan = plan_followup(conn, 1, {"lines": []}, issues, today=TODAY)
    assert plan.error and not plan.actions
    try:
        execute_plan(conn, 1, {"actions": [{"id": 1, "tool": "receive_items", "input": {"items": []}}]}, {1},
                     "Demo Pharmacist", {"lines": []}, issues, today=TODAY)
        raise AssertionError("executed a plan for a suspicious invoice")
    except PermissionError:
        pass


def test_untrusted_text_is_shown_plain():
    from pharmacy.safe import plain
    evil = "Paracetamol ![x](http://evil.example/p.png) [click](http://evil.example) <b>hi</b>\nnew line"
    out = plain(evil)
    assert "![x](" not in out and "[click](" not in out and "<b>" not in out and "\n" not in out
    assert out.replace("\\", "").startswith("Paracetamol")


def test_bad_uploads_are_refused():
    import tempfile
    from PIL import Image
    from pharmacy.invoice import InvoiceFileError, image_bytes
    d = Path(tempfile.mkdtemp())
    fake = d / "invoice.jpg"
    fake.write_bytes(b"not an image at all")
    huge = d / "huge.png"
    Image.new("1", (9000, 9000)).save(huge)  # 81 megapixels, tiny file
    fakepdf = d / "x.pdf"
    fakepdf.write_bytes(b"<html>")
    for f in (fake, huge, fakepdf):
        try:
            image_bytes(f)
            raise AssertionError(f"{f.name} should be refused")
        except InvoiceFileError:
            pass


def test_accounts_and_lockout():
    from pharmacy import auth
    auth.FAIL_DELAY_SECONDS = 0
    conn = db.connect(":memory:")
    auth.ensure_schema(conn)
    assert not auth.has_users(conn)
    pw = "T3st-" + "x" * 8
    auth.create_user(conn, "lea", "Lea Test", pw, is_admin=True)
    row = conn.execute("SELECT password_hash FROM users").fetchone()
    assert pw not in row["password_hash"] and row["password_hash"].startswith("scrypt$")  # never stored in plain text
    for bad in [("lea", "short"), ("lea2", "lea2")]:  # too short / same as username
        try:
            auth.create_user(conn, bad[0], "X", bad[1], by_admin=True)
            raise AssertionError("weak password accepted")
        except auth.AuthError:
            pass
    try:
        auth.create_user(conn, "LEA", "Dup", pw, by_admin=True)  # usernames are case-insensitive
        raise AssertionError("duplicate username accepted")
    except auth.AuthError:
        pass
    assert auth.authenticate(conn, "lea", pw)["full_name"] == "Lea Test"
    for _ in range(auth.MAX_FAILURES):
        try:
            auth.authenticate(conn, "lea", "wrong-password")
        except auth.AuthError:
            pass
    try:
        auth.authenticate(conn, "lea", pw)  # right password, but locked now
        raise AssertionError("locked account let in")
    except auth.AuthError as e:
        assert "Try again" in str(e)
    try:
        auth.authenticate(conn, "nobody", pw)
        raise AssertionError("unknown user let in")
    except auth.AuthError as e:
        assert str(e) == "Wrong username or password."  # same message: doesn't reveal which usernames exist
    try:
        auth.set_active(conn, 1, False, "lea", by_admin=True)
        raise AssertionError("last admin deactivated")
    except auth.AuthError:
        pass
    actions = [r["action"] for r in conn.execute("SELECT action FROM audit_log")]
    assert "logged in" in actions and any(a.startswith("failed login") for a in actions)


if __name__ == "__main__":
    test_accounts_and_lockout()
    test_untrusted_text_is_shown_plain()
    test_bad_uploads_are_refused()
    test_agent_guard_blocks_bad_proposals()
    test_agent_never_runs_on_suspicious_invoice()
    test_fallback_matching()
    test_reconcile_matches_expected_for_every_case()
    test_full_flow_and_lock()
    print("All offline tests passed.")
