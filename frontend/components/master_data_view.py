"""Master Data and Seeded Context Component.

Surfaces enterprise vendor records, verified bank accounts, open purchase orders,
policy tolerances, and demo scenario reference to make explaining the AP system effortless.
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any
import pandas as pd
import streamlit as st

# Direct PostgreSQL connection with static fallback
try:
    from app.db.connection import get_db_cursor, is_db_reachable
except ImportError:
    get_db_cursor = None
    is_db_reachable = lambda: False


# Baseline fallback dataset (matches app/db/init_db.py)
BASELINE_SUPPLIERS = [
    {
        "supplier_id": "SUPP-001",
        "name": "Acme Industrial Supplies LLC",
        "tax_id": "US-XX-9876543",
        "payment_terms": "NET30",
        "currency": "USD",
        "bank_name": "JPMorgan Chase Bank",
        "account_last4": "4321",
        "routing_number": "021000021",
        "status": "ACTIVE",
    },
    {
        "supplier_id": "SUPP-002",
        "name": "Globex Corp",
        "tax_id": "US-YY-1234567",
        "payment_terms": "NET30",
        "currency": "USD",
        "bank_name": "Wells Fargo Bank NA",
        "account_last4": "8765",
        "routing_number": "121000358",
        "status": "ACTIVE",
    },
    {
        "supplier_id": "SUPP-003",
        "name": "Vandelay Industries",
        "tax_id": "US-ZZ-5566778",
        "payment_terms": "NET45",
        "currency": "USD",
        "bank_name": "Citibank NA",
        "account_last4": "1111",
        "routing_number": "026009593",
        "status": "ACTIVE",
    },
    {
        "supplier_id": "SUPP-004",
        "name": "Initech Software Systems",
        "tax_id": "US-AA-1122334",
        "payment_terms": "NET30",
        "currency": "USD",
        "bank_name": "Silicon Valley Bank",
        "account_last4": "9900",
        "routing_number": "121140399",
        "status": "ACTIVE",
    },
]

BASELINE_POS = [
    {
        "po_number": "PO-9001",
        "supplier_id": "SUPP-001",
        "supplier_name": "Acme Industrial Supplies LLC",
        "status": "APPROVED",
        "total_amount": 5000.00,
        "remaining_amount": 5000.00,
        "line_number": 1,
        "sku": "SKU-IND-100",
        "description": "Standard service unit",
        "quantity": 5.0,
        "unit_price": 1000.00,
        "line_total": 5000.00,
    },
    {
        "po_number": "PO-2001",
        "supplier_id": "SUPP-002",
        "supplier_name": "Globex Corp",
        "status": "APPROVED",
        "total_amount": 3000.00,
        "remaining_amount": 3000.00,
        "line_number": 1,
        "sku": "SKU-CLD-201",
        "description": "Cloud hosting package",
        "quantity": 2.0,
        "unit_price": 1200.00,
        "line_total": 2400.00,
    },
    {
        "po_number": "PO-2001",
        "supplier_id": "SUPP-002",
        "supplier_name": "Globex Corp",
        "status": "APPROVED",
        "total_amount": 3000.00,
        "remaining_amount": 3000.00,
        "line_number": 2,
        "sku": "SKU-SUP-202",
        "description": "Support add-on",
        "quantity": 1.0,
        "unit_price": 600.00,
        "line_total": 600.00,
    },
    {
        "po_number": "PO-2002",
        "supplier_id": "SUPP-002",
        "supplier_name": "Globex Corp",
        "status": "APPROVED",
        "total_amount": 10000.00,
        "remaining_amount": 10000.00,
        "line_number": 1,
        "sku": "SKU-ENT-301",
        "description": "Enterprise consulting retainer",
        "quantity": 1.0,
        "unit_price": 10000.00,
        "line_total": 10000.00,
    },
    {
        "po_number": "PO-8888",
        "supplier_id": "SUPP-003",
        "supplier_name": "Vandelay Industries",
        "status": "APPROVED",
        "total_amount": 2500.00,
        "remaining_amount": 2000.00,
        "line_number": 1,
        "sku": "SKU-LTX-001",
        "description": "Latex sample parts",
        "quantity": 5.0,
        "unit_price": 100.00,
        "line_total": 500.00,
    },
]


def load_suppliers() -> list[dict[str, Any]]:
    """Fetch live suppliers with verified bank records from DB or fallback."""
    if is_db_reachable() and get_db_cursor:
        try:
            with get_db_cursor() as cur:
                cur.execute(
                    """
                    SELECT s.supplier_id, s.name, s.tax_id, s.payment_terms, s.currency, s.status,
                           b.bank_name, b.account_last4, b.routing_number
                    FROM suppliers s
                    LEFT JOIN supplier_bank_accounts b ON s.supplier_id = b.supplier_id
                    ORDER BY s.supplier_id;
                    """
                )
                rows = cur.fetchall()
                if rows:
                    return [dict(r) for r in rows]
        except Exception:
            pass
    return BASELINE_SUPPLIERS


def load_purchase_orders() -> list[dict[str, Any]]:
    """Fetch live POs with lines from DB or fallback."""
    if is_db_reachable() and get_db_cursor:
        try:
            with get_db_cursor() as cur:
                cur.execute(
                    """
                    SELECT po.po_number, po.supplier_id, s.name as supplier_name, po.status,
                           po.total_amount, po.remaining_amount,
                           pol.line_number, pol.sku, pol.description, pol.quantity, pol.unit_price, pol.line_total
                    FROM purchase_orders po
                    JOIN suppliers s ON po.supplier_id = s.supplier_id
                    LEFT JOIN purchase_order_lines pol ON po.po_number = pol.po_number
                    ORDER BY po.po_number, pol.line_number;
                    """
                )
                rows = cur.fetchall()
                if rows:
                    cleaned = []
                    for r in rows:
                        d = dict(r)
                        for k, v in d.items():
                            if isinstance(v, Decimal):
                                d[k] = float(v)
                        cleaned.append(d)
                    return cleaned
        except Exception:
            pass
    return BASELINE_POS


def render_master_data_page():
    """Render comprehensive Vendor & Master Data explanation view."""
    st.markdown('<div class="page-title">Vendor & Master Data</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-description">Enterprise master records, verified vendor banking accounts, active purchase orders, and deterministic policy thresholds.</div>',
        unsafe_allow_html=True,
    )

    # -----------------------------------------------------------------
    # Top KPI Metrics Strip
    # -----------------------------------------------------------------
    with st.container(border=True):
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Verified Suppliers", "4 Active", help="Vendor master directory with verified tax IDs and bank accounts")
        m2.metric("Open PO Commitments", "$20,500.00", help="Active approved purchase orders available for 3-way matching")
        m3.metric("Financial Controls", "13 Checks", help="Deterministic rule registry applied to every invoice")
        m4.metric("Policy Version", "v1.0.0", help="Active financial policy version with strict audit trail")

    st.markdown("<div style='height: 12px;'></div>", unsafe_allow_html=True)

    # -----------------------------------------------------------------
    # Master Data Tabs
    # -----------------------------------------------------------------
    tab_vendors, tab_pos, tab_policy, tab_scenarios = st.tabs([
        "Suppliers & Bank Records",
        "Purchase Orders & Schedules",
        "Financial Policy Rules",
        "Demo Scenarios Cheatsheet",
    ])

    # =================================================================
    # TAB 1: Suppliers & Bank Records
    # =================================================================
    with tab_vendors:
        st.markdown(
            """
            <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">
                Every invoice must resolve to an active supplier record and pass strict remittance validation against verified corporate banking details.
            </div>
            """,
            unsafe_allow_html=True,
        )

        suppliers = load_suppliers()
        table_rows = []
        for s in suppliers:
            acct = s.get("account_last4")
            acct_disp = f"••••{acct}" if acct and str(acct).strip() not in ("None", "nan") else "Not on file"
            table_rows.append({
                "Supplier ID": s.get("supplier_id"),
                "Legal Entity Name": s.get("name"),
                "Tax ID (EIN)": s.get("tax_id"),
                "Payment Terms": s.get("payment_terms", "NET30"),
                "Currency": s.get("currency", "USD"),
                "Bank Institution": s.get("bank_name") or "—",
                "Remittance Account": acct_disp,
                "Status": s.get("status", "ACTIVE"),
            })

        df_supp = pd.DataFrame(table_rows)
        st.dataframe(df_supp, hide_index=True, width="stretch")

        st.markdown(
            """
            <div style="font-size: 0.78rem; color: var(--text-muted); background: var(--bg-card-subtle); padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border-color); margin-top: 8px;">
                <strong>Compliance Note:</strong> Raw bank account numbers are encrypted at rest with AES-256. The AI Employee operates strictly against deterministic references and masked <code>account_last4</code> to enforce separation of duties and prevent remittance tampering.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # =================================================================
    # TAB 2: Purchase Orders & Schedules
    # =================================================================
    with tab_pos:
        st.markdown(
            """
            <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">
                Open purchase orders and schedule lines used by <code>CHK_PO_IDENT</code>, <code>CHK_PO_HEADER</code>, and <code>CHK_PO_LINES</code> for autonomous 3-way matching.
            </div>
            """,
            unsafe_allow_html=True,
        )

        pos = load_purchase_orders()
        po_summary = {}
        for r in pos:
            pnum = r.get("po_number")
            if pnum not in po_summary:
                po_summary[pnum] = {
                    "po_number": pnum,
                    "supplier_id": r.get("supplier_id"),
                    "supplier_name": r.get("supplier_name"),
                    "total_amount": r.get("total_amount"),
                    "remaining_amount": r.get("remaining_amount"),
                    "status": r.get("status"),
                    "lines": [],
                }
            if r.get("line_number"):
                po_summary[pnum]["lines"].append({
                    "line": r.get("line_number"),
                    "sku": r.get("sku"),
                    "description": r.get("description"),
                    "quantity": r.get("quantity"),
                    "unit_price": r.get("unit_price"),
                    "line_total": r.get("line_total"),
                })

        for pnum, pdata in po_summary.items():
            tot = pdata.get("total_amount", 0.0)
            rem = pdata.get("remaining_amount", 0.0)
            supp = pdata.get("supplier_name", "")
            supp_id = pdata.get("supplier_id", "")
            with st.expander(f"**{pnum}** — {supp} ({supp_id}) | Total: ${tot:,.2f} | Remaining: ${rem:,.2f}", expanded=True):
                lines_df = pd.DataFrame(pdata["lines"])
                if not lines_df.empty:
                    lines_df = lines_df.rename(columns={
                        "line": "Line #",
                        "sku": "SKU",
                        "description": "Item Description",
                        "quantity": "Quantity",
                        "unit_price": "Unit Price ($)",
                        "line_total": "Line Total ($)",
                    })
                    st.dataframe(lines_df, hide_index=True, width="stretch")

        st.markdown(
            """
            <div style="font-size: 0.8rem; background: var(--bg-card-subtle); border-left: 3px solid #2563eb; padding: 10px 14px; border-radius: 4px; margin-top: 10px;">
                <strong>Demo Insight:</strong> Globex Corp (<code>SUPP-002</code>) has <em>two</em> active purchase orders (<code>PO-2001</code> for $3,000.00 and <code>PO-2002</code> for $10,000.00). When an invoice arrives without an explicit PO number, the AI Employee flags an <strong>Ambiguous PO Exception</strong> and pauses at the AP Review gate so an operator can designate the correct order.
            </div>
            """,
            unsafe_allow_html=True,
        )

    # =================================================================
    # TAB 3: Financial Policy Rules & Tolerances
    # =================================================================
    with tab_policy:
        st.markdown(
            """
            <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">
                Active policy parameters governing deterministic controls and human-in-the-loop approval routing (Policy Version <code>v1.0.0</code>).
            </div>
            """,
            unsafe_allow_html=True,
        )

        p_col1, p_col2 = st.columns(2, gap="large")

        with p_col1:
            with st.container(border=True):
                st.markdown('<div class="ap-card-title">Matching Tolerances</div>', unsafe_allow_html=True)
                st.markdown(
                    """
                    <table style="width: 100%; font-size: 0.82rem; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid var(--border-color);">
                            <td style="padding: 8px 0; color: var(--text-secondary);">Price Variance Threshold</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">± 1.0%</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-color);">
                            <td style="padding: 8px 0; color: var(--text-secondary);">Quantity Variance Threshold</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">± 5.0%</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-color);">
                            <td style="padding: 8px 0; color: var(--text-secondary);">Arithmetic Rounding Balance</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">± $0.05</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: var(--text-secondary);">Tax Rate Verification</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">Subtotal + Tax == Total</td>
                        </tr>
                    </table>
                    """,
                    unsafe_allow_html=True,
                )

        with p_col2:
            with st.container(border=True):
                st.markdown('<div class="ap-card-title">Governance & Approval Limits</div>', unsafe_allow_html=True)
                st.markdown(
                    """
                    <table style="width: 100%; font-size: 0.82rem; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid var(--border-color);">
                            <td style="padding: 8px 0; color: var(--text-secondary);">Non-PO Expense Ceiling</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">$2,500.00</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-color);">
                            <td style="padding: 8px 0; color: var(--text-secondary);">Senior Finance Approval Gate</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">> $5,000.00</td>
                        </tr>
                        <tr style="border-bottom: 1px solid var(--border-color);">
                            <td style="padding: 8px 0; color: var(--text-secondary);">Duplicate Check Strategy</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">SHA-256 + (Tax ID, Inv #)</td>
                        </tr>
                        <tr>
                            <td style="padding: 8px 0; color: var(--text-secondary);">Checkpointer Persistence</td>
                            <td style="padding: 8px 0; font-weight: 600; text-align: right;">PostgreSQL (PostgresSaver)</td>
                        </tr>
                    </table>
                    """,
                    unsafe_allow_html=True,
                )

    # =================================================================
    # TAB 4: Demo Scenarios Cheatsheet
    # =================================================================
    with tab_scenarios:
        st.markdown(
            """
            <div style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 0.75rem;">
                Reference guide explaining how each built-in demo scenario exercises different paths in the LangGraph state machine.
            </div>
            """,
            unsafe_allow_html=True,
        )

        scenarios = [
            {
                "title": "Ambiguous PO Scenario",
                "badge": "AP Review Required",
                "badge_class": "status-pill-amber",
                "supplier": "Globex Corp (SUPP-002)",
                "amount": "$2,592.00",
                "expected": "Interrupt at AP Review gate",
                "explanation": "The invoice contains Cloud router services but omits the PO number. Globex has two open approved POs (PO-2001 and PO-2002). The agent identifies the conflict, halts via LangGraph interrupt, and asks the AP Operator to designate PO-2001 or PO-2002.",
            },
            {
                "title": "Happy Path Clean Match",
                "badge": "Finance Approval Ready",
                "badge_class": "status-pill-blue",
                "supplier": "Acme Industrial Supplies LLC (SUPP-001)",
                "amount": "$1,080.00",
                "expected": "All 13 checks pass -> Finance Approver sign-off",
                "explanation": "Invoice INV-2026-001 matches approved PO-9001 ($5,000 balance). Arithmetic matches ($1,000 subtotal + $80 tax = $1,080). Tolerances are 0.0%. After CFO sign-off, an ERP-ready posting package is generated.",
            },
            {
                "title": "Tax Mismatch Exception",
                "badge": "Auto-Blocked / Exception",
                "badge_class": "status-pill-red",
                "supplier": "Acme Industrial Supplies LLC (SUPP-001)",
                "amount": "$1,200.00",
                "expected": "Control CHK_ARITHMETIC fails immediately",
                "explanation": "Header total is $1,200.00, but line total $1,000.00 + tax $80.00 = $1,080.00. The agent detects an arithmetic variance > $0.05, immediately halts without posting, and records an unresolvable exception.",
            },
            {
                "title": "Duplicate Invoice Detection",
                "badge": "Duplicate Risk Detected",
                "badge_class": "status-pill-red",
                "supplier": "Vandelay Industries (SUPP-003)",
                "amount": "$540.00",
                "expected": "Control CHK_BIZ_DUP blocks execution",
                "explanation": "Invoice INV-DUP-999 is checked against historical records in PostgreSQL. The master ledger already contains a posted transaction for Vandelay INV-DUP-999 from 2026-09-02. The workflow halts to protect against double payment.",
            },
        ]

        for sc in scenarios:
            with st.container(border=True):
                h1, h2 = st.columns([3, 1])
                with h1:
                    st.markdown(f"**{sc['title']}** — `{sc['supplier']}`")
                with h2:
                    st.markdown(
                        f"""<div style="text-align: right;"><span class="status-pill {sc['badge_class']}">{sc['badge']}</span></div>""",
                        unsafe_allow_html=True,
                    )
                st.markdown(f"<div style='font-size: 0.82rem; color: var(--text-secondary); line-height: 1.45; margin-top: 4px;'>{sc['explanation']}</div>", unsafe_allow_html=True)
                st.caption(f"Invoice Amount: **{sc['amount']}** | Expected Outcome: **{sc['expected']}**")
