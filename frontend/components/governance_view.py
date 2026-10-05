"""Governance Component — Policy & Self-Learning overview."""

from __future__ import annotations
import streamlit as st
from api_client import BackendAPIClient


def render_governance_page(client: BackendAPIClient):
    st.markdown("## Policy & Self-Learning Governance")
    st.markdown(
        "The AP AI Employee enforces a **gated self-improvement loop** — every policy change is staged, "
        "regression-tested against 50 golden cases, and requires named Administrator sign-off before going live. "
        "Nothing touches production automatically.",
        unsafe_allow_html=False,
    )

    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

    # ── Active policy banner ──────────────────────────────────────────
    st.markdown(
        """
        <div style="display:flex; align-items:center; gap:12px; background:#f0fdf4;
                    border:1px solid #bbf7d0; border-radius:10px; padding:14px 20px; margin-bottom:24px;">
            <span style="font-size:1.5rem;">🛡️</span>
            <div>
                <div style="font-weight:700; color:#166534; font-size:0.95rem;">Active Policy: v1.0.0</div>
                <div style="color:#15803d; font-size:0.8rem;">Production · 13 controls · 0 violations · Rollback-ready</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ── How it works ─────────────────────────────────────────────────
    st.markdown("#### How the improvement loop works")
    steps = [
        ("01", "Feedback ingestion", "AP operators' manual corrections are captured after every run."),
        ("02", "Pattern detection", "The agent groups recurring corrections into actionable patterns (≥ 2 occurrences)."),
        ("03", "Candidate staging", "A bounded declarative diff is staged as an inactive candidate version (e.g. v1.1.0)."),
        ("04", "Regression gate", "50 golden test cases run against the candidate — zero regressions required to proceed."),
        ("05", "Admin sign-off", "A named Administrator reviews and approves before anything goes live."),
    ]

    cols = st.columns(len(steps))
    for col, (num, title, desc) in zip(cols, steps):
        col.markdown(
            f"""
            <div style="text-align:center; padding:12px 8px;">
                <div style="font-size:1.4rem; font-weight:800; color:#3b82f6;">{num}</div>
                <div style="font-weight:600; font-size:0.82rem; color:#1e293b; margin:4px 0;">{title}</div>
                <div style="font-size:0.75rem; color:#64748b; line-height:1.4;">{desc}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # ── Coming-soon capabilities ──────────────────────────────────────
    st.markdown("#### Planned autonomous improvements")

    capabilities = [
        (
            "PO Line Mapping",
            "Learns recurring SKU → PO line corrections and auto-maps them in future runs.",
            "Eliminate manual re-mapping for known SKUs",
        ),
        (
            "Tolerance Tuning",
            "Detects when operators repeatedly approve the same variance and proposes an adjusted threshold.",
            "Reduce false-positive flags per supplier",
        ),
        (
            "Supplier Alias Rules",
            "Captures repeated manual supplier corrections and stages an alias so future invoices resolve automatically.",
            "Zero-touch supplier resolution for known aliases",
        ),
    ]

    c1, c2, c3 = st.columns(3)
    for col, (name, desc, benefit) in zip([c1, c2, c3], capabilities):
        col.markdown(
            f"""
            <div style="border:1px solid #e2e8f0; border-radius:10px; padding:18px; background:#fafafa; height:100%;">
                <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
                    <div style="font-weight:700; font-size:0.88rem; color:#1e293b;">{name}</div>
                    <span style="background:#fef9c3; color:#92400e; font-size:0.68rem; font-weight:700;
                                 padding:2px 8px; border-radius:9999px; white-space:nowrap; margin-left:8px;">Coming Soon</span>
                </div>
                <div style="font-size:0.78rem; color:#64748b; margin-bottom:10px; line-height:1.5;">{desc}</div>
                <div style="font-size:0.75rem; color:#3b82f6; font-weight:600;">→ {benefit}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:20px'></div>", unsafe_allow_html=True)

    # ── Disabled trigger ──────────────────────────────────────────────
    col_btn, col_note = st.columns([1, 2])
    with col_btn:
        st.button("Run Improvement Analysis", disabled=True, type="primary")
    with col_note:
        st.caption(
            "Will analyze recent corrections, stage a candidate, run the regression gate, "
            "and surface an Administrator approval request — all without touching production."
        )
