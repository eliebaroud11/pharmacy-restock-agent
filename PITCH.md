# Pitch kit

Everything for the checkpoints, the 2-minute Loom, the slides and the live judging.
Items marked **[FILL]** need real information from you or the pharmacist. Don't present them as facts until filled.

---

## Checkpoint post (Saturday 23:00)

> **Pharmacy Restock Agent**: restocking a community pharmacy, from low-stock alert to stock updated from the invoice photo.
> Pass rate: **20/20** on synthetic invoices (clean prints, split batches, MM/YYYY dates, blurry photos, short/over/missing items, short expiry, missing batch, prompt injection).
> Humans needed: 9/20, all of them intentional problem invoices that *should* go to the pharmacist.
> Next: replacing synthetic cases with real invoices from our pharmacist.

Update the numbers from `eval/results/history.csv` before posting. If real cases are in by then, post the real-case pass rate instead (`python eval/run_eval.py real_`).

---

## 2-minute Loom script

| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | Title slide | "Every week, a pharmacist in Lebanon checks deliveries line by line against the order, then types each batch into stock. We built an agent that does it." |
| 0:15–0:35 | App → Alerts tab | "The agent watches stock and expiry dates. Here it flags Amlodipine as low and Amoxicillin as expiring, and suggests quantities." Tick both → **Draft order**. |
| 0:35–0:55 | Orders tab | "It drafts the supplier order. Nothing is sent until a named pharmacist approves. That lock is in the code, not the prompt." Click **Approve**. |
| 0:55–1:25 | Receive tab | Tick "batch matches" → upload the `--short` demo invoice. "It finds the problem, one item is short, and the agent decides what to do: add what's good, re-order the missing units, and draft the message to the supplier. I approve with one click." Click **Approve selected actions**. (Clean invoice on a second order: "Exact match, so stock is updated automatically.") |
| 1:25–1:40 | Stock + Audit log tabs | "Stock updated, and every action is logged with who did it." |
| 1:40–2:00 | Results slide | "20 of 20 cases right, 0 cents per delivery with a free model vs about $[FILL] of pharmacist time. Next: real invoices and WhatsApp ordering." |

Before recording: draft and approve the order in the app, note its number (say #3), then run
`.venv\Scripts\python.exe eval\make_demo_invoice.py 3` and `... make_demo_invoice.py 3 --short`.
The two images land in `demo_invoices\`. Upload the short one first (it flags the order), then the matching one. Rehearse once, then record.

---

## Slides (map to the 100-point rubric)

1. **Title.** Pharmacy Restock Agent · team names.
2. **A real job, a real person (15).** Who: community pharmacist, [FILL: town], Lebanon. Weekly: [FILL: N] deliveries, [FILL: minutes] each. Pain: line-by-line checking, missed short deliveries, expired stock. *Play the 30-second voice note here.*
3. **The agent does the whole job (15).** Alert → draft order → **pharmacist approves** → delivery → invoice photo → check → stock. One screenshot per step.
4. **It works, every time (25).** Pass-rate table and curve (from `history.csv`). What the 20 cases cover. Humans needed, and why (each was a real problem). Plan to push the number down.
5. **Secure and in control (15).**
   - Approval lock in code: `approve_order()` needs a named pharmacist.
   - Stock added automatically only on an exact match; otherwise the pharmacist decides.
   - Invoice text treated as untrusted data; injection attempt caught (case 19).
   - Keys in `.env`, never in Git; app only on localhost; full audit log.
6. **Business model (20).**
   - Who pays: the pharmacy, monthly subscription [FILL: price, e.g. $15–30/month].
   - Cost per run: $0.00 with a free model; ~$[FILL] per invoice with a paid model.
   - Human cost per delivery: [FILL: minutes] × [FILL: $/hour] = $[FILL].
   - Market: [FILL: number of pharmacies in Lebanon, with a source].
   - Lean start next month: one pharmacy, photo upload + WhatsApp, no system integration needed.
7. **Honest status (part of the pitch score, 10).** Real vs synthetic cases; pharmacy system not yet connected (SQLite stands in); supplier message drafted, sending is manual; free model may log data, so names are blurred.
8. **Next steps.** Real invoices, WhatsApp ordering, connect to the pharmacy's system.

---

## Live judging: the judges' 2 unseen cases (Twist 02)

When the judges hand you an invoice:
1. Create and approve an order with the items they say were ordered (Alerts → *Order something else manually*).
2. Receive tab → confirm batch → upload their photo.
3. Read the result out loud, including any flags.

If a product isn't in the demo catalog, add it in `pharmacy/seed.py` → `MEDICINES`, then click **Reset demo data** in the sidebar. Practise this once before Sunday.

---

## Adding real cases

```bash
.venv\Scripts\python.exe eval\add_case.py C:\path\to\invoice_photo.jpg --supplier "Supplier name"
```

Then open the new `eval/cases/real_NN/case.json` next to the paper invoice, fix anything wrong, set `"verified": true`, and run:

```bash
.venv\Scripts\python.exe eval\run_eval.py real_
```

Blur patient and pharmacy names in photos before committing.
