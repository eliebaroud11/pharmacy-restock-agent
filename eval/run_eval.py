"""Run every test case and report pass rate, human count and cost per run.

Each case lives in eval/cases/<id>/ with an invoice file and case.json:
  order_lines, supplier, today, invoice_file,
  expected: {status, issue_types, receive: [{name, qty, batch_no, expiry}]}

Run:  python eval/run_eval.py            (all cases)
      python eval/run_eval.py real_      (only cases whose folder starts with real_)
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")

from pharmacy.invoice import MODEL, read_invoice  # noqa: E402
from pharmacy.reconcile import reconcile  # noqa: E402
from pharmacy.seed import MEDICINES  # noqa: E402

CATALOG = [m[0] for m in MEDICINES]
# What the same task costs a person: minutes per delivery x hourly cost (USD). Adjust to your pharmacist's numbers.
HUMAN_MINUTES_PER_DELIVERY = 20
HUMAN_COST_PER_HOUR = 6.0


def check(case, invoice_data):
    """Compare the agent's result with what a human says is correct."""
    exp = case["expected"]
    got = reconcile(case["order_lines"], invoice_data, today=date.fromisoformat(case["today"]),
                    expected_supplier=case.get("supplier"))
    problems = []
    if got["status"] != exp["status"]:
        problems.append(f"status {got['status']} != {exp['status']}")
    if set(i["type"] for i in got["issues"]) != set(exp["issue_types"]):
        problems.append(f"issues {sorted(set(i['type'] for i in got['issues']))} != {sorted(exp['issue_types'])}")
    key = lambda r: (r["name"], r["batch_no"].upper().replace(" ", ""), r["expiry"], int(r["qty"]))  # noqa: E731
    if sorted(map(key, got["receive"])) != sorted(map(key, exp["receive"])):
        problems.append("stock to add differs from expected")
    return got, problems


def run_case(cdir: Path):
    case = json.loads((cdir / "case.json").read_text(encoding="utf-8"))
    t0 = time.time()
    res = read_invoice(cdir / case["invoice_file"], CATALOG)
    secs = time.time() - t0
    if res.error:
        return {"case": cdir.name, "passed": False, "human_needed": True, "problems": [res.error],
                "cost_usd": res.cost_usd, "seconds": secs}
    got, problems = check(case, res.data)
    return {
        "case": cdir.name,
        "description": case.get("description", ""),
        "passed": not problems,
        # A human is needed when the agent flags the delivery OR when it got the case wrong.
        "human_needed": got["status"] != "match" or bool(problems),
        "problems": problems,
        "issues_found": [i["detail"] for i in got["issues"]],
        "cost_usd": res.cost_usd,
        "tokens": res.input_tokens + res.output_tokens,
        "seconds": round(secs, 1),
    }


def main():
    prefix = sys.argv[1] if len(sys.argv) > 1 else ""
    cases = sorted(p for p in (ROOT / "cases").iterdir() if p.is_dir() and p.name.startswith(prefix))
    if not cases:
        sys.exit("No cases found. Run eval/make_synthetic.py or add real cases to eval/cases/.")
    print(f"Running {len(cases)} cases with {MODEL}...\n")
    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(run_case, cases))

    for r in results:
        mark = "PASS" if r["passed"] else "FAIL"
        print(f"[{mark}] {r['case']:<16} {r.get('description', '')[:45]:<45} ${r['cost_usd']:.4f}")
        for p in r["problems"]:
            print(f"        - {p}")

    n = len(results)
    passed = sum(r["passed"] for r in results)
    humans = sum(r["human_needed"] for r in results)
    avg_cost = sum(r["cost_usd"] for r in results) / n
    human_cost = HUMAN_MINUTES_PER_DELIVERY / 60 * HUMAN_COST_PER_HOUR
    print(f"\nPass rate:        {passed}/{n} ({passed / n:.0%})")
    print(f"Needed a human:   {humans}/{n}")
    print(f"AI cost per run:  ${avg_cost:.4f}   vs human: ${human_cost:.2f} "
          f"({HUMAN_MINUTES_PER_DELIVERY} min at ${HUMAN_COST_PER_HOUR}/h)")

    out = ROOT / "results"
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    summary = {"at": stamp, "model": MODEL, "cases": n, "passed": passed, "human_needed": humans,
               "avg_cost_usd": avg_cost, "human_cost_usd": human_cost, "results": results}
    (out / f"run-{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with open(out / "history.csv", "a", encoding="utf-8") as f:
        f.write(f"{stamp},{MODEL},{n},{passed},{humans},{avg_cost:.5f}\n")
    print(f"\nSaved to eval/results/run-{stamp}.json (history in eval/results/history.csv)")


if __name__ == "__main__":
    main()
