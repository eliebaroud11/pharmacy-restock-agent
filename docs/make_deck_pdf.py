"""Build docs/slides.pdf (a PDF copy of the pitch deck).  Run: python docs/make_deck_pdf.py"""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.pdfgen import canvas

W, H = 1920 / 2, 1080 / 2  # 16:9
INK, PAPER, BODY, MUTE = colors.HexColor("#111827"), colors.HexColor("#F9FAFB"), colors.HexColor("#374151"), colors.HexColor("#6B7280")
M = 48

SLIDES = [
    ("ALPHAHACK 2026", "Pharmacy Restock Agent",
     ["From \"we're running low\" to stock updated from the invoice photo,", "with the pharmacist in control.", "",
      "github.com/eliebaroud11/pharmacy-restock-agent"], True),
    ("A REAL JOB, A REAL PERSON", "Every delivery is checked by hand, line by line",
     ["A community pharmacist in Lebanon compares each supplier invoice with the order,",
      "checks batch numbers and expiry dates, then types every batch into stock.", "",
      "- Several deliveries every week, each checked line by line",
      "- About 20 minutes per delivery (our estimate)",
      "- Short deliveries, wrong batches and expiring stock are easy to miss"], False),
    ("THE AGENT DOES THE WHOLE JOB", "Six steps, one human lock",
     ["1. Alert: flags low stock and batches near expiry (agent)",
      "2. Draft: writes the order and the supplier message (agent)",
      "3. Approve: nothing is ordered until a signed-in pharmacist clicks, enforced in code",
      "4. Send and receive: WhatsApp/email ready to send; pharmacist confirms the batch, photographs the invoice",
      "5. Check: AI reads the invoice; code compares every line with the order (agent)",
      "6. Stock: exact match updates stock; any problem, the agent plans the fix for approval"], False),
    ("IT WORKS, EVERY TIME", "20 of 20 test invoices handled right",
     ["- 20/20 synthetic test invoices correct, about 3 seconds each",
      "- 9/20 sent to a pharmacist, each because the invoice had a real problem",
      "- Follow-up agent: right next steps on 9/9 problem deliveries",
      "- Best of 7 models tested: Gemini 3.1 Flash-Lite (accuracy and speed)",
      "- Real invoices from our pharmacist are being added"], False),
    ("SECURE AND IN CONTROL", "The agent can't order or change stock on its own",
     ["- Lock in code: orders need a signed-in pharmacist's approval",
      "- Agent proposes, code checks: unsafe actions refused, pharmacist approves the rest",
      "- Prompt injection: 12 malicious invoices, 12 detected, 0 harm; 0 harm even with detection off",
      "- Accounts: hashed passwords, lockout, sessions end on deactivation; full audit log",
      "- 23/23 attack tests (SQL injection, privilege escalation, forged plans, double receiving)",
      "- Bandit: 0 issues; libraries: no known vulnerabilities"], True),
    ("THE BUSINESS MODEL", "A fraction of a cent of AI replaces minutes of a pharmacist",
     ["- AI cost: about $0.002 per delivery, even when the agent plans a fix",
      "- Pharmacist time: about $2 per delivery (estimate: 20 min at $6/hour)",
      "- Who pays: independent community pharmacies in Lebanon, monthly subscription",
      "- Start next month: one pharmacy, a phone camera and a laptop; no integration needed"], False),
    ("HONEST STATUS", "What's real today, and what isn't yet",
     ["Working now: alerts, ordering with approval lock, WhatsApp/email sending, invoice check,",
      "automatic stock update, follow-up agent, staff accounts, audit log, results and tests.", "",
      "Not yet: test invoices are synthetic; the pharmacy's own software isn't connected;",
      "runs on one computer with no backups; no password-reset flow."], False),
    ("NEXT", "From one pharmacy to many",
     ["1. Real invoices: push the pass rate on real deliveries",
      "2. Read supplier replies on WhatsApp and handle them with the agent",
      "3. Write stock straight into the pharmacy's own software", "", "Thank you. Live demo at our table."], True),
]


def main():
    out = Path(__file__).resolve().parent / "slides.pdf"
    c = canvas.Canvas(str(out), pagesize=landscape((H, W)))
    c.setTitle("Pharmacy Restock Agent - pitch deck")
    for i, (eyebrow, title, lines, dark) in enumerate(SLIDES, start=1):
        c.setFillColor(INK if dark else PAPER)
        c.rect(0, 0, W, H, stroke=0, fill=1)
        fg, body = (PAPER, colors.HexColor("#D1D5DB")) if dark else (INK, BODY)
        c.setFillColor(MUTE if not dark else colors.HexColor("#9CA3AF"))
        c.setFont("Helvetica-Bold", 11)
        c.drawString(M, H - M - 6, eyebrow)
        c.setFillColor(fg)
        size = 34 if i == 1 else 26
        c.setFont("Helvetica-Bold", size)
        c.drawString(M, H - M - 18 - size, title)
        c.setFont("Helvetica", 14)
        c.setFillColor(body)
        y = H - M - 40 - size - 26
        for line in lines:
            c.drawString(M, y, line)
            y -= 24
        c.setFont("Helvetica", 9)
        c.setFillColor(MUTE)
        c.drawRightString(W - M, 24, f"{i} / {len(SLIDES)}")
        c.showPage()
    c.save()
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
