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
from pharmacy.receive import check_delivery, receive_delivery  # noqa: E402
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
        upload = st.file_uploader("Photo or PDF of the invoice", type=["jpg", "jpeg", "png", "webp", "pdf"],
                                  disabled=not confirmed, key=f"up{order['id']}")
        if upload and st.button("Read invoice", type="primary", disabled=not pharmacist):
            catalog = [r["name"] for r in conn.execute("SELECT name FROM medicines ORDER BY name")]
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(upload.name).suffix) as f:
                f.write(upload.getbuffer())
            with st.spinner("Reading the invoice..."):
                res = read_invoice(f.name, catalog)
            Path(f.name).unlink(missing_ok=True)
            if res.error:
                st.error(res.error)
            else:
                st.session_state[f"inv{order['id']}"] = res.data
                st.caption(f"Read with {res.model} · {res.input_tokens + res.output_tokens} tokens · ${res.cost_usd:.4f}")

        inv = st.session_state.get(f"inv{order['id']}")
        if inv:
            st.markdown(f"**Invoice {inv.get('invoice_number') or '?'}** from {inv.get('supplier_name') or '?'}, "
                        f"dated {inv.get('invoice_date') or '?'}")
            st.table([{"Item": l["product_name"], "Matched to": l["catalog_match"], "Batch": l["batch_no"],
                       "Expiry": l["expiry"], "Qty": l["qty"]} for l in inv.get("lines", [])])
            check = check_delivery(conn, order["id"], inv)
            if check["status"] == "match":
                st.success("Invoice matches the order exactly.")
                if st.button("Add to stock", type="primary", key=f"add{order['id']}"):
                    receive_delivery(conn, order["id"], inv, pharmacist, confirmed)
                    st.session_state.pop(f"inv{order['id']}", None)
                    st.success("Stock updated.")
                    st.rerun()
            else:
                st.error("The invoice does not match the order:")
                for i in check["issues"]:
                    st.markdown(f"- **{i['type'].replace('_', ' ')}**: {i['detail']}")
                c1, c2 = st.columns(2)
                if c1.button("Flag for follow-up with supplier", key=f"fl{order['id']}"):
                    receive_delivery(conn, order["id"], inv, pharmacist, confirmed)
                    st.rerun()
                if c2.button("Accept anyway and add what was delivered", key=f"acc{order['id']}", disabled=not pharmacist):
                    receive_delivery(conn, order["id"], inv, pharmacist, confirmed, accept_discrepancies=True)
                    st.session_state.pop(f"inv{order['id']}", None)
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
