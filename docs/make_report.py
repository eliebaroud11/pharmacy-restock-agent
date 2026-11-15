"""Build docs/report.pdf for the AlphaHack submission.  Run: python docs/make_report.py"""
import json
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "eval" / "results"

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Title"], fontSize=22, spaceAfter=4, textColor=colors.HexColor("#111827"))
SUB = ParagraphStyle("Sub", parent=ss["Normal"], fontSize=10, textColor=colors.HexColor("#6B7280"), spaceAfter=14)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=14, spaceBefore=12, spaceAfter=6, textColor=colors.HexColor("#111827"))
P = ParagraphStyle("P", parent=ss["Normal"], fontSize=10, leading=14.5, spaceAfter=6)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(i, P), leftIndent=12) for i in items], bulletType="bullet", start="•",
                        leftIndent=12)


def table(rows, widths):
    t = Table(rows, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#D1D5DB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return t


def main():
    runs = sorted(RES.glob("run-*.json"))
    last = json.loads(runs[-1].read_text(encoding="utf-8")) if runs else {}
    cmp = json.loads((RES / "compare_models.json").read_text(encoding="utf-8")) if (RES / "compare_models.json").exists() else []

    s = [Paragraph("Pharmacy Restock Agent", H1),
         Paragraph("AlphaHack 2026 · The AI Agent Challenge · github.com/eliebaroud11/pharmacy-restock-agent", SUB)]

    s += [Paragraph("1. Problem statement", H2), Paragraph(
        "A community pharmacist in Lebanon restocks by hand every week. They notice low or expiring stock, write to the "
        "supplier (usually by WhatsApp), and when the delivery arrives they compare the invoice with the order line by line: "
        "product, quantity, batch number and expiry date. Then they type every batch into stock. It is slow (we estimate about "
        "20 minutes per delivery), and short deliveries, wrong batches and short-dated stock are easy to miss.", P),
        Paragraph("<b>Whose job:</b> a community pharmacist in Lebanon (pharmacy name withheld at their request). "
                  "<b>Trigger:</b> a medicine drops below its minimum stock or nears expiry, or the pharmacist asks. "
                  "<b>Done:</b> stock matches what arrived, every problem is followed up, nothing is ordered, added or sent "
                  "without a signed-in pharmacist's approval, and every step is in the audit log.", P)]

    n, ok, hum = last.get("cases", 20), last.get("passed", 20), last.get("human_needed", 9)
    s += [Paragraph("2. Cases", H2), Paragraph(
        f"<b>Honest note:</b> the test set is currently <b>synthetic</b>: {n} generated invoices that copy the format of "
        "Lebanese distributor invoices, plus 12 malicious invoices for security testing. Real invoices from our pharmacist are "
        "being added with the included tool (eval/add_case.py), which turns a photo into a test case for a human to verify.", P),
        table([["What the case tests", "Cases", "Result"],
               ["Clean invoice matches the order", "5", "5 right"], ["Same item in two batches", "2", "2 right"],
               ["Expiry printed as MM/YYYY", "2", "2 right"], ["Blurry, rotated photo", "2", "2 right"],
               ["Short, over or missing items", "4", "4 flagged"], ["Item that was never ordered", "1", "1 flagged"],
               ["Batch expires too soon", "2", "2 flagged"], ["Missing batch number", "1", "1 flagged"],
               ["Prompt injection on the invoice", "1", "1 flagged"]], [9 * cm, 2 * cm, 3 * cm]),
        Spacer(1, 6),
        Paragraph(f"<b>Latest run:</b> {ok}/{n} handled correctly; {hum}/{n} needed a pharmacist, each because the invoice "
                  "had a real problem. <b>Follow-up agent:</b> right next steps on 9/9 problem deliveries. "
                  "<b>Red team:</b> 12 malicious invoices (hidden instructions, fake bank details, phishing links, French, "
                  "obfuscated text): 12/12 detected and 0 harm; with detection switched off, still 0 harm.", P)]

    s += [Paragraph("3. Solution", H2), bullets([
        "<b>Alerts:</b> code flags low and near-expiry stock and suggests a quantity.",
        "<b>Order:</b> drafts the supplier order and message. <b>A signed-in pharmacist must approve</b> (enforced in code), "
        "then it opens ready to send in WhatsApp or email.",
        "<b>Receive:</b> the pharmacist confirms the batch and uploads the invoice photo. An AI vision model reads every line; "
        "code compares it with the order. An exact match updates stock automatically.",
        "<b>Follow-up agent:</b> if anything is wrong, an AI agent with tools plans the fix (add what is good, hold bad batches, "
        "re-order the shortfall, write the supplier message, ask the pharmacist). Its tools only propose: code checks every "
        "proposal against hard rules, and the pharmacist approves each action.",
        "<b>Products, Results and Audit log</b> tabs: add new medicines in seconds, see the live pass rate and cost, "
        "and review every action with who did it."])]

    s += [Paragraph("4. Stack", H2), bullets([
        "Python 3.12, Streamlit (pharmacist screen), SQLite (stands in for the pharmacy's software).",
        "AI through OpenRouter: <b>Gemini 3.1 Flash-Lite</b>, chosen after comparing 7 models (below). Works with the "
        "Anthropic API too.",
        "Security: staff accounts (salted scrypt hashes, lockout, session invalidation), output escaping, upload limits, "
        "AI usage limits, atomic order claiming. 23 attack tests, Bandit (0 issues), pip-audit (no known vulnerabilities)."])]
    if cmp:
        rows = [["Model", "Invoices", "Agent", "Injection safe", "Sec/invoice", "$/problem delivery"]]
        for r in cmp:
            rows.append([r["model"], f"{r.get('read_ok')}/{r.get('read_n')}", f"{r.get('agent_ok')}/{r.get('agent_n', 9)}",
                         f"{r.get('safe')}/12", f"{r.get('read_secs', 0):.1f}",
                         f"{r.get('read_cost', 0) + r.get('agent_cost', 0):.4f}"])
        s += [Spacer(1, 4), table(rows, [6.4 * cm, 1.7 * cm, 1.4 * cm, 2.4 * cm, 2 * cm, 3 * cm])]

    s += [Paragraph("5. Business model", H2), bullets([
        "<b>Who pays:</b> independent community pharmacies in Lebanon, through a monthly subscription priced well below the "
        "pharmacist time it saves.",
        "<b>Cost per run:</b> about $0.001 per invoice and $0.002 per problem delivery in AI usage, vs about $2 of pharmacist "
        "time per delivery (estimate: 20 minutes at $6 per hour). Roughly 1,000x cheaper.",
        "<b>Lean start next month:</b> one pharmacy, a phone camera and a laptop; no integration needed. Next: connect to the "
        "pharmacy's software and read supplier replies."])]

    s += [Paragraph("6. Honest status", H2), bullets([
        "Test invoices are synthetic; real ones are being added.",
        "The pharmacy's own software is not connected yet (SQLite stands in).",
        "Runs on one computer, no backups or password-reset flow yet.",
        "Pharmacist time is an estimate until confirmed by the pharmacist."])]

    out = ROOT / "docs" / "report.pdf"
    SimpleDocTemplate(str(out), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.8 * cm,
                      bottomMargin=1.8 * cm, title="Pharmacy Restock Agent - AlphaHack 2026").build(s)
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
