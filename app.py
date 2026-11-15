"""Pharmacist screen. Run with:  streamlit run app.py"""
import html
import os
import tempfile
import time
from datetime import date
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

from pharmacy import auth, db, orders  # noqa: E402
from pharmacy.agent import execute_plan, plan_followup  # noqa: E402
from pharmacy.alerts import find_alerts  # noqa: E402
from pharmacy.invoice import read_invoice  # noqa: E402
from pharmacy.receive import receive_delivery  # noqa: E402
from pharmacy.safe import plain  # noqa: E402
from pharmacy.seed import seed  # noqa: E402

DEMO_MODE = os.environ.get("PHARMA_DEMO", "") == "1"
IDLE_MINUTES = 30

TOOL_LABELS = {"receive_items": "Add to stock", "hold_items": "Set aside (not added)",
               "draft_reorder": "Draft a re-order", "draft_supplier_message": "Message to supplier",
               "ask_pharmacist": "Question"}
STATUS = {"draft": "Draft", "pending_delivery": "Awaiting delivery", "needs_review": "Needs review",
          "received": "Received", "closed": "Closed"}

# Static styling only. Any text from the database, invoices or the AI is escaped before it is placed in HTML.
CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  html, body, .stApp, p, li, label, input, textarea, h1, h2, h3, h4, table {
    font-family: 'Inter', -apple-system, 'Segoe UI', Arial, sans-serif; }
  .block-container { padding-top: 3.2rem; padding-bottom: 3rem; max-width: 1240px; }
  footer { visibility: hidden; }
  h1, h2, h3, h4 { letter-spacing: -0.01em; }
  .rs-brand { font-size: 1.05rem; font-weight: 700; letter-spacing: .02em; color: #111827; }
  .rs-brand span { color: #6B7280; font-weight: 500; }
  .rs-title { font-size: 1.5rem; font-weight: 700; color: #111827; margin: 0; }
  .rs-sub { color: #6B7280; font-size: .9rem; margin: 2px 0 14px 0; }
  .rs-tag { display: inline-block; font-size: .72rem; font-weight: 600; letter-spacing: .04em; text-transform: uppercase;
            color: #374151; border: 1px solid #D1D5DB; border-radius: 4px; padding: 1px 7px; margin-left: 6px;
            vertical-align: 2px; background: #FFFFFF; }
  .rs-tag.strong { color: #FFFFFF; background: #1F2937; border-color: #1F2937; }
  .rs-step { font-size: .72rem; font-weight: 700; letter-spacing: .08em; color: #6B7280; margin-bottom: 2px; }
  .rs-notice { border: 1px solid #E5E7EB; border-left: 4px solid #9CA3AF; border-radius: 6px; padding: 12px 16px;
               background: #FFFFFF; margin: 8px 0; color: #111827; }
  .rs-notice.dark { border-left-color: #111827; }
  .rs-notice b { display: block; margin-bottom: 2px; }
  .rs-notice ul { margin: 6px 0 0 18px; padding: 0; }
  div[data-testid="stMetric"] { background: #FFFFFF; border: 1px solid #E5E7EB; border-radius: 8px; padding: 14px 18px; }
  div[data-testid="stMetricLabel"] p { font-size: .8rem; color: #6B7280; text-transform: uppercase; letter-spacing: .04em; }
  button[data-baseweb="tab"] p { font-size: .95rem; font-weight: 600; }
  div[data-testid="stVerticalBlockBorderWrapper"] { background: #FFFFFF; border-radius: 8px; }
  section[data-testid="stSidebar"] { border-right: 1px solid #E5E7EB; }
</style>
"""


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def tag(label: str, strong=False) -> str:
    return f'<span class="rs-tag{" strong" if strong else ""}">{esc(label)}</span>'


def notice(title: str, lines=(), dark=False):
    """Neutral message box. Everything inside is escaped."""
    items = "".join(f"<li>{esc(l)}</li>" for l in lines)
    st.markdown(f'<div class="rs-notice{" dark" if dark else ""}"><b>{esc(title)}</b>'
                + (f"<ul>{items}</ul>" if items else "") + "</div>", unsafe_allow_html=True)


def step(n, title):
    st.markdown(f'<div class="rs-step">STEP {n}</div>', unsafe_allow_html=True)
    st.markdown(f"**{title}**")


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


st.set_page_config(page_title="Restock Agent", layout="wide")
st.markdown(CSS, unsafe_allow_html=True)
conn = db.connect()
auth.ensure_schema(conn)
if conn.execute("SELECT COUNT(*) FROM medicines").fetchone()[0] == 0:
    seed(conn)

# ---------------- Sign-in ----------------
user = st.session_state.get("user")
if user and time.time() - st.session_state.get("last_seen", 0) > IDLE_MINUTES * 60:
    db.log(conn, user["username"], "signed out (idle timeout)")
    conn.commit()
    st.session_state.clear()
    st.session_state["flash_login"] = f"You were signed out after {IDLE_MINUTES} minutes without activity."
    user = None
if user and not auth.session_valid(conn, user):
    # Account deactivated, or password changed elsewhere: end this session now.
    db.log(conn, user["username"], "session ended (account changed)")
    conn.commit()
    st.session_state.clear()
    st.session_state["flash_login"] = "Your session has ended. Please sign in again."
    user = None

if not user:
    _, mid, _ = st.columns([1, 1.1, 1])
    with mid:
        st.write("")
        st.markdown('<div class="rs-brand">RESTOCK AGENT <span>· Pharmacy operations</span></div>', unsafe_allow_html=True)
        if "flash_login" in st.session_state:
            notice(st.session_state.pop("flash_login"))
        if not auth.has_users(conn):
            st.markdown("### Create the administrator account")
            st.caption("No accounts exist yet. This first account can add other pharmacists.")
            with st.form("first_user"):
                full = st.text_input("Full name")
                uname = st.text_input("Username")
                pw = st.text_input("Password", type="password", help=f"At least {auth.MIN_PASSWORD} characters.")
                pw2 = st.text_input("Confirm password", type="password")
                if st.form_submit_button("Create account", type="primary", use_container_width=True):
                    try:
                        if pw != pw2:
                            raise auth.AuthError("The two passwords don't match.")
                        auth.create_user(conn, uname, full, pw, is_admin=True)
                        st.session_state["flash_login"] = "Account created. Sign in to continue."
                        st.rerun()
                    except auth.AuthError as e:
                        notice(str(e), dark=True)
        else:
            st.markdown("### Sign in")
            with st.form("login"):
                uname = st.text_input("Username")
                pw = st.text_input("Password", type="password")
                if st.form_submit_button("Sign in", type="primary", use_container_width=True):
                    try:
                        st.session_state["user"] = auth.authenticate(conn, uname, pw)
                        st.session_state["last_seen"] = time.time()
                        st.rerun()
                    except auth.AuthError as e:
                        notice(str(e), dark=True)
        st.caption("Access is limited to pharmacy staff. All activity is recorded.")
    st.stop()

st.session_state["last_seen"] = time.time()
# The approving pharmacist is the signed-in account, not a typed name.
pharmacist = f"{user['full_name']} ({user['username']})"

# ---------------- Sidebar ----------------
with st.sidebar:
    st.markdown('<div class="rs-brand">RESTOCK AGENT</div>', unsafe_allow_html=True)
    st.caption("Demo Pharmacy · fictional data")
    st.markdown(f"Signed in as **{plain(user['full_name'], 60)}**  \n`{plain(user['username'], 40)}`"
                + ("  · administrator" if user["is_admin"] else ""))
    if st.button("Sign out", use_container_width=True):
        db.log(conn, user["username"], "signed out")
        conn.commit()
        st.session_state.clear()
        st.rerun()
    st.divider()
    with st.expander("Change password"):
        with st.form("change_pw", clear_on_submit=True):
            cur = st.text_input("Current password", type="password")
            new = st.text_input("New password", type="password")
            new2 = st.text_input("Confirm new password", type="password")
            if st.form_submit_button("Update password"):
                try:
                    if new != new2:
                        raise auth.AuthError("The two new passwords don't match.")
                    user["session_version"] = auth.change_password(conn, user["id"], cur, new)
                    notice("Password updated. Any other open sessions were signed out.")
                except auth.AuthError as e:
                    notice(str(e), dark=True)
    if user["is_admin"]:
        with st.expander("Manage accounts"):
            for u in auth.list_users(conn):
                c1, c2 = st.columns([3, 2], vertical_alignment="center")
                c1.markdown(f"**{plain(u['full_name'], 40)}**  \n`{plain(u['username'], 32)}`"
                            + (" · admin" if u["is_admin"] else "") + ("" if u["active"] else " · inactive"))
                if u["id"] != user["id"]:
                    if c2.button("Deactivate" if u["active"] else "Activate", key=f"act{u['id']}"):
                        try:
                            auth.set_active(conn, u["id"], not u["active"], user["username"],
                                            by_admin=auth.is_admin(conn, user["id"]))
                            st.rerun()
                        except auth.AuthError as e:
                            notice(str(e), dark=True)
            st.markdown("**Add an account**")
            with st.form("add_user", clear_on_submit=True):
                full = st.text_input("Full name")
                uname = st.text_input("Username")
                pw = st.text_input("Temporary password", type="password")
                admin = st.checkbox("Administrator")
                if st.form_submit_button("Add account"):
                    try:
                        auth.create_user(conn, uname, full, pw, is_admin=admin, actor=user["username"],
                                         by_admin=auth.is_admin(conn, user["id"]))  # re-checked in the database
                        notice(f"Account '{uname}' created.")
                    except auth.AuthError as e:
                        notice(str(e), dark=True)
    st.divider()
    st.markdown("**How it works**")
    st.caption("1. The agent flags low or expiring stock.  \n2. You approve every order.  \n"
               "3. Upload the invoice: an exact match updates stock automatically.  \n"
               "4. If anything is wrong, the agent proposes a fix for you to approve.")
    if DEMO_MODE and user["is_admin"]:
        st.divider()
        st.markdown("**Demo controls**")
        # Wipes stock, orders and the audit log (accounts are kept), so it needs demo mode, an admin and a second click.
        sure = st.checkbox("I want to erase all stock and order data", key="reset_sure")
        if st.button("Reset demo data", disabled=not sure):
            seed(conn)
            db.log(conn, user["username"], "reset demo data")
            conn.commit()
            st.session_state.pop("reset_sure", None)
            st.rerun()

# ---------------- Header + KPIs ----------------
st.markdown('<p class="rs-title">Restock Agent</p>'
            f'<p class="rs-sub">Stock alerts, supplier orders and invoice checks · {date.today().strftime("%A %d %B %Y")}</p>',
            unsafe_allow_html=True)
alerts = find_alerts(conn)
counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, COUNT(*) n FROM orders GROUP BY status")}
k1, k2, k3, k4 = st.columns(4)
k1.metric("Need attention", sum(not a["already_on_order"] for a in alerts))
k2.metric("Orders to approve", counts.get("draft", 0))
k3.metric("Awaiting delivery", counts.get("pending_delivery", 0))
k4.metric("Deliveries to review", counts.get("needs_review", 0))
st.write("")

tab_alerts, tab_orders, tab_receive, tab_stock, tab_log = st.tabs(
    ["Alerts", "Orders", "Receive delivery", "Stock", "Audit log"])

# ---------------- Alerts ----------------
with tab_alerts:
    st.subheader("Medicines that need attention")
    if not alerts:
        notice("Nothing is low or close to expiry.")
    picks = []
    for a in alerts:
        with st.container(border=True):
            c1, c2, c3 = st.columns([5, 2, 1.3], vertical_alignment="center")
            tags = ""
            if any(r.startswith("low stock") for r in a["reasons"]):
                tags += tag("Low stock", strong=True)
            if any("expire" in r for r in a["reasons"]):
                tags += tag("Expiring soon")
            c1.markdown(f"<b>{esc(a['name'])}</b>{tags}", unsafe_allow_html=True)
            c1.caption(f"{'; '.join(a['reasons']).capitalize()} · Supplier: {a['supplier']}")
            if a["already_on_order"]:
                c2.markdown(tag("On an open order"), unsafe_allow_html=True)
                continue
            qty = c2.number_input("Order qty", min_value=0, max_value=orders.MAX_QTY,
                                  value=min(int(a["suggested_qty"]), orders.MAX_QTY), key=f"q{a['medicine_id']}",
                                  label_visibility="collapsed")
            if c3.checkbox("Order", key=f"c{a['medicine_id']}"):
                picks.append((a["medicine_id"], qty))

    with st.expander("Order something else manually"):
        meds = conn.execute("SELECT id, name FROM medicines ORDER BY name").fetchall()
        names = {m["name"]: m["id"] for m in meds}
        manual = st.multiselect("Medicines", list(names))
        for n in manual:
            picks.append((names[n], st.number_input(f"Qty: {n}", min_value=1, max_value=orders.MAX_QTY, value=10,
                                                    key=f"m{names[n]}")))

    if st.button(f"Draft order for {len(picks)} item(s)" if picks else "Draft order", type="primary", disabled=not picks):
        ids = orders.draft_orders(conn, picks, reason="alert" if alerts else "manual request")
        for k in [k for k in st.session_state if str(k).startswith(("c", "m"))]:
            del st.session_state[k]
        st.session_state["flash"] = f"Drafted order(s) {', '.join('#' + str(i) for i in ids)}. Review them in the Orders tab."
        st.rerun()
    if "flash" in st.session_state:
        notice(st.session_state.pop("flash"))

# ---------------- Orders ----------------
with tab_orders:
    st.subheader("Supplier orders")
    all_orders = conn.execute("SELECT o.id, o.status FROM orders o WHERE o.status != 'cancelled' ORDER BY o.id DESC").fetchall()
    if not all_orders:
        notice("No orders yet. Draft one from the Alerts tab.")
    for o in all_orders:
        order, lines = db.order_with_lines(conn, o["id"])
        status = STATUS.get(order["status"], order["status"])
        with st.expander(f"Order #{order['id']}  —  {order['supplier']}  —  {status}", expanded=order["status"] == "draft"):
            if order["status"] == "draft":
                st.caption("Review the quantities, then approve to place the order.")
                for l in lines:
                    new = st.number_input(l["name"], min_value=0, max_value=orders.MAX_QTY, value=int(l["qty"]),
                                          key=f"ol{order['id']}_{l['medicine_id']}")
                    if new != l["qty"]:
                        orders.update_line(conn, order["id"], l["medicine_id"], int(new), pharmacist)
                        st.rerun()
                st.text_area("Message to supplier (preview)", order["message"], height=200, disabled=True,
                             key=f"msg{order['id']}")
                c1, c2, _ = st.columns([2, 1, 3])
                # THE LOCK: only a signed-in pharmacist can approve, and approve_order() re-checks in code.
                if c1.button("Approve and place order", key=f"ap{order['id']}", type="primary"):
                    try:
                        orders.approve_order(conn, order["id"], pharmacist)
                        st.rerun()
                    except Exception as e:
                        notice(str(e), dark=True)
                if c2.button("Cancel order", key=f"cx{order['id']}"):
                    orders.cancel_order(conn, order["id"], pharmacist)
                    st.rerun()
            else:
                st.caption(f"Approved by {order['approved_by']} on {(order['approved_at'] or '?').replace('T', ' at ')}")
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
        notice("No orders are waiting for delivery. Approve an order first.")
    else:
        with st.container(border=True):
            step(1, "Which order arrived?")
            choice = st.selectbox("Order", waiting, label_visibility="collapsed",
                                  format_func=lambda r: f"#{r['id']} — {r['supplier']} — {STATUS[r['status']]}")
            order, lines = db.order_with_lines(conn, choice["id"])
            st.dataframe([{"Medicine": l["name"], "Ordered": l["qty"]} for l in lines], hide_index=True, width="stretch")
        with st.container(border=True):
            step(2, "Check the boxes")
            confirmed = st.checkbox("I checked the boxes: the batch matches this order", key=f"bc{order['id']}")
        with st.container(border=True):
            step(3, "Upload the invoice")
            st.caption("The agent reads it, checks every line against the order, and updates stock if it matches exactly.")
            upload = st.file_uploader("Invoice photo or PDF", type=["jpg", "jpeg", "png", "webp", "pdf"],
                                      disabled=not confirmed, key=f"up{order['id']}", label_visibility="collapsed")
            if not confirmed:
                st.caption("Tick step 2 to unlock the upload.")

        # A new upload is processed once: read -> check -> stock updated on an exact match, else flagged.
        file_key = f"{order['id']}:{upload.file_id}" if upload is not None else None
        if upload is not None and confirmed and st.session_state.get("processed") != file_key:
            st.session_state["processed"] = file_key
            catalog = [r["name"] for r in conn.execute("SELECT name FROM medicines ORDER BY name")]
            # Never trust the uploaded file name: keep only a known extension, write to a fresh temp file.
            ext = Path(upload.name).suffix.lower()
            ext = ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".pdf") else ".bin"
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as f:
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
                    with st.spinner("The agent is working out what to do next..."):
                        rec["plan"] = plan_followup(conn, order["id"], res.data, result["issues"]).to_dict()
                st.session_state["receipt"] = rec
            st.rerun()

    # Result of the last upload (shown even after the order leaves the waiting list).
    rec = st.session_state.get("receipt")
    if rec:
        st.write("")
        with st.container(border=True):
            if rec.get("error"):
                notice(f"Order #{rec['order_id']}: the invoice could not be read.", [rec["error"]], dark=True)
                if st.button("Try again", type="primary", key="retry_read"):
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
                    notice("Invoice matches the order. Stock updated automatically.",
                           [f"{r['name']}: +{r['qty']} (batch {r['batch_no']})" for r in result["receive"]])
                else:
                    notice("The invoice does not match the order. Nothing has been changed yet.",
                           [f"{i['type'].replace('_', ' ').capitalize()}: {i['detail']}" for i in result["issues"]], dark=True)
                    still_open = conn.execute("SELECT status FROM orders WHERE id = ?", (rec["order_id"],)).fetchone()
                    is_open = still_open and still_open["status"] == "needs_review"
                    plan = rec.get("plan")
                    if rec.get("done"):
                        d = rec["done"]
                        lines_done = [f"Added to stock: {i['name']} +{i['qty']}" for i in d["received"]]
                        lines_done += [f"Set aside: {i['name']} × {i['qty']}" for i in d["held"]]
                        lines_done += [f"Draft re-order #{o} created (approve it in Orders)" for o in d["reorders"]]
                        notice("Approved plan carried out.", lines_done)
                        for m in d["messages"]:
                            st.text_area("Message to send the supplier", m, height=200, key="sent_msg")
                    elif plan and is_open:
                        st.divider()
                        st.markdown("#### Proposed follow-up")
                        st.caption("Prepared by the agent. Untick anything you don't want, then approve.")
                        if plan.get("error"):
                            notice(plan["error"], dark=True)
                        if plan.get("summary"):
                            notice(plan["summary"])
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
                            answers[q["input"]["question"]] = st.text_input(f"Question: {plain(q['input']['question'])}",
                                                                            key=f"qa{rec['order_id']}_{q['id']}")
                        if plan.get("rejected"):
                            with st.expander(f"Proposals blocked by the safety rules ({len(plan['rejected'])})"):
                                for r in plan["rejected"]:
                                    st.markdown(f"- {TOOL_LABELS.get(r['tool'], r['tool'])}: {plain(r['why'])}")
                        c1, c2, _ = st.columns([2, 2, 2])
                        if c1.button("Approve selected actions", type="primary", disabled=not approved,
                                     key=f"ok{rec['order_id']}"):
                            try:
                                done = execute_plan(conn, rec["order_id"], plan, set(approved), pharmacist, inv,
                                                    result["issues"])
                                st.session_state["receipt"] = {**rec, "done": done}
                            except (ValueError, PermissionError) as e:
                                st.session_state["receipt"] = {**rec, "exec_error": str(e)}
                            st.rerun()
                        if questions and c2.button("Re-plan with my answers", key=f"rp{rec['order_id']}",
                                                   disabled=not any(answers.values())):
                            with st.spinner("Re-planning..."):
                                new = plan_followup(conn, rec["order_id"], inv, result["issues"],
                                                    answers={k: v for k, v in answers.items() if v}).to_dict()
                            st.session_state["receipt"] = {**rec, "plan": new}
                            st.rerun()
                        if rec.get("exec_error"):
                            notice(rec["exec_error"], dark=True)
                        st.caption(f"Agent: {plan.get('turns', 0)} step(s) · ${plan.get('cost_usd', 0):.4f}")
                    if is_open and not rec.get("done"):
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
    st.caption("Everything the agent and staff did, newest first.")
    rows = conn.execute("SELECT at, actor, action, details FROM audit_log ORDER BY id DESC LIMIT 300").fetchall()
    st.dataframe([{"When": r["at"].replace("T", " "), "Who": r["actor"], "What": r["action"], "Details": r["details"] or ""}
                  for r in rows], hide_index=True, width="stretch",
                 column_config={"Details": st.column_config.TextColumn(width="large")})
