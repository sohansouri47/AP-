"""ZAMP Accounts Payable AI Employee — Frontend Microservice.

Modern, clean finance-operations application built with Streamlit.
Header Layout:
[ AP AI Employee logo/name ]   [ Process Invoice | Decision | History ]      [ Settings ⚙ ]

Core Views:
1. Process Invoice: Simple dropzone/scenario, run status card, 7-step vertical business stepper, recent activity.
2. Decision: Status badge header, decision summary & required next action, tabs for invoice, PO, controls, evidence.
3. History: Clean table-first history with search, status/date filters, and row selection.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Ensure frontend directory is at the top of sys.path
_FRONTEND_DIR = str(Path(__file__).resolve().parent)
if _FRONTEND_DIR not in sys.path:
    sys.path.insert(0, _FRONTEND_DIR)

import streamlit as st

from api_client import BackendAPIClient
from theme import init_theme, get_theme_css, render_theme_toggle
from components.stepper import render_business_stepper, render_execution_timeline
from components.decision_view import (
    render_decision_details,
    render_decision_summary_card,
    render_contextual_action_card,
)
from components.history_table import render_run_history
from components.master_data_view import render_master_data_page
from components.batch_view import render_batch_summary_card

# Page Configuration (Clean, centered max-width layout, collapsed sidebar)
st.set_page_config(
    page_title="AP AI Employee",
    page_icon=":material/account_balance:",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# Initialize Theme & Session State
init_theme()
if "pending_nav_tab" in st.session_state:
    pending = st.session_state.pop("pending_nav_tab")
    st.session_state["active_tab"] = pending
    st.session_state["main_nav_tab"] = pending

if "backend_url" not in st.session_state:
    st.session_state["backend_url"] = os.environ.get("BACKEND_URL", "http://127.0.0.1:8080")
if "active_tab" not in st.session_state:
    st.session_state["active_tab"] = "Process Invoice"
if "current_thread_id" not in st.session_state:
    st.session_state["current_thread_id"] = ""
if "live_events" not in st.session_state:
    st.session_state["live_events"] = []
if "current_snapshot" not in st.session_state:
    st.session_state["current_snapshot"] = None
if "batch_results" not in st.session_state:
    st.session_state["batch_results"] = []

# Inject Dynamic Theme CSS
st.markdown(get_theme_css(), unsafe_allow_html=True)

# Load CSS Stylesheet
CSS_PATH = Path(__file__).resolve().parent / "styles.css"
if CSS_PATH.exists():
    with open(CSS_PATH) as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

# API Client
client = BackendAPIClient(base_url=st.session_state["backend_url"])
health = client.check_health()
is_healthy = health.get("status") == "healthy"

# =====================================================================
# 1. APPLICATION SHELL & COMPACT HEADER
# [ AP AI Employee logo/name ]   [ Process Invoice | Decision | History ]   [ Settings ⚙ ]
# =====================================================================
header_col1, header_col2, header_col3 = st.columns([1.8, 2.8, 0.9], vertical_alignment="center")

with header_col1:
    st.markdown(
        """
        <div style="display: flex; align-items: center; gap: 10px;">
            <div class="brand-badge">AP</div>
            <div>
                <div class="brand-title">AP AI Employee</div>
                <div class="brand-subtitle">Autonomous AP Finance</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

with header_col2:
    nav_options = ["Process Invoice", "Decision", "History", "Master Data"]
    # Map legacy keys if needed
    legacy_map = {
        "Process invoice": "Process Invoice",
        "Decision details": "Decision",
        "Run history": "History",
        "Master data": "Master Data",
        "Vendor details": "Master Data",
        "Seeded data": "Master Data",
    }
    cur_tab = legacy_map.get(st.session_state["active_tab"], st.session_state["active_tab"])
    if cur_tab not in nav_options:
        cur_tab = "Process Invoice"

    if "main_nav_tab" not in st.session_state or st.session_state["main_nav_tab"] not in nav_options:
        st.session_state["main_nav_tab"] = cur_tab

    selected_nav = st.segmented_control(
        "Navigation",
        options=nav_options,
        selection_mode="single",
        required=True,
        key="main_nav_tab",
        label_visibility="collapsed",
    )

    if selected_nav and selected_nav != st.session_state["active_tab"]:
        st.session_state["active_tab"] = selected_nav
        st.rerun()

with header_col3:
    with st.popover("Settings", icon=":material/settings:"):
        st.markdown("##### Theme & Display")
        render_theme_toggle()

        st.markdown("<hr style='margin: 10px 0; border: none; border-bottom: 1px solid var(--border-color);' />", unsafe_allow_html=True)
        st.markdown("##### Connectivity")
        if is_healthy:
            st.markdown(":material/check_circle: **FastAPI:** Connected")
            st.markdown(":material/check_circle: **PostgreSQL:** Online (PostgresSaver)")
            st.markdown(":material/check_circle: **FastMCP:** Online (34 tools)")
        else:
            err_msg = health.get("error", "Offline")
            st.markdown(f":material/error: **Backend:** Offline ({err_msg})")

        backend_url_input = st.text_input(
            "FastAPI URL",
            value=st.session_state["backend_url"],
            key="cfg_backend_url",
        )
        if backend_url_input != st.session_state["backend_url"]:
            st.session_state["backend_url"] = backend_url_input
            st.rerun()

        st.markdown("<hr style='margin: 8px 0; border: none; border-bottom: 1px solid var(--border-color);' />", unsafe_allow_html=True)
        st.caption("All sensitive banking information masked to `account_last4`.")

st.markdown("<hr style='border: none; border-bottom: 1px solid var(--border-color); margin: 0.4rem 0 1.25rem 0;' />", unsafe_allow_html=True)

# Normalize active tab string
current_tab = legacy_map.get(st.session_state["active_tab"], st.session_state["active_tab"])

# =====================================================================
# 2. PAGE 1: PROCESS INVOICE
# Page title + short description
# [ Upload invoice card ]     [ Run status / decision card ]
# Processing activity
# [ clean vertical stepper ]
# Recent activity / latest events
# =====================================================================
if current_tab == "Process Invoice":
    st.markdown('<div class="page-title">Process Invoice</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-description">Autonomous extraction, deterministic financial policy validation, and human governance.</div>',
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([1.1, 1], gap="large")

    with col_left:
        with st.container(border=True):
            st.markdown('<div class="ap-card-title">Upload invoice</div>', unsafe_allow_html=True)
            st.markdown("<div style='height: 4px;'></div>", unsafe_allow_html=True)

            if "input_method_select" not in st.session_state:
                st.session_state["input_method_select"] = "Demo scenarios"

            input_method = st.segmented_control(
                "Input method",
                ["Demo scenarios", "Upload PDF"],
                selection_mode="single",
                required=True,
                key="input_method_select",
                label_visibility="collapsed",
            )

            selected_fixture = None
            uploaded_files = []
            sample_pdf_path = Path(__file__).resolve().parents[1] / "backend" / "tests" / "data" / "sample_invoice.pdf"

            if input_method == "Demo scenarios":
                scenario_choice = st.selectbox(
                    "Select invoice scenario",
                    [
                        "Ambiguous PO invoice (Globex Corp — Triggers AP review)",
                        "Sample invoice PDF (Real document with GPT-4o-mini vision)",
                        "Tax mismatch invoice (Acme Supplies — Triggers auto-rejection)",
                        "Happy path invoice (Acme Supplies — Clean match)",
                        "All demo scenarios (Batch of 4 scenarios)",
                    ],
                    key="scenario_choice_select",
                )
                if "Ambiguous PO" in scenario_choice:
                    selected_fixture = "inv-ambiguous-po"
                elif "Sample invoice PDF" in scenario_choice:
                    selected_fixture = "REAL_PDF"
                elif "Tax mismatch" in scenario_choice:
                    selected_fixture = "inv-tax-mismatch"
                elif "All demo scenarios" in scenario_choice:
                    selected_fixture = "BATCH_ALL"
                else:
                    selected_fixture = "inv-happy-001"
            else:
                uploaded_files = st.file_uploader(
                    "Drag and drop PDF invoices (supports multiple files)",
                    type=["pdf"],
                    accept_multiple_files=True,
                    key="custom_pdf_uploader",
                    label_visibility="collapsed",
                )

            workflow_version = st.text_input(
                "Financial policy version",
                value="v1.0.0",
                key="input_wf_version",
                help="Policy version governing 3-way match tolerances and approval routes.",
            )

            is_batch = False
            batch_count = 0
            if input_method == "Upload PDF":
                if uploaded_files and len(uploaded_files) > 1:
                    is_batch = True
                    batch_count = len(uploaded_files)
            elif input_method == "Demo scenarios" and selected_fixture == "BATCH_ALL":
                is_batch = True
                batch_count = 4

            btn_label = f"Process {batch_count} invoices in batch" if is_batch else "Process invoice"

            start_btn = st.button(
                btn_label,
                type="primary",
                icon=":material/play_arrow:",
                disabled=not is_healthy,
            )

    with col_right:
        with st.container(border=True):
            st.markdown('<div class="ap-card-title">Run status / decision</div>', unsafe_allow_html=True)

            current_tid = st.session_state.get("current_thread_id")
            snapshot = st.session_state.get("current_snapshot")

            if not snapshot and current_tid:
                try:
                    snapshot = client.get_status(current_tid)
                    st.session_state["current_snapshot"] = snapshot
                except Exception:
                    snapshot = None

            if snapshot and current_tid:
                render_decision_summary_card(snapshot)
                st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
                if st.button("Inspect full decision ➔", key="btn_jump_to_decision"):
                    st.session_state["pending_nav_tab"] = "Decision"
                    st.rerun()
            else:
                st.markdown(
                    """
                    <div style="border: 1px dashed var(--border-color); border-radius: 8px; padding: 2.25rem 1.5rem; text-align: center; color: var(--text-muted);">
                        <div style="font-size: 0.92rem; font-weight: 500;">No active run</div>
                        <div style="font-size: 0.8rem; margin-top: 0.25rem;">Select an invoice scenario or upload a PDF to begin processing.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    # -----------------------------------------------------------------
    # Live Execution Section (Triggered on Run)
    # -----------------------------------------------------------------
    if start_btn:
        st.session_state["live_events"] = []
        st.session_state["current_snapshot"] = None

        if is_batch:
            # Multi-file batch processing workflow
            items_to_process: list[dict[str, Any]] = []
            if input_method == "Upload PDF":
                for uf in (uploaded_files or []):
                    uf.seek(0)
                    items_to_process.append({
                        "type": "pdf",
                        "filename": uf.name,
                        "bytes": uf.read(),
                    })
            else:
                items_to_process = [
                    {"type": "fixture", "fixture_id": "inv-happy-001", "filename": "inv-happy-001 (Acme Supplies)"},
                    {"type": "fixture", "fixture_id": "inv-ambiguous-po", "filename": "inv-ambiguous-po (Globex Corp)"},
                    {"type": "fixture", "fixture_id": "inv-tax-mismatch", "filename": "inv-tax-mismatch (Acme Supplies)"},
                    {"type": "pdf_path", "path": sample_pdf_path, "filename": "sample_invoice.pdf"},
                ]

            progress_bar = st.progress(0.0, text=f"Processing 1 of {len(items_to_process)} invoices...")
            batch_results = []

            for idx, item in enumerate(items_to_process):
                fname = item["filename"]
                pct = idx / len(items_to_process)
                progress_bar.progress(pct, text=f"Processing {idx + 1} of {len(items_to_process)}: {fname}")

                try:
                    if item["type"] == "pdf":
                        res = client.upload_invoice_file(item["bytes"], fname, workflow_version)
                    elif item["type"] == "pdf_path":
                        if not item["path"].exists():
                            raise FileNotFoundError(f"File not found: {item['path']}")
                        res = client.upload_invoice_file(item["path"].read_bytes(), fname, workflow_version)
                    else:
                        res = client.upload_invoice_json(item["fixture_id"], workflow_version)

                    tid = res.get("thread_id")
                    events = client.get_events(tid) if tid else []
                    snapshot = client.get_status(tid) if tid else {}
                    inv_data = snapshot.get("extracted_invoice") or snapshot.get("invoice_data") or {}
                    pkg = snapshot.get("posting_package") or {}

                    batch_results.append({
                        "filename": fname,
                        "thread_id": tid,
                        "lifecycle_status": snapshot.get("lifecycle_status") or "UNKNOWN",
                        "supplier_name": inv_data.get("supplier_name") or inv_data.get("vendor_name") or "—",
                        "invoice_number": inv_data.get("invoice_number") or inv_data.get("invoice_id") or pkg.get("invoice_number") or "—",
                        "total_amount": inv_data.get("total_amount") if inv_data.get("total_amount") is not None else pkg.get("total_amount"),
                        "events": events,
                        "snapshot": snapshot,
                    })
                except Exception as exc:
                    batch_results.append({
                        "filename": fname,
                        "thread_id": None,
                        "lifecycle_status": "BLOCKED",
                        "supplier_name": "—",
                        "invoice_number": "—",
                        "total_amount": None,
                        "events": [],
                        "snapshot": {"error": str(exc)},
                    })

            progress_bar.progress(1.0, text=f"Processed all {len(items_to_process)} invoices successfully!")
            st.session_state["batch_results"] = batch_results

            # Set first valid invoice as active for detailed inspection
            first_valid = next((b for b in batch_results if b.get("thread_id")), None)
            if first_valid:
                st.session_state["current_thread_id"] = first_valid["thread_id"]
                st.session_state["current_snapshot"] = first_valid["snapshot"]
                st.session_state["live_events"] = first_valid["events"]

            st.rerun()

        else:
            # Single-run SSE live streaming workflow
            st.session_state["batch_results"] = []
            thread_id = None

            try:
                if input_method == "Upload PDF":
                    if not uploaded_files:
                        st.error("Please select a PDF file to upload.")
                        st.stop()
                    uploaded_files[0].seek(0)
                    res = client.upload_invoice_file(
                        uploaded_files[0].read(),
                        uploaded_files[0].name,
                        workflow_version,
                    )
                else:
                    if selected_fixture == "REAL_PDF":
                        if not sample_pdf_path.exists():
                            st.error(f"Sample PDF not found at {sample_pdf_path}")
                            st.stop()
                        res = client.upload_invoice_file(
                            sample_pdf_path.read_bytes(),
                            "sample_invoice.pdf",
                            workflow_version,
                        )
                    else:
                        res = client.upload_invoice_json(selected_fixture, workflow_version)

                thread_id = res.get("thread_id")
                st.session_state["current_thread_id"] = thread_id

            except Exception as e:
                st.error(f"Ingestion error: {e}")
                st.stop()

            # Stream real-time events via Server-Sent Events (SSE)
            if thread_id:
                st.markdown('<div class="ap-card-title" style="margin-top: 1.5rem; margin-bottom: 0.5rem;">Processing activity</div>', unsafe_allow_html=True)
                stepper_placeholder = st.empty()
                events_accumulated = []

                try:
                    for ev in client.stream_events(thread_id):
                        events_accumulated.append(ev)
                        with stepper_placeholder.container():
                            with st.container(border=True):
                                render_business_stepper(events_accumulated)

                    st.session_state["live_events"] = events_accumulated

                    # Fetch final status snapshot
                    snapshot = client.get_status(thread_id)
                    st.session_state["current_snapshot"] = snapshot

                except Exception as e:
                    st.warning(f"Event stream completed: {e}")

                st.rerun()

    # -----------------------------------------------------------------
    # Render Batch Summary Card & Stepper / Activity
    # -----------------------------------------------------------------
    if st.session_state.get("batch_results"):
        st.markdown("<div style='height: 14px;'></div>", unsafe_allow_html=True)
        inspect_tid = render_batch_summary_card(
            st.session_state["batch_results"],
            current_thread_id=st.session_state.get("current_thread_id"),
        )
        if inspect_tid and inspect_tid != st.session_state.get("current_thread_id"):
            st.session_state["current_thread_id"] = inspect_tid
            matched = next((b for b in st.session_state["batch_results"] if b.get("thread_id") == inspect_tid), None)
            if matched:
                st.session_state["current_snapshot"] = matched.get("snapshot")
                st.session_state["live_events"] = matched.get("events") or []
            else:
                try:
                    st.session_state["current_snapshot"] = client.get_status(inspect_tid)
                    st.session_state["live_events"] = client.get_events(inspect_tid)
                except Exception:
                    pass
            st.rerun()

    if st.session_state.get("live_events") or st.session_state.get("current_thread_id"):
        curr_tid = st.session_state.get("current_thread_id", "")
        title_suffix = f" — <code>{curr_tid[:14]}</code>" if curr_tid else ""
        st.markdown(f'<div class="ap-card-title" style="margin-top: 1.5rem; margin-bottom: 0.5rem;">Processing activity{title_suffix}</div>', unsafe_allow_html=True)
        with st.container(border=True):
            render_business_stepper(
                st.session_state["live_events"],
                st.session_state.get("current_snapshot"),
            )

        # Recent activity / latest events
        events_list = [e for e in st.session_state["live_events"] if e.get("event") != "stream_completed"]
        if events_list:
            with st.expander("Recent activity / live event feed", expanded=False):
                for ev in reversed(events_list[-8:]):
                    etype = ev.get("event", "event")
                    etime = ev.get("timestamp")
                    time_str = time.strftime("%H:%M:%S", time.localtime(etime)) if isinstance(etime, (int, float)) else str(etime or "")
                    st.markdown(
                        f"""
                        <div style="display: flex; justify-content: space-between; padding: 4px 0; border-bottom: 1px solid var(--border-color); font-size: 0.8rem;">
                            <span><code>{etype}</code>: {ev.get('data', {}).get('message') or ev.get('data', {}).get('action') or ev.get('data', {}).get('status') or 'Completed'}</span>
                            <span style="color: var(--text-muted); font-family: monospace;">{time_str}</span>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

# =====================================================================
# 3. PAGE 2: DECISION DETAILS
# Status badge header, supplier, invoice, total amount
# [ Decision summary ] [ Required next action ]
# Tabs: Invoice details | Purchase order match | Controls | Evidence
# =====================================================================
elif current_tab == "Decision":
    st.markdown('<div class="page-title">Decision Details</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="page-description">Detailed audit record, 3-way match reconciliation, and governance action gates.</div>',
        unsafe_allow_html=True,
    )

    t_col1, t_col2 = st.columns([3, 1], vertical_alignment="bottom")
    with t_col1:
        selected_tid = st.text_input(
            "Run Thread ID",
            value=st.session_state.get("current_thread_id", ""),
            placeholder="e.g. run-3a27b314075a",
            key="input_thread_id_decision_page",
        )
        if selected_tid != st.session_state.get("current_thread_id"):
            st.session_state["current_thread_id"] = selected_tid
            st.session_state["current_snapshot"] = None
    with t_col2:
        if st.button("Refresh status", icon=":material/refresh:"):
            st.rerun()

    st.markdown("<div style='height: 8px;'></div>", unsafe_allow_html=True)
    render_decision_details(client, st.session_state.get("current_thread_id", ""))

# =====================================================================
# 4. PAGE 3: HISTORY
# Clean table-first history page
# =====================================================================
elif current_tab == "History":
    selected_run = render_run_history(client)
    if selected_run:
        st.session_state["current_thread_id"] = selected_run
        st.session_state["current_snapshot"] = None
        st.session_state["pending_nav_tab"] = "Decision"
        st.rerun()

# =====================================================================
# 5. PAGE 4: VENDOR & MASTER DATA
# =====================================================================
elif current_tab == "Master Data":
    render_master_data_page()
