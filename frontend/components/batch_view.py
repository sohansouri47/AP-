"""Batch Invoice Processing Component.

Provides a clean dashboard for multi-invoice batch uploads, tracking per-invoice
execution status, review gates, and seamless switching between batch items.
"""

from __future__ import annotations

from typing import Any
import pandas as pd
import streamlit as st

from components.decision_view import render_decision_status_badge


def render_batch_summary_card(
    batch_results: list[dict[str, Any]],
    current_thread_id: str | None = None,
) -> str | None:
    """Render a clean batch summary dashboard for multiple processed invoices.

    Returns the thread_id of any selected invoice if the user clicked inspect.
    """
    if not batch_results:
        return None

    total_count = len(batch_results)
    completed_count = sum(
        1 for r in batch_results if r.get("lifecycle_status") == "POSTING_PACKAGE_READY"
    )
    needs_attention_count = sum(
        1
        for r in batch_results
        if r.get("lifecycle_status") in ("AP_REVIEW", "NEEDS_ATTENTION")
    )
    approval_ready_count = sum(
        1
        for r in batch_results
        if r.get("lifecycle_status") in ("FINANCE_APPROVAL", "READY_FOR_APPROVAL")
    )
    blocked_count = sum(
        1
        for r in batch_results
        if r.get("lifecycle_status") in ("BLOCKED", "REJECTED")
    )

    with st.container(border=True):
        # Header Row
        h_left, h_right = st.columns([1.5, 2], vertical_alignment="center")
        with h_left:
            st.markdown(
                f"""
                <div style="display: flex; align-items: baseline; gap: 8px;">
                    <span class="ap-card-title">Batch Processing Summary</span>
                    <span style="font-size: 0.8rem; color: var(--text-muted); font-weight: 500;">({total_count} invoices)</span>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with h_right:
            badges_html = []
            if completed_count:
                badges_html.append(
                    f'<span class="status-pill status-pill-green">{completed_count} Posted</span>'
                )
            if approval_ready_count:
                badges_html.append(
                    f'<span class="status-pill status-pill-blue">{approval_ready_count} Ready for Sign-off</span>'
                )
            if needs_attention_count:
                badges_html.append(
                    f'<span class="status-pill status-pill-amber">{needs_attention_count} Needs AP Review</span>'
                )
            if blocked_count:
                badges_html.append(
                    f'<span class="status-pill status-pill-red">{blocked_count} Blocked / Exception</span>'
                )
            st.markdown(
                f"""<div style="display: flex; gap: 6px; justify-content: flex-end; flex-wrap: wrap;">{''.join(badges_html)}</div>""",
                unsafe_allow_html=True,
            )

        st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)

        selected_tid = None

        # Render each invoice row
        for idx, item in enumerate(batch_results):
            tid = item.get("thread_id", "")
            fname = item.get("filename", f"Invoice #{idx + 1}")
            supp = item.get("supplier_name", "—")
            inv_num = item.get("invoice_number", "—")
            amt = item.get("total_amount")
            amt_str = f"${amt:,.2f}" if isinstance(amt, (int, float)) else "—"
            st_val = item.get("lifecycle_status", "UNKNOWN")
            is_active = tid == current_thread_id

            row_border = "border: 1.5px solid var(--primary);" if is_active else "border: 1px solid var(--border-color);"
            row_bg = "background: var(--bg-card-subtle);" if is_active else "background: var(--bg-card);"

            with st.container():
                c1, c2, c3, c4, c5, c6 = st.columns([1.6, 1.3, 1.1, 1.0, 1.4, 1.2], vertical_alignment="center")

                with c1:
                    active_tag = '<span style="color: var(--primary); font-size: 0.72rem; font-weight: 700; margin-right: 4px;">●</span>' if is_active else ''
                    st.markdown(
                        f"""
                        <div style="font-weight: 600; font-size: 0.85rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">
                            {active_tag}<code>{fname}</code>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                with c2:
                    st.markdown(
                        f"""<div style="font-size: 0.82rem; color: var(--text-primary);">{supp}</div>""",
                        unsafe_allow_html=True,
                    )
                with c3:
                    st.markdown(
                        f"""<div style="font-size: 0.82rem; color: var(--text-secondary);">{inv_num}</div>""",
                        unsafe_allow_html=True,
                    )
                with c4:
                    st.markdown(
                        f"""<div style="font-size: 0.82rem; font-weight: 600;">{amt_str}</div>""",
                        unsafe_allow_html=True,
                    )
                with c5:
                    st.markdown(render_decision_status_badge(st_val), unsafe_allow_html=True)

                with c6:
                    btn_text = "Viewing" if is_active else "Inspect"
                    if st.button(
                        btn_text,
                        key=f"btn_inspect_batch_{tid}_{idx}",
                        type="primary" if is_active else "secondary",
                        disabled=is_active,
                        use_container_width=True,
                    ):
                        selected_tid = tid

                st.markdown("<hr style='margin: 4px 0; border: none; border-bottom: 1px solid var(--border-color);' />", unsafe_allow_html=True)

    return selected_tid
