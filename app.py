"""Pharmacist screen. Run with:  streamlit run app.py"""
import json
import tempfile
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from pharmacy import db, orders  # noqa: E402
from pharmacy.alerts import find_alerts  # noqa: E402
from pharmacy.invoice import read_invoice  # noqa: E402
from pharmacy.agent import execute_plan, plan_followup  # noqa: E402
from pharmacy.receive import receive_delivery  # noqa: E402

TOOL_LABELS = {"receive_items": "📥 Add to stock", "hold_items": "⏸️ Set aside (not added)",
               "draft_reorder": "🔁 Draft a re-order", "draft_supplier_message": "✉️ Message to supplier",
               "ask_pharmacist": "❓ Question for you"}


def describe(action):
    inp = action["input"]
    if action["tool"] in ("receive_items", "hold_items", "draft_reorder"):
        items = "; ".join(f"{i.get('name')} × {i.get('qty')}" + (f" (batch {i['batch_no']})" if i.get("batch_no") else "")
                          for i in inp.get("items", []))
        return f"{items}. _{inp.get('reason', '')}_"
    if action["tool"] == "ask_pharmacist":
        return inp.get("question", "")
    return f"_{inp.get('reason', '')}_"
from pharmacy.seed import seed  # noqa: E402

st.set_page_config(page_title="Pharmacy Restock Agent", page_icon="💊", layout="wide")
conn = db.connect()

with st.sidebar:
    st.header("💊 Restock Agent")
    pharmacist = st.text_input("Pharmacist on duty", key="pharmacist", placeholder="Your name")
    if not pharmacist:
        st.warning("Enter your name to approve orders or receive deliveries.")
    st.divider()
    if st.button("Reset demo data"):
        seed(conn)
        st.success("Demo data reset.")
        st.rerun()

if conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0] == 0:
    seed(conn)

tab_alerts, tab_orders, tab_receive, tab_stock, tab_log = st.tabs(
    ["🔔 Alerts", "📝 Orders", "📦 Receive delivery", "📊 Stock", "🧾 Audit log"]
)

# ---------------- Alerts ----------------
with tab_alerts:
    st.subheader("Medicines that need attention")
    alerts = find_alerts(conn)
    if not alerts:
        st.success("Nothing is low or close to expiry.")
    picks = []
    for a in alerts:
        c1, c2, c3 = st.columns([4, 2, 1])
        c1.markdown(f"**{a['name']}**  \n{'; '.join(a['reasons'])}  \n_Supplier: {a['supplier']}_")
        if a["already_on_order"]:
            c2.info("Already on an open order")
            continue
        qty = c2.number_input("Order qty", min_value=0, value=int(a["suggested_qty"]), key=f"q{a['medicine_id']}")
        if c3.checkbox("Order", key=f"c{a['medicine_id']}"):
            picks.append((a["medicine_id"], qty))

    with st.expander("Order something else manually"):
        meds = conn.execute("SELECT id, name FROM medicines ORDER BY name").fetchall()
        names = {m["name"]: m["id"] for m in meds}
        manual = st.multiselect("Medicines", list(names))
        for n in manual:
            picks.append((names[n], st.number_input(f"Qty: {n}", min_value=1, value=10, key=f"m{names[n]}")))

    if st.button("Draft order(s) for selected items", type="primary", disabled=not picks):
        ids = orders.draft_orders(conn, picks, reason="alert" if alerts else "manual request")
        for k in [k for k in st.session_state if str(k).startswith(("c", "m"))]:
            del st.session_state[k]
        st.session_state["flash"] = f"Drafted order(s) {', '.join('#' + str(i) for i in ids)}. Review them in the Orders tab."
        st.rerun()
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))

# ---------------- Orders ----------------
with tab_orders:
    st.subheader("Orders")
    for o in conn.execute(
        "SELECT o.id, o.status FROM orders o WHERE o.status != 'cancelled' ORDER BY o.id DESC"
    ).fetchall():
        order, lines = db.order_with_lines(conn, o["id"])
        badge = {"draft": "🟡 draft", "pending_delivery": "🔵 pending delivery", "received": "🟢 received",
                 "needs_review": "🔴 needs review"}.get(order["status"], order["status"])
        with st.expander(f"Order #{order['id']} · {order['supplier']} · {badge}", expanded=order["status"] == "draft"):
            if order["status"] == "draft":
                for l in lines:
                    new = st.number_input(l["name"], min_value=0, value=int(l["qty"]), key=f"ol{order['id']}_{l['medicine_id']}")
                    if new != l["qty"]:
                        orders.update_line(conn, order["id"], l["medicine_id"], int(new), pharmacist or "unknown")
                        st.rerun()
                st.text_area("Message to supplier (preview)", order["message"], height=200, disabled=True,
                             key=f"msg{order['id']}")
                c1, c2 = st.columns(2)
                # THE LOCK: the button is disabled without a name, and approve_order() re-checks in code.
                if c1.button("✅ Approve and place order", key=f"ap{order['id']}", type="primary", disabled=not pharmacist):
                    try:
                        orders.approve_order(conn, order["id"], pharmacist)
                        st.rerun()
                    except Exception as e:
                        st.error(str(e))
                if c2.button("Cancel", key=f"cx{order['id']}"):
                    orders.cancel_order(conn, order["id"], pharmacist or "unknown")
                    st.rerun()
            else:
                st.table([{"Medicine": l["name"], "Qty": l["qty"]} for l in lines])
                st.caption(f"Approved by {order['approved_by']} at {order['approved_at']}")
                st.text_area("Message to send the supplier", orders.supplier_message(conn, order["id"]),
                             height=180, key=f"sm{order['id']}")
                if order["contact"]:
                    st.caption(f"Supplier contact: {order['contact']}")

# ---------------- Receive ----------------
with tab_receive:
    st.subheader("Receive a delivery")
    waiting = [dict(r) for r in conn.execute(
        "SELECT o.id, s.name AS supplier FROM orders o JOIN suppliers s ON s.id = o.supplier_id "
        "WHERE o.status IN ('pending_delivery', 'needs_review') ORDER BY o.id"
    ).fetchall()]
    if not waiting:
        st.info("No orders are waiting for delivery.")
    else:
        choice = st.selectbox("Which order arrived?", waiting, format_func=lambda r: f"#{r['id']} · {r['supplier']}")
        order, lines = db.order_with_lines(conn, choice["id"])
        st.table([{"Medicine": l["name"], "Ordered": l["qty"]} for l in lines])
        confirmed = st.checkbox("I checked the boxes: the batch matches this order", key=f"bc{order['id']}")
        ready = confirmed and bool(pharmacist)
        upload = st.file_uploader("Photo or PDF of the invoice: the agent reads it and updates stock if it matches",
                                  type=["jpg", "jpeg", "png", "webp", "pdf"], disabled=not ready, key=f"up{order['id']}")
        if not pharmacist:
            st.caption("Enter your name in the sidebar first.")

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
                    "meta": f"Read with {res.model} · {res.input_tokens + res.output_tokens} tokens · ${res.cost_usd:.4f}",
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
        st.divider()
        if rec.get("error"):
            st.error(f"Order #{rec['order_id']}: could not read the invoice. {rec['error']}")
        else:
            inv, result = rec["invoice"], rec["result"]
            st.markdown(f"**Order #{rec['order_id']} · invoice {inv.get('invoice_number') or '?'}** from "
                        f"{inv.get('supplier_name') or '?'}, dated {inv.get('invoice_date') or '?'}")
            st.table([{"Item": l["product_name"], "Matched to": l["catalog_match"], "Batch": l["batch_no"],
                       "Expiry": l["expiry"], "Qty": l["qty"]} for l in inv.get("lines", [])])
            if result.get("applied"):
                added = ", ".join(f"{r['name']} +{r['qty']}" for r in result["receive"])
                st.success(f"✅ Invoice matches the order. Stock updated automatically: {added}.")
            else:
                st.error("⚠️ The invoice does not match the order. Nothing has been changed yet.")
                for i in result["issues"]:
                    st.markdown(f"- **{i['type'].replace('_', ' ')}**: {i['detail']}")
                still_open = conn.execute("SELECT status FROM orders WHERE id = ?", (rec["order_id"],)).fetchone()
                is_open = still_open and still_open["status"] == "needs_review"
                plan = rec.get("plan")
                if rec.get("done"):
                    d = rec["done"]
                    st.success("✅ Approved plan carried out.")
                    if d["received"]:
                        st.markdown("**Added to stock:** " + ", ".join(f"{i['name']} +{i['qty']}" for i in d["received"]))
                    if d["held"]:
                        st.markdown("**Set aside:** " + ", ".join(f"{i['name']} × {i['qty']}" for i in d["held"]))
                    if d["reorders"]:
                        st.markdown("**Draft re-order(s) created:** " + ", ".join(f"#{o}" for o in d["reorders"])
                                    + " (approve them in the Orders tab)")
                    for m in d["messages"]:
                        st.text_area("Message to send the supplier", m, height=200, key="sent_msg")
                elif plan and is_open:
                    st.subheader("🤖 The agent's plan")
                    if plan.get("error"):
                        st.warning(plan["error"])
                    if plan.get("summary"):
                        st.info(plan["summary"])
                    approved, questions = [], []
                    for a in plan.get("actions", []):
                        if a["tool"] == "ask_pharmacist":
                            questions.append(a)
                            continue
                        label = f"{TOOL_LABELS.get(a['tool'], a['tool'])}: {describe(a)}"
                        if st.checkbox(label, value=True, key=f"pa{rec['order_id']}_{a['id']}"):
                            approved.append(a["id"])
                        if a["tool"] == "draft_supplier_message":
                            st.text_area("Draft message", a["input"]["message"], height=180, disabled=True,
                                         key=f"pm{rec['order_id']}_{a['id']}")
                    answers = {}
                    for q in questions:
                        answers[q["input"]["question"]] = st.text_input(f"❓ {q['input']['question']}",
                                                                        key=f"qa{rec['order_id']}_{q['id']}")
                    if plan.get("rejected"):
                        with st.expander(f"Proposals blocked by the safety rules ({len(plan['rejected'])})"):
                            for r in plan["rejected"]:
                                st.markdown(f"- {TOOL_LABELS.get(r['tool'], r['tool'])}: {r['why']}")
                    st.caption(f"Agent: {plan.get('turns', 0)} step(s) · ${plan.get('cost_usd', 0):.4f}")
                    c1, c2 = st.columns(2)
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
                if is_open and pharmacist and not rec.get("done"):
                    with st.expander("Other options"):
                        if st.button("Accept the whole delivery as invoiced", key=f"acc{rec['order_id']}"):
                            res2 = receive_delivery(conn, rec["order_id"], inv, pharmacist, True, accept_discrepancies=True)
                            st.session_state["receipt"] = {**rec, "result": res2}
                            st.rerun()
            st.caption(rec["meta"])
        if st.button("Clear", key="clear_receipt"):
            st.session_state.pop("receipt", None)
            st.rerun()

# ---------------- Stock ----------------
with tab_stock:
    st.subheader("Current stock")
    st.dataframe([dict(r) for r in db.stock_summary(conn)], use_container_width=True, hide_index=True)

# ---------------- Audit log ----------------
with tab_log:
    st.subheader("Everything the agent and pharmacists did")
    rows = conn.execute("SELECT at, actor, action, details FROM audit_log ORDER BY id DESC LIMIT 200").fetchall()
    st.dataframe([{**dict(r), "details": json.loads(r["details"]) if r["details"] else ""} for r in rows],
                 use_container_width=True, hide_index=True)
