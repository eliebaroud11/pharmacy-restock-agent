"""Pharmacist screen. Run with:  streamlit run app.py"""
import os
import tempfile
from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from pharmacy import db, orders  # noqa: E402
from pharmacy.agent import execute_plan, plan_followup  # noqa: E402
from pharmacy.alerts import find_alerts  # noqa: E402
from pharmacy.invoice import read_invoice  # noqa: E402
from pharmacy.receive import receive_delivery  # noqa: E402
from pharmacy.safe import plain  # noqa: E402
from pharmacy.seed import seed  # noqa: E402

DEMO_MODE = os.environ.get("PHARMA_DEMO", "") == "1"

TOOL_LABELS = {"receive_items": "📥 Add to stock", "hold_items": "⏸️ Set aside (not added)",
               "draft_reorder": "🔁 Draft a re-order", "draft_supplier_message": "✉️ Message to supplier",
               "ask_pharmacist": "❓ Question for you"}
STATUS = {  # label, Streamlit colour
    "draft": ("Draft", "orange"), "pending_delivery": ("Awaiting delivery", "blue"),
    "needs_review": ("Needs review", "red"), "received": ("Received", "green"), "closed": ("Closed", "gray"),
}

# Static styling only (no user or AI text ever goes through unsafe_allow_html).
CSS = """
<style>
  .block-container { padding-top: 3.5rem; padding-bottom: 3rem; max-width: 1280px; }
  footer { visibility: hidden; }
  .rs-header { display: flex; align-items: center; gap: 14px; margin-bottom: 4px; }
  .rs-logo { width: 46px; height: 46px; border-radius: 12px; background: #137A59; color: #fff;
             display: flex; align-items: center; justify-content: center; font-size: 24px; }
  .rs-title { font-size: 1.65rem; font-weight: 700; color: #0F2E2C; line-height: 1.1; margin: 0; }
  .rs-sub { color: #5A6B69; font-size: 0.95rem; margin: 2px 0 0 0; }
  div[data-testid="stMetric"] { background: #FFFFFF; border: 1px solid #DCE5DF; border-radius: 12px;
                                padding: 14px 18px; }
  div[data-testid="stMetricLabel"] p { font-size: 0.85rem; color: #5A6B69; }
  button[data-baseweb="tab"] p { font-size: 1rem; font-weight: 600; }
  div[data-testid="stVerticalBlockBorderWrapper"] { background: #FFFFFF; border-radius: 12px; }
  .rs-step { font-size: 0.8rem; font-weight: 700; letter-spacing: .06em; color: #137A59; margin-bottom: 2px; }
</style>
"""


def badge(status):
    label, colour = STATUS.get(status, (status, "gray"))
    return f":{colour}-background[{label}]"


def describe(action):
    """One-line description of an agent action. All AI-written text is escaped (shown as plain text)."""
    inp = action["input"]
    if action["tool"] in ("receive_items", "hold_items", "draft_reorder"):
        items = "; ".join(plain(f"{i.get('name')} × {i.get('qty')}" + (f" (batch {i['batch_no']})" if i.get("batch_no") else ""))
                          for i in inp.get("items", []))
        return f"{items}. {plain(inp.get('reason', ''))}"
    if action["tool"] == "ask_pharmacist":
        return plain(inp.get("question", ""))
    return plain(inp.get("reason", ""))


def step(n, title):
    st.markdown(f'<div class="rs-step">STEP {n}</div>', unsafe_allow_html=True)
    st.markdown(f"**{title}**")


st.set_page_config(page_title="Restock Agent", page_icon="💊", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
conn = db.connect()
if conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0] == 0:
    seed(conn)

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown("### 💊 Restock Agent")
    st.caption("Demo Pharmacy · fictional data")
    pharmacist = st.text_input("Pharmacist on duty", key="pharmacist", placeholder="Your name")
    if pharmacist:
        st.success(f"On duty: {plain(pharmacist, 60)}")
    else:
        st.warning("Enter your name to approve orders or receive deliveries.")
    st.divider()
    st.markdown("**How it works**")
    st.caption("1. The agent flags low or expiring stock.  \n2. You approve every order.  \n"
               "3. Upload the invoice: an exact match updates stock automatically.  \n"
               "4. If anything is wrong, the agent proposes a fix for you to approve.")
    if DEMO_MODE:
        st.divider()
        st.markdown("**Demo controls**")
        # Wipes everything (including the audit log), so it exists only in demo mode and needs a second click.
        sure = st.checkbox("I want to erase all data", key="reset_sure")
        if st.button("Reset demo data", disabled=not sure):
            seed(conn)
            st.session_state.pop("reset_sure", None)
            st.rerun()

# ---------------- Header + KPIs ----------------
st.markdown(
    '<div class="rs-header"><div class="rs-logo">💊</div><div>'
    '<p class="rs-title">Restock Agent</p>'
    f'<p class="rs-sub">Stock alerts, supplier orders and invoice checks · {date.today().strftime("%A %d %B %Y")}</p>'
    "</div></div>", unsafe_allow_html=True)

alerts = find_alerts(conn)
counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM orders GROUP BY status")}
k1, k2, k3, k4 = st.columns(4)
k1.metric("Need attention", sum(not a["already_on_order"] for a in alerts))
k2.metric("Orders to approve", counts.get("draft", 0))
k3.metric("Awaiting delivery", counts.get("pending_delivery", 0))
k4.metric("Deliveries to review", counts.get("needs_review", 0))
st.write("")

tab_alerts, tab_orders, tab_receive, tab_stock, tab_log = st.tabs(
    ["🔔  Alerts", "📝  Orders", "📦  Receive delivery", "📊  Stock", "🧾  Audit log"]
)

# ---------------- Alerts ----------------
with tab_alerts:
    st.subheader("Medicines that need attention")
    if not alerts:
        st.success("Nothing is low or close to expiry.")
    picks = []
    for a in alerts:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 2, 1.3], vertical_alignment="center")
            tags = []
            if any(r.startswith("low stock") for r in a["reasons"]):
                tags.append(":red-background[Low stock]")
            if any("expire" in r for r in a["reasons"]):
                tags.append(":orange-background[Expiring soon]")
            c1.markdown(f"**{a['name']}** &nbsp; {' '.join(tags)}")
            c1.caption(f"{'; '.join(a['reasons']).capitalize()} · Supplier: {a['supplier']}")
            if a["already_on_order"]:
                c2.markdown(":blue-background[On an open order]")
                continue
            qty = c2.number_input("Order qty", min_value=0, value=int(a["suggested_qty"]), key=f"q{a['medicine_id']}",
                                  label_visibility="collapsed")
            if c3.checkbox("Order", key=f"c{a['medicine_id']}"):
                picks.append((a["medicine_id"], qty))

    with st.expander("Order something else manually"):
        meds = conn.execute("SELECT id, name FROM medicines ORDER BY name").fetchall()
        names = {m["name"]: m["id"] for m in meds}
        manual = st.multiselect("Medicines", list(names))
        for n in manual:
            picks.append((names[n], st.number_input(f"Qty: {n}", min_value=1, value=10, key=f"m{names[n]}")))

    if st.button(f"Draft order for {len(picks)} item(s)" if picks else "Draft order", type="primary", disabled=not picks):
        ids = orders.draft_orders(conn, picks, reason="alert" if alerts else "manual request")
        for k in [k for k in st.session_state if str(k).startswith(("c", "m"))]:
            del st.session_state[k]
        st.session_state["flash"] = f"Drafted order(s) {', '.join('#' + str(i) for i in ids)}. Review them in the Orders tab."
        st.rerun()
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

# ---------------- Orders ----------------
with tab_orders:
    st.subheader("Supplier orders")
    all_orders = conn.execute("SELECT o.id, o.status FROM orders o WHERE o.status != 'cancelled' ORDER BY o.id DESC").fetchall()
    if not all_orders:
        st.info("No orders yet. Draft one from the Alerts tab.")
    for o in all_orders:
        order, lines = db.order_with_lines(conn, o["id"])
        icon = {"draft": "🟠", "pending_delivery": "🔵", "needs_review": "🔴", "received": "🟢"}.get(order["status"], "⚪")
        label = STATUS.get(order["status"], (order["status"], ""))[0]
        with st.expander(f"{icon}  Order #{order['id']}  ·  {order['supplier']}  ·  {label}",
                         expanded=order["status"] == "draft"):
            if order["status"] == "draft":
                st.markdown(f"{badge('draft')} &nbsp; Review quantities, then approve to place the order.")
                for l in lines:
                    new = st.number_input(l["name"], min_value=0, value=int(l["qty"]), key=f"ol{order['id']}_{l['medicine_id']}")
                    if new != l["qty"]:
                        orders.update_line(conn, order["id"], l["medicine_id"], int(new), pharmacist or "unknown")
                        st.rerun()
                st.text_area("Message to supplier (preview)", order["message"], height=200, disabled=True,
                             key=f"msg{order['id']}")
                c1, c2, _ = st.columns([2, 1, 3])
                # THE LOCK: the button is disabled without a name, and approve_order() re-checks in code.
                if c1.button("✅ Approve and place order", key=f"ap{order['id']}", type="primary", disabled=not pharmacist):
                    try:
                        orders.approve_order(conn, order["id"], pharmacist)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
                if c2.button("Cancel order", key=f"cx{order['id']}"):
                    orders.cancel_order(conn, order["id"], pharmacist or "unknown")
                    st.rerun()
                if not pharmacist:
                    st.caption("Enter your name in the sidebar to approve.")
            else:
                st.markdown(f"{badge(order['status'])} &nbsp; Approved by **{plain(order['approved_by'], 60)}** "
                            f"on {(order['approved_at'] or '?').replace('T', ' at ')}")
                st.dataframe([{"Medicine": l["name"], "Quantity": l["qty"]} for l in lines], hide_index=True, width="stretch")
                st.text_area("Message to send the supplier", orders.supplier_message(conn, order["id"]),
                             height=180, key=f"sm{order['id']}")
                if order["contact"]:
                    st.caption(f"Supplier contact: {order['contact']}")

# ---------------- Receive ----------------
with tab_receive:
    st.subheader("Receive a delivery")
    waiting = [dict(r) for r in conn.execute(
        "SELECT o.id, o.status, s.name AS supplier FROM orders o JOIN suppliers s ON s.id = o.supplier_id "
        "WHERE o.status IN ('pending_delivery', 'needs_review') ORDER BY o.id"
    ).fetchall()]
    if not waiting:
        st.info("No orders are waiting for delivery. Approve an order first.")
    else:
        with st.container(border=True):
            step(1, "Which order arrived?")
            choice = st.selectbox("Order", waiting, label_visibility="collapsed",
                                  format_func=lambda r: f"#{r['id']} · {r['supplier']} · {STATUS[r['status']][0]}")
            order, lines = db.order_with_lines(conn, choice["id"])
            st.dataframe([{"Medicine": l["name"], "Ordered": l["qty"]} for l in lines], hide_index=True, width="stretch")
        with st.container(border=True):
            step(2, "Check the boxes")
            confirmed = st.checkbox("I checked the boxes: the batch matches this order", key=f"bc{order['id']}")
        ready = confirmed and bool(pharmacist)
        with st.container(border=True):
            step(3, "Upload the invoice")
            st.caption("The agent reads it, checks every line against the order, and updates stock if it matches exactly.")
            upload = st.file_uploader("Invoice photo or PDF", type=["jpg", "jpeg", "png", "webp", "pdf"],
                                      disabled=not ready, key=f"up{order['id']}", label_visibility="collapsed")
            if not pharmacist:
                st.caption("Enter your name in the sidebar first.")
            elif not confirmed:
                st.caption("Tick step 2 to unlock the upload.")

        # A new upload is processed once: read -> check -> stock updated on an exact match, else flagged.
        file_key = f"{order['id']}:{upload.file_id}" if upload is not None else None
        if upload is not None and ready and st.session_state.get("processed") != file_key:
            st.session_state["processed"] = file_key
            catalog = [r["name"] for r in conn.execute("SELECT name FROM medicines ORDER BY name")]
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(upload.name).suffix) as f:
                f.write(upload.getbuffer())
            with st.spinner("Reading the invoice and checking it against the order..."):
                res = read_invoice(f.name, catalog)
            Path(f.name).unlink(missing_ok=True)
            if res.error:
                st.session_state["receipt"] = {"order_id": order["id"], "error": res.error}
            else:
                result = receive_delivery(conn, order["id"], res.data, pharmacist, confirmed)
                rec = {
                    "order_id": order["id"], "invoice": res.data, "result": result,
                    "meta": f"Read by {res.model} · {res.input_tokens + res.output_tokens} tokens · ${res.cost_usd:.4f}",
                }
                if not result.get("applied"):
                    # Something is wrong: the agent decides what should happen next.
                    with st.spinner("🤖 The agent is working out what to do next..."):
                        rec["plan"] = plan_followup(conn, order["id"], res.data, result["issues"]).to_dict()
                st.session_state["receipt"] = rec
            st.rerun()

    # Result of the last upload (shown even after the order leaves the waiting list).
    rec = st.session_state.get("receipt")
    if rec:
        st.write("")
        with st.container(border=True):
            if rec.get("error"):
                st.error(f"Order #{rec['order_id']}: could not read the invoice. {plain(rec['error'])}")
                if st.button("🔄 Try again", type="primary", key="retry_read"):
                    st.session_state.pop("processed", None)  # lets the same uploaded file be read again
                    st.session_state.pop("receipt", None)
                    st.rerun()
            else:
                inv, result = rec["invoice"], rec["result"]
                st.markdown(f"#### Invoice {plain(inv.get('invoice_number') or '?')}")
                st.caption(f"Order #{rec['order_id']} · from {plain(inv.get('supplier_name') or '?')} · "
                           f"dated {plain(inv.get('invoice_date') or '?')}")
                st.dataframe([{"Item on invoice": l["product_name"], "Matched to": l["catalog_match"],
                               "Batch": l["batch_no"], "Expiry": l["expiry"], "Qty": l["qty"]}
                              for l in inv.get("lines", [])], hide_index=True, width="stretch")
                if result.get("applied"):
                    added = ", ".join(plain(f"{r['name']} +{r['qty']}") for r in result["receive"])
                    st.success(f"✅ **Invoice matches the order.** Stock updated automatically: {added}.")
                else:
                    st.error("⚠️ **The invoice does not match the order.** Nothing has been changed yet.")
                    for i in result["issues"]:
                        st.markdown(f"- **{i['type'].replace('_', ' ').capitalize()}**: {plain(i['detail'])}")
                    still_open = conn.execute("SELECT status FROM orders WHERE id = ?", (rec["order_id"],)).fetchone()
                    is_open = still_open and still_open["status"] == "needs_review"
                    plan = rec.get("plan")
                    if rec.get("done"):
                        d = rec["done"]
                        st.success("✅ **Approved plan carried out.**")
                        if d["received"]:
                            st.markdown("**Added to stock:** " + ", ".join(plain(f"{i['name']} +{i['qty']}") for i in d["received"]))
                        if d["held"]:
                            st.markdown("**Set aside:** " + ", ".join(plain(f"{i['name']} × {i['qty']}") for i in d["held"]))
                        if d["reorders"]:
                            st.markdown("**Draft re-order(s) created:** " + ", ".join(f"#{o}" for o in d["reorders"])
                                        + " (approve them in the Orders tab)")
                        for m in d["messages"]:
                            st.text_area("Message to send the supplier", m, height=200, key="sent_msg")
                    elif plan and is_open:
                        st.divider()
                        st.markdown("#### 🤖 The agent's plan")
                        if plan.get("error"):
                            st.warning(plain(plan["error"]))
                        if plan.get("summary"):
                            st.info(plain(plan["summary"]))
                        approved, questions = [], []
                        for a in plan.get("actions", []):
                            if a["tool"] == "ask_pharmacist":
                                questions.append(a)
                                continue
                            label = f"**{TOOL_LABELS.get(a['tool'], a['tool'])}**: {describe(a)}"
                            if st.checkbox(label, value=True, key=f"pa{rec['order_id']}_{a['id']}"):
                                approved.append(a["id"])
                            if a["tool"] == "draft_supplier_message":
                                st.text_area("Draft message", a["input"]["message"], height=180, disabled=True,
                                             key=f"pm{rec['order_id']}_{a['id']}")
                        answers = {}
                        for q in questions:
                            answers[q["input"]["question"]] = st.text_input(f"❓ {plain(q['input']['question'])}",
                                                                            key=f"qa{rec['order_id']}_{q['id']}")
                        if plan.get("rejected"):
                            with st.expander(f"Proposals blocked by the safety rules ({len(plan['rejected'])})"):
                                for r in plan["rejected"]:
                                    st.markdown(f"- {TOOL_LABELS.get(r['tool'], r['tool'])}: {plain(r['why'])}")
                        c1, c2, _ = st.columns([2, 2, 2])
                        if c1.button("✅ Approve selected actions", type="primary", disabled=not pharmacist or not approved,
                                     key=f"ok{rec['order_id']}"):
                            try:
                                done = execute_plan(conn, rec["order_id"], plan, set(approved), pharmacist, inv,
                                                    result["issues"])
                                st.session_state["receipt"] = {**rec, "done": done}
                            except (ValueError, PermissionError) as e:
                                st.error(str(e))
                            st.rerun()
                        if questions and c2.button("🔄 Re-plan with my answers", key=f"rp{rec['order_id']}",
                                                   disabled=not any(answers.values())):
                            with st.spinner("🤖 Re-planning..."):
                                new = plan_followup(conn, rec["order_id"], inv, result["issues"],
                                                    answers={k: v for k, v in answers.items() if v}).to_dict()
                            st.session_state["receipt"] = {**rec, "plan": new}
                            st.rerun()
                        st.caption(f"Agent: {plan.get('turns', 0)} step(s) · ${plan.get('cost_usd', 0):.4f}")
                    if is_open and pharmacist and not rec.get("done"):
                        with st.expander("Other options"):
                            if st.button("Accept the whole delivery as invoiced", key=f"acc{rec['order_id']}"):
                                res2 = receive_delivery(conn, rec["order_id"], inv, pharmacist, True, accept_discrepancies=True)
                                st.session_state["receipt"] = {**rec, "result": res2}
                                st.rerun()
                st.caption(rec["meta"])
            if st.button("Clear", key="clear_receipt"):
                st.session_state.pop("receipt", None)
                st.session_state.pop("processed", None)
                st.rerun()

# ---------------- Stock ----------------
with tab_stock:
    st.subheader("Current stock")
    soon = date.today().toordinal() + 90
    rows = []
    for r in db.stock_summary(conn):
        exp = r["nearest_expiry"]
        state = "Low" if r["qty"] < r["min_stock"] else ("Expiring" if exp and date.fromisoformat(exp).toordinal() <= soon else "OK")
        rows.append({"Medicine": r["name"], "Status": state, "In stock": r["qty"],
                     "Level": round(min(r["qty"] / r["target_stock"], 1.0) * 100) if r["target_stock"] else 0,
                     "Minimum": r["min_stock"], "Target": r["target_stock"],
                     "Nearest expiry": date.fromisoformat(exp) if exp else None, "Supplier": r["supplier"]})
    st.dataframe(rows, hide_index=True, width="stretch", column_config={
        "Level": st.column_config.ProgressColumn("Level vs target", min_value=0, max_value=100, format="%d%%"),
        "Nearest expiry": st.column_config.DateColumn(format="D MMM YYYY"),
    })

# ---------------- Audit log ----------------
with tab_log:
    st.subheader("Audit log")
    st.caption("Everything the agent and pharmacists did, newest first.")
    rows = conn.execute("SELECT at, actor, action, details FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
    st.dataframe([{"When": r["at"].replace("T", " "), "Who": r["actor"], "What": r["action"], "Details": r["details"] or ""}
                  for r in rows], hide_index=True, width="stretch",
                 column_config={"Details": st.column_config.TextColumn(width="large")})
