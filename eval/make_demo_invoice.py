"""Print a fake invoice image for an order in the app, for rehearsing the demo.

  python eval/make_demo_invoice.py 3            -> demo_invoices/order_3.jpg, matches order #3 exactly
  python eval/make_demo_invoice.py 3 --short    -> same, but the first item is 4 units short

Then upload it on the Receive delivery tab. These are DEMO props, not test cases:
say so if a judge asks, and use real invoices for the live test.
"""
import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from make_synthetic import CATALOG, draw_invoice  # noqa: E402
from pharmacy import db  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("order_id", type=int)
    ap.add_argument("--short", action="store_true", help="make the first line 4 units short")
    args = ap.parse_args()

    conn = db.connect()
    order, lines = db.order_with_lines(conn, args.order_id)
    if order is None:
        sys.exit(f"Order #{args.order_id} not found. Draft and approve it in the app first.")
    rng = random.Random(args.order_id)  # nosec B311 - fake demo data, not security
    inv_lines = []
    for n, l in enumerate(lines):
        qty = l["qty"] - (4 if args.short and n == 0 else 0)
        inv_lines.append({"name": l["name"], "qty": max(qty, 1),
                          "batch": f"{l['name'][:3].upper()}{rng.randint(1000, 9999)}",
                          "expiry": date.today() + timedelta(days=rng.randint(450, 900)),
                          "price": round(rng.uniform(1.5, 25), 2)})
    # Print names the way a supplier would, when we know a style for that product.
    for l in inv_lines:
        CATALOG.setdefault(l["name"], l["name"].upper())
    img = draw_invoice(1000 + args.order_id, inv_lines, None, False, False, rng, supplier=order["supplier"])
    out = ROOT.parent / "demo_invoices"
    out.mkdir(exist_ok=True)
    path = out / f"order_{args.order_id}{'_short' if args.short else ''}.jpg"
    img.save(path, quality=88)
    print(f"Saved {path}")


if __name__ == "__main__":
    main()
