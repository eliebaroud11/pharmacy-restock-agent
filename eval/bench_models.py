"""Compare invoice-reading models on speed and accuracy (OpenRouter).

  python eval/bench_models.py model_a model_b ...
  (append ":noreason" to a model id to ask OpenRouter to turn its reasoning off)
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT.parent / ".env")

import run_eval  # noqa: E402
from pharmacy import invoice_openrouter  # noqa: E402
from pharmacy.invoice import read_invoice  # noqa: E402

CASES = ["synthetic_01", "synthetic_08", "synthetic_10", "synthetic_11"]


def main():
    for spec in sys.argv[1:]:
        model, _, flag = spec.partition(":noreason")
        model = model if not spec.endswith(":noreason") else spec[: -len(":noreason")]
        os.environ["PHARMA_REASONING"] = "off" if spec.endswith(":noreason") else ""
        ok, secs = 0, []
        for name in CASES:
            cdir = ROOT / "cases" / name
            case = json.loads((cdir / "case.json").read_text(encoding="utf-8-sig"))
            t = time.time()
            res = read_invoice(cdir / case["invoice_file"], run_eval.CATALOG, model=model)
            secs.append(time.time() - t)
            if not res.error:
                _, problems = run_eval.check(case, res.data)
                ok += not problems
        print(f"{spec:<55} correct {ok}/{len(CASES)}   avg {sum(secs) / len(secs):5.1f}s   max {max(secs):5.1f}s")


if __name__ == "__main__":
    main()
