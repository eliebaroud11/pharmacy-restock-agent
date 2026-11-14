"""Find medicines that are low on stock or close to expiry. Pure code, no AI."""
import os
from datetime import date, timedelta

from .db import stock_summary

NEAR_EXPIRY_DAYS = int(os.environ.get("NEAR_EXPIRY_DAYS", "90"))


def find_alerts(conn, today: date | None = None, near_days: int = NEAR_EXPIRY_DAYS):
    today = today or date.today()
    limit = (today + timedelta(days=near_days)).isoformat()
    # Medicines already on an open order shouldn't trigger a second order.
    on_order = {
        r["medicine_id"]
        for r in conn.execute(
            "SELECT ol.medicine_id FROM order_lines ol JOIN orders o ON o.id = ol.order_id "
            "WHERE o.status IN ('draft', 'pending_delivery')"
        )
    }
    alerts = []
    for row in stock_summary(conn):
        reasons = []
        if row["qty"] < row["min_stock"]:
            reasons.append(f"low stock: {row['qty']} left (minimum {row['min_stock']})")
        if row["nearest_expiry"] and row["nearest_expiry"] <= limit:
            expiring = conn.execute(
                "SELECT COALESCE(SUM(qty), 0) FROM batches WHERE medicine_id = ? AND qty > 0 AND expiry <= ?",
                (row["id"], limit),
            ).fetchone()[0]
            reasons.append(f"{expiring} units expire by {row['nearest_expiry']}")
        if reasons:
            alerts.append({
                "medicine_id": row["id"],
                "name": row["name"],
                "supplier": row["supplier"],
                "qty": row["qty"],
                "suggested_qty": suggested_qty(conn, row, limit),
                "reasons": reasons,
                "already_on_order": row["id"] in on_order,
            })
    return alerts


def suggested_qty(conn, row, expiry_limit: str) -> int:
    """Refill to target stock, not counting units that are about to expire."""
    expiring = conn.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM batches WHERE medicine_id = ? AND qty > 0 AND expiry <= ?",
        (row["id"], expiry_limit),
    ).fetchone()[0]
    usable = row["qty"] - expiring
    return max(row["target_stock"] - usable, 0)
