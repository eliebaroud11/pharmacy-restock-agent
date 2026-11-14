"""Receive a delivery: check the invoice against the order and update stock.

Stock is added automatically only when the pharmacist has confirmed the batch
and the invoice matches the order exactly. Anything else waits for a human.
"""
from .db import log, now, order_with_lines
from .reconcile import reconcile


def check_delivery(conn, order_id: int, invoice: dict, today=None):
    order, lines = order_with_lines(conn, order_id)
    if order is None:
        raise ValueError(f"Order {order_id} not found")
    if order["status"] not in ("pending_delivery", "needs_review"):
        raise ValueError(f"Order {order_id} is '{order['status']}', not awaiting delivery.")
    return reconcile([dict(l) for l in lines], invoice, today=today, expected_supplier=order["supplier"])


def receive_delivery(conn, order_id: int, invoice: dict, pharmacist: str, batch_confirmed: bool,
                     accept_discrepancies: bool = False, today=None):
    """Returns the reconcile result. Adds stock only if allowed."""
    if not batch_confirmed:
        raise PermissionError("The pharmacist must confirm the batch matches the order first.")
    if not pharmacist or not pharmacist.strip():
        raise PermissionError("A pharmacist's name is required.")
    result = check_delivery(conn, order_id, invoice, today=today)

    if result["status"] != "match" and not accept_discrepancies:
        conn.execute("UPDATE orders SET status = 'needs_review' WHERE id = ?", (order_id,))
        log(conn, "agent", "flagged delivery for review", {"order_id": order_id, "issues": result["issues"]})
        conn.commit()
        result["applied"] = False
        return result

    for item in result["receive"]:
        med = conn.execute("SELECT id FROM medicines WHERE name = ?", (item["name"],)).fetchone()
        conn.execute(
            "INSERT INTO batches (medicine_id, batch_no, expiry, qty, order_id) VALUES (?, ?, ?, ?, ?)",
            (med["id"], item["batch_no"] or "UNKNOWN", item["expiry"] or "9999-12-31", item["qty"], order_id),
        )
    conn.execute("UPDATE orders SET status = 'received', received_at = ? WHERE id = ?", (now(), order_id))
    actor = pharmacist.strip() if accept_discrepancies else "agent"
    log(conn, actor, "added delivery to stock",
        {"order_id": order_id, "items": result["receive"], "accepted_discrepancies": accept_discrepancies,
         "invoice_number": invoice.get("invoice_number"), "batch_confirmed_by": pharmacist.strip()})
    conn.commit()
    result["applied"] = True
    return result
