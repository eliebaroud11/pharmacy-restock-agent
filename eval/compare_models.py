"""Compare models on the three things that matter: reading accuracy, agent decisions, injection safety.

  python eval/compare_models.py                      (default shortlist)
  python eval/compare_models.py model_a model_b ...

Per model: 20 invoices read, 9 agent decisions, 12 malicious invoices. Real cost comes from OpenRouter prices.
Results: printed table + eval/results/compare_models.json
"""
import json
import os
import random
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")
os.environ["PHARMA_PROVIDER"] = "openrouter"

import redteam  # noqa: E402
import run_agent_eval  # noqa: E402
import run_eval  # noqa: E402
from pharmacy import agent, invoice  # noqa: E402

SHORTLIST = [
    "anthropic/claude-haiku-5.5",
    "deepseek/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
    "qwen/qwen3.5-flash-02-23",
    "google/gemini-3.1-flash-lite",
    "openai/gpt-5-mini",
    "mistralai/mistral-small-3.2-24b-instruct",
]


def load_prices(models):
    with urllib.request.urlopen("https://openrouter.ai/api/v1/models", timeout=30) as r:  # nosec B310 - fixed https URL
        data = json.load(r)["data"]
    for m in data:
        if m["id"] in models:
            invoice.PRICES[m["id"]] = (float(m["pricing"]["prompt"]) * 1e6, float(m["pricing"]["completion"]) * 1e6)


def reading(model):
    cases = sorted(p for p in (ROOT / "cases").iterdir() if p.is_dir() and p.name.startswith("synthetic_"))

    def one(cdir):
        case = json.loads((cdir / "case.json").read_text(encoding="utf-8-sig"))
        t = time.time()
        res = invoice.read_invoice(cdir / case["invoice_file"], run_eval.CATALOG, model=model)
        secs = time.time() - t
        if res.error:
            return False, secs, res.cost_usd, res.error
        _, problems = run_eval.check(case, res.data)
        return not problems, secs, res.cost_usd, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        out = list(pool.map(one, cases))
    errors = [e for _, _, _, e in out if e]
    return {"read_ok": sum(o[0] for o in out), "read_n": len(out),
            "read_secs": sum(o[1] for o in out) / len(out), "read_cost": sum(o[2] for o in out) / len(out),
            "read_errors": errors[:2]}


def agent_decisions(model):
    agent.AGENT_MODEL = model
    cases = []
    for cdir in sorted((ROOT / "cases").iterdir()):
        case = json.loads((cdir / "case.json").read_text(encoding="utf-8-sig"))
        if case["expected"]["issue_types"] and cdir.name.startswith("synthetic_"):
            cases.append(case)

    def one(case):
        conn, oid, inv, issues, today = run_agent_eval.setup(case)
        t = time.time()
        plan = agent.plan_followup(conn, oid, inv, issues, today=today).to_dict()
        secs = time.time() - t
        return not run_agent_eval.grade(case, inv, plan, today), secs, plan["cost_usd"]

    with ThreadPoolExecutor(max_workers=3) as pool:
        out = list(pool.map(one, cases))
    return {"agent_ok": sum(o[0] for o in out), "agent_n": len(out),
            "agent_secs": sum(o[1] for o in out) / len(out), "agent_cost": sum(o[2] for o in out) / len(out)}


def red_team(model):
    agent.AGENT_MODEL = model
    real = invoice.read_invoice
    redteam.read_invoice = lambda path, catalog: real(path, catalog, model=model)
    rng = random.Random(7)  # nosec B311 - same fake invoices for every model
    results = []
    for missed in (False, True):
        redteam.ASSUME_MISSED = missed
        for name, inj, opt in redteam.CASES:
            results.append(redteam.run_case(name, inj, opt, rng))
    redteam.read_invoice = real
    normal, worst = results[:12], results[12:]
    return {"safe": sum(r["passed"] for r in normal), "detected": sum(r["detected"] for r in normal),
            "safe_if_missed": sum(r["passed"] for r in worst), "rt_n": 12,
            "rt_cost": sum(r.get("cost", 0) for r in results)}


def main():
    models = sys.argv[1:] or SHORTLIST
    load_prices(models)
    rows = []
    for m in models:
        print(f"\n=== {m} ===", flush=True)
        row = {"model": m}
        for name, fn in (("reading", reading), ("agent", agent_decisions), ("red team", red_team)):
            try:
                row.update(fn(m))
                print(f"  {name}: done", flush=True)
            except Exception as e:  # keep going: one failing model shouldn't stop the comparison
                row[f"{name}_crash"] = f"{type(e).__name__}: {str(e)[:120]}"
                print(f"  {name}: CRASHED {row[f'{name}_crash']}", flush=True)
        rows.append(row)
        (ROOT / "results").mkdir(exist_ok=True)
        (ROOT / "results" / "compare_models.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")

    print("\n" + "-" * 132)
    print(f"{'model':<42}{'reading':>9}{'s/inv':>7}{'agent':>7}{'s/plan':>8}{'inj safe':>10}{'detected':>10}"
          f"{'safe if missed':>16}{'$/problem delivery':>21}")
    for r in rows:
        cost = r.get("read_cost", 0) + r.get("agent_cost", 0)
        print(f"{r['model']:<42}{str(r.get('read_ok', '-')) + '/' + str(r.get('read_n', '-')):>9}"
              f"{r.get('read_secs', 0):>7.1f}{str(r.get('agent_ok', '-')) + '/9':>7}{r.get('agent_secs', 0):>8.1f}"
              f"{str(r.get('safe', '-')) + '/12':>10}{str(r.get('detected', '-')) + '/12':>10}"
              f"{str(r.get('safe_if_missed', '-')) + '/12':>16}{cost:>21.5f}")
        for k in ("read_errors", "reading_crash", "agent_crash", "red team_crash"):
            if r.get(k):
                print(f"    {k}: {r[k]}")


if __name__ == "__main__":
    main()
