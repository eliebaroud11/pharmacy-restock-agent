# AlphaHack 2026 submission: Pharmacy Restock Agent

**Repository:** https://github.com/eliebaroud11/pharmacy-restock-agent

## One-line pitch
An AI agent that runs a Lebanese community pharmacy's restocking job from start to finish: it flags low and
expiring stock, drafts the supplier order, waits for the pharmacist's approval, reads the delivery invoice from a
photo, updates stock on an exact match, and when anything is wrong, plans the fix for the pharmacist to approve.

## The job
Whose job: a community pharmacist in Lebanon. Trigger: a medicine runs low or nears expiry, or the pharmacist asks.
Done: stock matches what arrived, every problem is flagged and followed up, nothing is ordered, added or sent
without a signed-in pharmacist's approval, and every step is in the audit log.

## Results
- 20/20 test invoices handled correctly; 9/20 sent to a pharmacist, each because the invoice had a real problem
  (synthetic invoices; real ones being added)
- Follow-up agent: right next steps on 9/9 problem deliveries
- Prompt injection: 12 malicious invoices, 12/12 detected, 0 harm; still 0 harm with detection switched off
- Security: 23/23 attack tests (SQL injection, login attacks, privilege escalation, forged plans, double
  receiving, malicious files); Bandit 0 issues; no known vulnerable libraries
- Cost: about $0.001 per invoice and $0.002 per problem delivery, vs about $2 of pharmacist time
- Model chosen after testing 7 models: Gemini 3.1 Flash-Lite (best accuracy and fastest)

## Human in control
- Orders need a signed-in pharmacist's click, enforced in code
- Stock updates automatically only on an exact match with the batch confirmed
- The agent's tools only propose; code re-checks every action; supplier messages can't carry links or payment details
- WhatsApp/email messages open ready to send; the pharmacist presses Send

## Honest status
Test invoices are synthetic; the pharmacy's own software isn't connected (SQLite stands in); runs on one computer
with no backups yet; no password reset flow.

## Run it
See the README: install Python 3.12, `pip install -r requirements.txt`, add an OpenRouter key to `.env`,
`streamlit run app.py`, then create the administrator account on first launch.
