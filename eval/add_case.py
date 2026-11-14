r"""Turn a real invoice photo into a test case, ready for a human to check.

  python eval/add_case.py path\to\invoice.jpg
  python eval/add_case.py path\to\invoice.jpg --name real_03 --short "Paracetamol 500mg=5"

What it does:
  1. Copies the photo into eval/cases/real_NN/
  2. Reads it once with the AI to pre-fill case.json (so you don't type everything)
  3. Marks the case "verified": false, so run_eval.py skips it until you check it

Then YOU open case.json next to the paper invoice and fix anything wrong:
  - order_lines: what the pharmacy actually ORDERED (defaults to what's on the invoice)
  - expected.receive: the true batch, expiry (YYYY-MM-DD) and qty for each line
  - expected.status / issue_types: "match" + [] if order and invoice agree,
    otherwise "needs_review" + the problems (short_qty, over_qty, missing_item,
    not_ordered, short_expiry, missing_batch, missing_expiry, suspicious_text)
  - set "verified": true
Blur patient and pharmacy names in the photo before committing it.
"""
import argparse
import json
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")

from pharmacy.invoice import read_invoice  # noqa: E402


def next_name():
    n = 1
    while (ROOT / "cases" / f"real_{n:02d}").exists():
        n += 1
    return f"real_{n:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo")
    ap.add_argument("--name", help="case folder name (default real_NN)")
    ap.add_argument("--supplier", default="", help="supplier the order was sent to")
    ap.add_argument("--today", default=date.today().isoformat(), help="date the delivery arrived (YYYY-MM-DD)")
    args = ap.parse_args()

    src = Path(args.photo)
    if not src.exists():
        sys.exit(f"File not found: {src}")
    name = args.name or next_name()
    cdir = ROOT / "cases" / name
    cdir.mkdir(parents=True, exist_ok=False)
    dest = cdir / ("invoice" + src.suffix.lower())
    shutil.copy2(src, dest)

    print(f"Reading {src.name} to pre-fill the case...")
    res = read_invoice(dest, [])
    lines = res.data.get("lines", []) if not res.error else []
    if res.error:
        print(f"Could not read it automatically ({res.error}). Fill case.json by hand.")

    names = list(dict.fromkeys(l["product_name"] for l in lines))
    ordered = {}
    for l in lines:  # one order line per product, even if it arrived in several batches
        ordered[l["product_name"]] = ordered.get(l["product_name"], 0) + int(l["qty"] or 0)
    case = {
        "description": "REAL - describe this delivery (e.g. 'Clean invoice, 6 lines')",
        "verified": False,
        "today": args.today,
        "supplier": args.supplier or res.data.get("supplier_name", ""),
        "invoice_file": dest.name,
        "catalog": names,
        "order_lines": [{"name": n, "qty": q} for n, q in ordered.items()],
        "expected": {
            "status": "match",
            "issue_types": [],
            "receive": [{"name": l["product_name"], "qty": l["qty"], "batch_no": l["batch_no"],
                         "expiry": l["expiry"]} for l in lines],
        },
    }
    (cdir / "case.json").write_text(json.dumps(case, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nCreated eval/cases/{name}/ with {len(lines)} pre-filled line(s).")
    print("Now open case.json next to the paper invoice, fix anything wrong, and set \"verified\": true.")


if __name__ == "__main__":
    main()
