# Pharmacy Restock Agent · AlphaHack 2026

An AI agent that runs a community pharmacy's restocking loop from start to finish:
**alert → draft order → pharmacist approves → delivery arrives → invoice photo checked → stock updated.**

## Index card

| | |
|---|---|
| **Whose job** | A community pharmacist in Lebanon (name withheld) |
| **Trigger** | A medicine falls below its minimum stock or comes within 90 days of expiry, or the pharmacist asks for a restock |
| **Steps** | Flag the item → draft the supplier order → pharmacist approves (required click) → order saved as *pending delivery* → pharmacist confirms the batch and photographs the invoice → agent reads it and checks it against the order → stock updated |
| **Done** | Stock matches the invoice exactly, every mismatch is flagged to the pharmacist, and nothing is ordered or added without a named pharmacist's action |

## How it works

| Step | Who | Code |
|---|---|---|
| Low stock / near-expiry alerts | Code (no AI) | `pharmacy/alerts.py` |
| Draft order + supplier message | Code (no AI) | `pharmacy/orders.py` |
| **Approve order** | **Pharmacist click, enforced in code** | `orders.approve_order()` |
| Read invoice photo / PDF | Claude (vision, structured JSON output) | `pharmacy/invoice.py` |
| Compare invoice to order | Code (no AI) | `pharmacy/reconcile.py` |
| Add to stock | Automatic only if everything matches; otherwise a pharmacist decides | `pharmacy/receive.py` |

AI is used only where it's needed (reading messy invoices). Every decision that changes money or stock is plain code with a human gate.

### Security ("Secure and in control")
- **The lock is in code, not in a prompt.** `approve_order()` needs a named pharmacist; `supplier_message()` refuses unapproved orders; `receive_delivery()` needs batch confirmation and refuses to add stock on any mismatch unless a pharmacist accepts it.
- **Prompt injection.** The invoice is treated as untrusted data. Claude has no tools and can only return a fixed JSON schema. Text on an invoice addressed to an AI is flagged and the delivery goes to human review (see test case `synthetic_19`).
- **Keys.** The API key lives in `.env`, which is git-ignored.
- **Audit log.** Every agent and human action is recorded, with who did it.
- The app only listens on `localhost`.

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env        # then paste your ANTHROPIC_API_KEY into .env
streamlit run app.py
```

## Prove it: 20 cases

```bash
python eval/make_synthetic.py   # 20 synthetic placeholder invoices (until real ones are added)
python eval/run_eval.py         # pass rate, humans needed, cost per run
python tests/test_offline.py    # logic tests, no API calls
```

Each case is a folder in `eval/cases/` with an invoice image and `case.json` (the order plus the correct answer).
To add a **real** case, create `eval/cases/real_01/`, add the invoice photo (blur patient or pharmacy names), and write `case.json` in the same format.
Run only the real ones with `python eval/run_eval.py real_`.

Every run is appended to `eval/results/history.csv`. That's your pass-rate curve for the checkpoints.

## Honest status
- The 20 cases in `eval/cases/synthetic_*` are **generated**, not real invoices. They need replacing with real ones.
- The pharmacy's own management system isn't connected yet; SQLite stands in for it.
- The supplier message is drafted and shown to the pharmacist; it isn't sent automatically yet (WhatsApp/email integration is next).
- All pharmacy and supplier names are fictional.
