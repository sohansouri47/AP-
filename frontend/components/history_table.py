"""Clean, table-first Run History component for AP AI Employee.

Layout:
Run history                         [ Search ]
[ Status filter ] [ Date filter ]
Table: Run ID | Supplier | Invoice | Amount | Route | Status | Updated

Clicking a row opens the matching Decision page.
"""

from __future__ import annotations

import datetime
from typing import Any
import pandas as pd
import streamlit as st

from api_client import BackendAPIClient


def render_run_history(client: BackendAPIClient) -> str | None:
    """Render historical runs table and return selected thread_id if any."""
    # Top Bar: Title on left, Search on right
    h_col1, h_col2 = st.columns([2.2, 1.2], vertical_alignment="center")
    with h_col1:
        st.markdown('<div class="page-title">Run history</div>', unsafe_allow_html=True)
        st.markdown('<div class="page-description">Audit records of autonomous processing runs, decision routes, and human reviews.</div>', unsafe_allow_html=True)
    with h_col2:
        search_query = st.text_input(
            "Search runs",
            placeholder="Search supplier, invoice, run ID...",
            label_visibility="collapsed",
            key="hist_search_filter",
        )

    runs = client.list_invoices(limit=100)
    if not runs:
        st.markdown(
            """
            <div style="border: 1px dashed var(--border-color); border-radius: 8px; padding: 2.5rem; text-align: center; color: var(--text-muted);">
                <div style="font-size: 0.95rem; font-weight: 500;">No processing runs recorded yet</div>
                <div style="font-size: 0.82rem; margin-top: 0.25rem;">Processed invoices will appear here with audit timestamps and status routes.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return None

    df = pd.DataFrame(runs)

    # Filter Bar: [ Status filter ] [ Date filter ]
    f_col1, f_col2, f_col3 = st.columns([1.5, 1.5, 1.2])
    with f_col1:
        status_options = [
            "All",
            "POSTING_PACKAGE_READY",
            "READY_FOR_APPROVAL",
            "NEEDS_ATTENTION",
            "BLOCKED",
            "REJECTED",
        ]
        status_filter = st.selectbox(
            "Status filter",
            status_options,
            format_func=lambda x: "All statuses" if x == "All" else x.replace("_", " ").title(),
            key="hist_status_filter",
        )
    with f_col2:
        date_filter = st.selectbox(
            "Date filter",
            ["All time", "Today", "Last 7 days", "Last 30 days"],
            key="hist_date_filter",
        )
    with f_col3:
        st.markdown("<div style='height: 28px;'></div>", unsafe_allow_html=True)
        total_runs = len(df)
        st.caption(f"Showing **{total_runs}** total recorded runs")

    # Apply Filters
    filtered_df = df.copy()
    if status_filter != "All":
        filtered_df = filtered_df[filtered_df["lifecycle_status"] == status_filter]

    if search_query:
        q = search_query.lower()
        mask = (
            filtered_df["run_id"].astype(str).str.lower().str.contains(q)
            | filtered_df["invoice_number"].astype(str).str.lower().str.contains(q)
            | filtered_df["supplier_id"].astype(str).str.lower().str.contains(q)
        )
        filtered_df = filtered_df[mask]

    if filtered_df.empty:
        st.info("No processing runs match the selected search or status filters.")
        return None

    # Format Display Columns: Run ID | Supplier | Invoice | Amount | Route | Status | Updated
    formatted_rows = []
    for _, row in filtered_df.iterrows():
        raw_id = str(row.get("run_id", ""))
        short_id = raw_id[:16] + "..." if len(raw_id) > 16 else raw_id
        amt = row.get("total_amount")
        amt_str = f"${amt:,.2f}" if pd.notnull(amt) and isinstance(amt, (int, float)) else "—"

        ts = row.get("started_at")
        ts_str = "—"
        if ts:
            try:
                if isinstance(ts, (int, float)):
                    ts_str = datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
                else:
                    ts_str = str(ts)[:16]
            except Exception:
                ts_str = str(ts)

        st_clean = str(row.get("lifecycle_status", "UNKNOWN")).replace("_", " ").title()

        supp = row.get("supplier_id")
        supp_str = str(supp) if pd.notnull(supp) and str(supp).strip() not in ("nan", "None", "") else "—"

        inv = row.get("invoice_number")
        inv_str = str(inv) if pd.notnull(inv) and str(inv).strip() not in ("nan", "None", "") else "—"

        status_short_map = {
            "POSTING_PACKAGE_READY": "Posted",
            "READY_FOR_APPROVAL": "Awaiting Approval",
            "NEEDS_ATTENTION": "AP Review",
            "BLOCKED": "Blocked",
            "REJECTED": "Rejected",
            "START": "Initializing",
        }
        st_display = status_short_map.get(str(row.get("lifecycle_status", "")), st_clean)
        formatted_rows.append({
            "Run ID": raw_id,
            "Supplier": supp_str,
            "Invoice": inv_str,
            "Amount": amt_str,
            "Policy": str(row.get("workflow_version", "v1.0.0")),
            "Status": st_display,
            "Started": ts_str,
        })

    display_df = pd.DataFrame(formatted_rows)

    # Clickable Table via Streamlit dataframe selection
    st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)
    table_event = st.dataframe(
        display_df,
        hide_index=True,
        selection_mode="single-row",
        on_select="rerun",
        key="history_runs_table",
    )

    selected_thread_id = None
    if table_event and hasattr(table_event, "selection") and table_event.selection.rows:
        row_idx = table_event.selection.rows[0]
        if row_idx < len(formatted_rows):
            selected_thread_id = formatted_rows[row_idx]["Run ID"]

    # Action bar below table
    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    c_action1, c_action2 = st.columns([2, 1], vertical_alignment="center")
    with c_action1:
        if selected_thread_id:
            st.success(f"Selected run `{selected_thread_id}`. Click below to inspect.")
        else:
            st.caption("Click any row in the table to inspect its decision and audit report.")

    with c_action2:
        if selected_thread_id:
            if st.button("Inspect Decision ➔", type="primary", key="btn_inspect_history_run"):
                return selected_thread_id

    return selected_thread_id
