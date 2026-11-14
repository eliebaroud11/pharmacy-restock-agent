"""Compare an extracted invoice with the order it should fulfil. Pure code, no AI."""
import os
from collections import defaultdict
from datetime import date, timedelta

MIN_SHELF_DAYS = int(os.environ.get("MIN_SHELF_DAYS", "180"))


def reconcile(order_lines, invoice: dict, today: date | None = None, expected_supplier: str | None = None):
    """order_lines: iterable of {"name", "qty"}. Returns {"status", "issues", "receive"}.

    status is "match" only when every check passes; otherwise "needs_review".
    receive is the list of batches that would be added to stock.
    """
    today = today or date.today()
    min_expiry = (today + timedelta(days=MIN_SHELF_DAYS)).isoformat()
    issues = []
    ordered = {l["name"]: int(l["qty"]) for l in order_lines}
    delivered = defaultdict(int)
    receive = []

    if invoice.get("suspicious_text"):
        issues.append({"type": "suspicious_text", "detail": invoice.get("notes") or "Invoice contains text addressed to the AI."})

    if expected_supplier and invoice.get("supplier_name"):
        a, b = expected_supplier.lower(), invoice["supplier_name"].lower()
        if a.split()[0] not in b and b.split()[0] not in a:
            issues.append({"type": "supplier_mismatch",
                           "detail": f"Invoice is from '{invoice['supplier_name']}', order was to '{expected_supplier}'."})

    for line in invoice.get("lines", []):
        name = line.get("catalog_match", "NONE")
        qty = int(line.get("qty") or 0)
        label = line.get("product_name") or name
        if name == "NONE" or name not in ordered:
            issues.append({"type": "not_ordered", "detail": f"'{label}' x{qty} is on the invoice but was not ordered."})
            continue
        if qty <= 0:
            issues.append({"type": "bad_qty", "detail": f"'{label}' has no readable quantity."})
            continue
        delivered[name] += qty
        batch, expiry = (line.get("batch_no") or "").strip(), (line.get("expiry") or "").strip()
        if not batch:
            issues.append({"type": "missing_batch", "detail": f"'{label}' has no batch number."})
        if not _valid_date(expiry):
            issues.append({"type": "missing_expiry", "detail": f"'{label}' has no readable expiry date."})
        elif expiry < min_expiry:
            issues.append({"type": "short_expiry",
                           "detail": f"'{label}' batch {batch or '?'} expires {expiry} (less than {MIN_SHELF_DAYS} days)."})
        receive.append({"name": name, "batch_no": batch, "expiry": expiry, "qty": qty})

    for name, want in ordered.items():
        got = delivered.get(name, 0)
        if got == 0:
            issues.append({"type": "missing_item", "detail": f"'{name}': ordered {want}, none on invoice."})
        elif got < want:
            issues.append({"type": "short_qty", "detail": f"'{name}': ordered {want}, invoiced {got}."})
        elif got > want:
            issues.append({"type": "over_qty", "detail": f"'{name}': ordered {want}, invoiced {got}."})

    return {"status": "match" if not issues else "needs_review", "issues": issues, "receive": receive}


def _valid_date(s: str) -> bool:
    try:
        date.fromisoformat(s)
        return True
    except (ValueError, TypeError):
        return False
