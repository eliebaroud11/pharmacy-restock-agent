"""Draft supplier orders and enforce the human approval lock.

THE LOCK: an order can only leave 'draft' through approve_order(), which needs a
named pharmacist. supplier_message() refuses to produce a sendable message for
an unapproved order. This is enforced in code, not in a prompt.
"""
from collections import defaultdict

from .db import log, now, order_with_lines


class ApprovalRequired(Exception):
    pass


def draft_orders(conn, items, reason: str = "manual request"):
    """items: list of (medicine_id, qty). Creates one draft order per supplier."""
    by_supplier = defaultdict(list)
    for med_id, qty in items:
        if qty <= 0:
            continue
        sup = conn.execute("SELECT supplier_id FROM medicines WHERE id = ?", (med_id,)).fetchone()
        if sup is None:
            raise ValueError(f"Unknown medicine id {med_id}")
        by_supplier[sup["supplier_id"]].append((med_id, int(qty)))

    order_ids = []
    for supplier_id, lines in by_supplier.items():
        cur = conn.execute(
            "INSERT INTO orders (supplier_id, status, reason, created_at) VALUES (?, 'draft', ?, ?)",
            (supplier_id, reason, now()),
        )
        oid = cur.lastrowid
        conn.executemany(
            "INSERT INTO order_lines (order_id, medicine_id, qty) VALUES (?, ?, ?)",
            [(oid, m, q) for m, q in lines],
        )
        conn.execute("UPDATE orders SET message = ? WHERE id = ?", (_compose(conn, oid), oid))
        log(conn, "agent", "drafted order", {"order_id": oid, "lines": lines, "reason": reason})
        order_ids.append(oid)
    conn.commit()
    return order_ids


def _compose(conn, order_id: int) -> str:
    order, lines = order_with_lines(conn, order_id)
    body = "\n".join(f"- {l['name']}: {l['qty']}" for l in lines)
    return (
        f"Hello {order['supplier']},\n\n"
        f"We would like to order the following (order #{order_id}):\n{body}\n\n"
        "Please confirm availability, price and expected delivery date. "
        "Please send batches with at least 12 months before expiry.\n\nThank you."
    )


def update_line(conn, order_id: int, medicine_id: int, qty: int, actor: str):
    order, _ = order_with_lines(conn, order_id)
    if order is None or order["status"] != "draft":
        raise ValueError("Only draft orders can be edited.")
    if qty <= 0:
        conn.execute("DELETE FROM order_lines WHERE order_id = ? AND medicine_id = ?", (order_id, medicine_id))
    else:
        conn.execute("UPDATE order_lines SET qty = ? WHERE order_id = ? AND medicine_id = ?", (qty, order_id, medicine_id))
    conn.execute("UPDATE orders SET message = ? WHERE id = ?", (_compose(conn, order_id), order_id))
    log(conn, actor, "edited order line", {"order_id": order_id, "medicine_id": medicine_id, "qty": qty})
    conn.commit()


def approve_order(conn, order_id: int, pharmacist: str):
    """The only way an order can be placed. Requires a named human."""
    if not pharmacist or not pharmacist.strip():
        raise ApprovalRequired("A pharmacist's name is required to approve an order.")
    order, lines = order_with_lines(conn, order_id)
    if order is None:
        raise ValueError(f"Order {order_id} not found")
    if order["status"] != "draft":
        raise ValueError(f"Order {order_id} is '{order['status']}', not 'draft'.")
    if not lines:
        raise ValueError("Cannot approve an empty order.")
    conn.execute(
        "UPDATE orders SET status = 'pending_delivery', approved_by = ?, approved_at = ? WHERE id = ?",
        (pharmacist.strip(), now(), order_id),
    )
    log(conn, pharmacist.strip(), "approved order", {"order_id": order_id})
    conn.commit()


def cancel_order(conn, order_id: int, actor: str):
    conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ? AND status = 'draft'", (order_id,))
    log(conn, actor, "cancelled order", {"order_id": order_id})
    conn.commit()


def supplier_message(conn, order_id: int) -> str:
    order, _ = order_with_lines(conn, order_id)
    if order is None or not order["approved_by"]:
        raise ApprovalRequired("This order has not been approved by a pharmacist.")
    return order["message"]
