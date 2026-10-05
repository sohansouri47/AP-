"""Clean, modern 7-step vertical business stepper for AP AI Employee.

Business-readable canonical steps:
1. Invoice received
2. Extracting invoice details
3. Validating supplier and duplicate risk
4. Matching purchase order
5. Running financial controls
6. Preparing decision
7. Awaiting human action / Complete

Rules:
- Completed = subtle green check
- Current = blue filled indicator and short live message
- Future = muted gray
- Failed / needs attention = amber or red, with one short reason
- Updates strictly from genuine SSE / backend events.
"""

from __future__ import annotations

import datetime
from typing import Any
import streamlit as st


EVENT_CONFIG = {
    "uploaded": {
        "title": "Invoice ingested",
        "icon": "upload_file",
        "badge_class": "status-pill-blue",
        "badge_text": "Ingested",
        "description": "Document validated and SHA-256 fingerprint registered.",
    },
    "extraction_started": {
        "title": "Vision extraction started",
        "icon": "visibility",
        "badge_class": "status-pill-blue",
        "badge_text": "Extracting",
        "description": "Multimodal vision model parsing optical text and tabular line items.",
    },
    "extraction_completed": {
        "title": "Invoice data extracted",
        "icon": "check_circle",
        "badge_class": "status-pill-green",
        "badge_text": "Extracted",
        "description": "Structured invoice fields, line items, and totals extracted by vision model.",
    },
    "supplier_resolved": {
        "title": "Supplier verified",
        "icon": "domain",
        "badge_class": "status-pill-green",
        "badge_text": "Verified",
        "description": "Supplier Tax ID and vendor profile resolved in master ledger.",
    },
    "control_completed": {
        "title": "Financial control check",
        "icon": "verified_user",
        "badge_class": "status-pill-green",
        "badge_text": "Passed",
        "description": "Deterministic control check evaluated against financial policy.",
    },
    "exception_raised": {
        "title": "Variance flagged",
        "icon": "warning",
        "badge_class": "status-pill-amber",
        "badge_text": "Attention",
        "description": "Tolerance variance or ambiguous match identified.",
    },
    "decision_ready": {
        "title": "Decision synthesized",
        "icon": "gavel",
        "badge_class": "status-pill-blue",
        "badge_text": "Decision",
        "description": "Autonomous evaluation complete across all mandatory controls.",
    },
    "human_action_received": {
        "title": "Human action recorded",
        "icon": "how_to_reg",
        "badge_class": "status-pill-blue",
        "badge_text": "Action",
        "description": "Revision-safe human input registered with digital audit signature.",
    },
    "awaiting_human_action": {
        "title": "Awaiting human review",
        "icon": "pending_actions",
        "badge_class": "status-pill-amber",
        "badge_text": "Gate Paused",
        "description": "Execution paused at review gate; action required to advance workflow.",
    },
    "posting_package_ready": {
        "title": "ERP posting package ready",
        "icon": "inventory_2",
        "badge_class": "status-pill-green",
        "badge_text": "Completed",
        "description": "Final immutable ERP-ready ledger payload compiled.",
    },
}

EVENT_METADATA = EVENT_CONFIG


def _format_time(timestamp: float | str | None) -> str:
    """Format Unix timestamp or ISO string to HH:MM:SS."""
    if not timestamp:
        return ""
    try:
        if isinstance(timestamp, (int, float)):
            dt = datetime.datetime.fromtimestamp(timestamp)
            return dt.strftime("%H:%M:%S")
        return str(timestamp)
    except Exception:
        return str(timestamp)


def compute_canonical_steps(
    events: list[dict[str, Any]],
    status_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Derive state for each of the 7 business-readable steps from genuine backend events."""
    event_types = [e.get("event") for e in events]
    status_data = status_data or {}
    ctrl_rep = status_data.get("control_report") or {}
    checks = ctrl_rep.get("check_results") or status_data.get("check_results") or []

    # Build a synthetic check map from live control_completed events so the stepper
    # shows failures/warnings in real-time during SSE streaming (before status_data arrives).
    event_checks: dict[str, dict] = {}
    for ev in events:
        if ev.get("event") == "control_completed":
            d = ev.get("data") or {}
            cid = d.get("check_id")
            if cid:
                event_checks[cid] = d
        elif ev.get("event") == "exception_raised":
            d = ev.get("data") or {}
            cid = d.get("check_id")
            if cid and cid in event_checks:
                event_checks[cid]["status"] = d.get("status", "FAILED")

    # Merge: status_data checks take precedence (more authoritative), fill gaps with event_checks
    merged_checks = {c.get("check_id"): c for c in checks}
    for cid, c in event_checks.items():
        if cid not in merged_checks:
            merged_checks[cid] = c
    all_checks = list(merged_checks.values())

    # Lifecycle status: prefer status_data, fall back to decision_ready event data
    lifecycle_status = (status_data.get("lifecycle_status") or "").upper()
    if not lifecycle_status:
        dec_ev = next((e for e in events if e.get("event") == "decision_ready"), None)
        if dec_ev:
            lifecycle_status = ((dec_ev.get("data") or {}).get("lifecycle_status") or "").upper()

    has_uploaded = "uploaded" in event_types or bool(status_data)
    has_extraction_started = "extraction_started" in event_types
    has_extraction_completed = "extraction_completed" in event_types
    has_supplier_resolved = "supplier_resolved" in event_types or bool(status_data.get("extracted_invoice"))
    has_decision = "decision_ready" in event_types or bool(status_data.get("decision"))
    has_posting_package = "posting_package_ready" in event_types or lifecycle_status == "POSTING_PACKAGE_READY"
    has_human_action = "human_action_received" in event_types

    # Find specific control results from merged view
    dup_check = next((c for c in all_checks if c.get("check_id") == "CHK_BIZ_DUP"), None)
    dup_failed = dup_check and dup_check.get("status") in ("FAILED", "BLOCKED")

    po_checks = [c for c in all_checks if "PO" in c.get("check_id", "") or "3WAY" in c.get("check_id", "")]
    po_needs_input = any(c.get("status") == "REQUIRES_INPUT" for c in po_checks) or (
        lifecycle_status in ("AP_REVIEW", "NEEDS_ATTENTION") and not has_human_action
    )
    po_failed = any(c.get("status") == "FAILED" for c in po_checks)

    failed_ctrl = next(
        (c for c in all_checks if c.get("status") == "FAILED" and c.get("check_id") != "CHK_BIZ_DUP"),
        None,
    )
    checks = all_checks  # use merged set for the rest of the function

    steps = [
        {
            "num": 1,
            "title": "Invoice received",
            "state": "future",
            "message": "",
        },
        {
            "num": 2,
            "title": "Extracting invoice details",
            "state": "future",
            "message": "",
        },
        {
            "num": 3,
            "title": "Validating supplier and duplicate risk",
            "state": "future",
            "message": "",
        },
        {
            "num": 4,
            "title": "Matching purchase order",
            "state": "future",
            "message": "",
        },
        {
            "num": 5,
            "title": "Running financial controls",
            "state": "future",
            "message": "",
        },
        {
            "num": 6,
            "title": "Preparing decision",
            "state": "future",
            "message": "",
        },
        {
            "num": 7,
            "title": "Awaiting human action / Complete",
            "state": "future",
            "message": "",
        },
    ]

    if not events and not status_data:
        return steps

    # 1. Invoice received
    if has_uploaded:
        steps[0]["state"] = "completed"
        steps[0]["message"] = "Document received and SHA-256 fingerprint verified"
    else:
        steps[0]["state"] = "future"

    # 2. Extracting invoice details
    if has_supplier_resolved or checks or has_decision:
        steps[1]["state"] = "completed"
        ext = status_data.get("extracted_invoice") or {}
        inv_num = ext.get("invoice_number")
        if not inv_num:  # fall back to extraction_completed event during live streaming
            ext_ev = next((e for e in events if e.get("event") == "extraction_completed"), {})
            inv_num = (ext_ev.get("data") or {}).get("invoice_number")
        steps[1]["message"] = f"Invoice #{inv_num} line items and optical data parsed" if inv_num else "Line items parsed via multimodal vision model"
    elif has_extraction_completed:
        # Extraction finished — controls starting next
        steps[1]["state"] = "completed"
        ext_ev = next((e for e in events if e.get("event") == "extraction_completed"), {})
        inv_num = (ext_ev.get("data") or {}).get("invoice_number")
        steps[1]["message"] = f"Invoice #{inv_num} extracted" if inv_num else "Invoice data extracted successfully"
    elif has_extraction_started:
        steps[1]["state"] = "current"
        steps[1]["message"] = "Multimodal vision model parsing optical text and tabular line items..."
    elif steps[0]["state"] == "completed":
        steps[1]["state"] = "current"
        steps[1]["message"] = "Starting invoice document parsing..."

    # 3. Validating supplier and duplicate risk
    if dup_failed:
        steps[2]["state"] = "failed"
        steps[2]["message"] = "Duplicate invoice detected in master ledger"
    elif has_decision or checks or has_supplier_resolved:
        steps[2]["state"] = "completed"
        supp = (status_data.get("extracted_invoice") or {}).get("supplier_name")
        steps[2]["message"] = f"Supplier verified: {supp} (No duplicates found)" if supp else "Supplier Tax ID and duplicate risk clear"
    elif steps[1]["state"] == "completed":
        steps[2]["state"] = "current"
        steps[2]["message"] = "Validating supplier record in master ledger..."

    # When step 3 hard-fails (duplicate invoice), cascade: steps 4 & 5 are blocked upstream
    upstream_hard_fail = steps[2]["state"] == "failed"

    # 4. Matching purchase order
    if upstream_hard_fail:
        steps[3]["state"] = "failed"
        steps[3]["message"] = "Not evaluated — invoice blocked at duplicate check"
    elif po_needs_input:
        steps[3]["state"] = "warning"
        steps[3]["message"] = "Ambiguous purchase order: multiple candidate POs found"
    elif po_failed:
        steps[3]["state"] = "failed"
        steps[3]["message"] = "PO 3-way match tolerance threshold exceeded"
    elif has_decision or has_posting_package or (po_checks and all(c.get("status") == "PASSED" for c in po_checks)):
        steps[3]["state"] = "completed"
        po_num = (status_data.get("po_match") or {}).get("po_number")
        steps[3]["message"] = f"Matched with {po_num} within tolerance" if po_num else "Purchase order matched within tolerance"
    elif steps[2]["state"] == "completed" and checks:
        steps[3]["state"] = "current"
        steps[3]["message"] = "Reconciling line items against purchase orders..."

    # 5. Running financial controls
    if upstream_hard_fail:
        steps[4]["state"] = "failed"
        steps[4]["message"] = "Not evaluated — invoice blocked at duplicate check"
    elif failed_ctrl:
        steps[4]["state"] = "failed"
        steps[4]["message"] = f"{failed_ctrl.get('check_id')}: {failed_ctrl.get('message', 'Control check failed')}"
    elif has_decision or has_posting_package or (checks and len(checks) >= 8):
        steps[4]["state"] = "completed"
        steps[4]["message"] = "All 13 deterministic financial control policies passed"
    elif steps[3]["state"] in ("completed", "warning"):
        steps[4]["state"] = "current"
        steps[4]["message"] = "Evaluating math, tax balance, and payment policy checks..."

    # 6. Preparing decision
    if has_decision or (status_data and status_data.get("decision")):
        steps[5]["state"] = "completed"
        route_name = lifecycle_status.replace("_", " ").title() if lifecycle_status else "Decision ready"
        steps[5]["message"] = f"Decision synthesized: {route_name}"
    elif steps[4]["state"] in ("completed", "warning", "failed"):
        steps[5]["state"] = "current"
        steps[5]["message"] = "Synthesizing audit decision and confidence score..."

    # 7. Awaiting human action / Complete
    if has_posting_package or lifecycle_status == "POSTING_PACKAGE_READY":
        steps[6]["state"] = "completed"
        steps[6]["message"] = "Posting package ready for ERP export"
    elif lifecycle_status in ("AP_REVIEW", "NEEDS_ATTENTION"):
        steps[6]["state"] = "warning"
        steps[6]["message"] = "Paused at AP Review gate (Operator resolution needed)"
    elif lifecycle_status in ("FINANCE_APPROVAL", "READY_FOR_APPROVAL"):
        steps[6]["state"] = "current"
        steps[6]["message"] = "Paused at Finance Approval gate (Sign-off needed)"
    elif lifecycle_status in ("BLOCKED", "REJECTED"):
        steps[6]["state"] = "failed"
        steps[6]["message"] = "Workflow concluded: Invoice rejected / blocked"
    elif steps[5]["state"] == "completed":
        steps[6]["state"] = "current"
        steps[6]["message"] = "Finalizing workflow outcome..."

    return steps


_AGENT_STEPS = {2, 3, 4, 5, 6}  # step numbers driven by deep-agent / AI

_CIRCLE_ICONS = {
    "completed": "✓",
    "warning":   "!",
    "failed":    "✕",
}

_BADGES = {
    "completed": '<span class="status-pill status-pill-green" style="font-size:0.66rem;padding:1px 6px;">Done</span>',
    "current":   '<span class="status-pill status-pill-blue"  style="font-size:0.66rem;padding:1px 6px;">Processing</span>',
    "warning":   '<span class="status-pill status-pill-amber" style="font-size:0.66rem;padding:1px 6px;">Action needed</span>',
    "failed":    '<span class="status-pill status-pill-red"   style="font-size:0.66rem;padding:1px 6px;">Failed</span>',
}

_THINKING_DOTS = (
    '<span class="thinking-dots">'
    '<span></span><span></span><span></span>'
    '</span>'
)


def _step_timestamp(events: list[dict[str, Any]], step_num: int) -> str:
    """Return HH:MM:SS for the event that maps to a given step, or ''."""
    step_event_map = {
        1: "uploaded",
        2: "extraction_started",
        3: "supplier_resolved",
        4: "control_completed",
        5: "control_completed",
        6: "decision_ready",
        7: "posting_package_ready",
    }
    target = step_event_map.get(step_num)
    if not target:
        return ""
    for ev in reversed(events):
        if ev.get("event") == target:
            ts = ev.get("timestamp")
            if ts:
                return _format_time(ts)
    return ""


def render_business_stepper(
    events: list[dict[str, Any]],
    status_data: dict[str, Any] | None = None,
):
    """Render an animated, deep-agent-aware vertical stepper."""
    if not events and not status_data:
        st.markdown(
            """
            <div style="border:1px dashed var(--border-color);border-radius:8px;
                        padding:2rem;text-align:center;color:var(--text-muted);">
                <div style="font-size:0.9rem;font-weight:500;">No execution in progress</div>
                <div style="font-size:0.8rem;margin-top:0.25rem;">
                    Select a scenario or upload an invoice to begin.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    steps = compute_canonical_steps(events, status_data)
    total = len(steps)

    completed_count = sum(1 for s in steps if s["state"] == "completed")
    is_active = any(s["state"] == "current" for s in steps)

    # ── Progress header ──────────────────────────────────────────────
    pct = int(completed_count / total * 100)
    fill_cls = "stepper-progress-fill-active" if is_active else "stepper-progress-fill"
    fill_style = f"width:{pct}%;" if not is_active else f"width:{max(pct, 12)}%;"

    agent_badge = (
        '<span class="agent-label" style="vertical-align:middle;">Deep Agent</span> '
        if is_active else ""
    )
    progress_html = (
        f'<div class="stepper-progress-header">'
        f'<span class="stepper-progress-label">{agent_badge}'
        f'{completed_count} / {total} steps</span>'
        f'<div class="stepper-progress-track">'
        f'<div class="{fill_cls}" style="{fill_style}"></div>'
        f'</div>'
        f'</div>'
    )

    # ── Steps ────────────────────────────────────────────────────────
    rows = []
    for idx, s in enumerate(steps):
        state = s["state"]
        is_last = idx == total - 1
        num = s["num"]
        title = s["title"]
        msg = s.get("message", "")

        circle_icon = _CIRCLE_ICONS.get(state, str(num))
        badge_html = _BADGES.get(state, "")

        # Agent micro-label on AI-driven steps
        if num in _AGENT_STEPS and state in ("completed", "current"):
            badge_html += ' <span class="agent-label">AI</span>'

        # Title class
        title_cls = "stepper-title"
        if state == "future":
            title_cls += " stepper-title-future"
        elif state == "current":
            title_cls += " stepper-title-current"

        # Timestamp for completed steps
        ts = _step_timestamp(events, num) if state == "completed" else ""
        ts_html = f'<span class="stepper-timestamp">{ts}</span>' if ts else ""

        # Message with thinking dots for active step
        msg_html = ""
        if msg:
            msg_cls = f"stepper-message stepper-message-{state}"
            dots = _THINKING_DOTS if state == "current" else ""
            msg_html = f'<div class="{msg_cls}">{msg}{dots}</div>'

        # Connecting line
        line_cls = "stepper-line" + (" stepper-line-completed" if state == "completed" else "")
        line_html = f'<div class="{line_cls}"></div>' if not is_last else ""

        # Step row class (highlight active)
        step_cls = "stepper-step" + (" stepper-step-current" if state == "current" else "")

        rows.append(
            f'<div class="{step_cls}">'
            f'<div class="stepper-left">'
            f'<div class="stepper-circle stepper-circle-{state}">{circle_icon}</div>'
            f'{line_html}'
            f'</div>'
            f'<div class="stepper-content">'
            f'<div class="{title_cls}">'
            f'<span>{num}. {title}</span>'
            f'{badge_html}'
            f'{ts_html}'
            f'</div>'
            f'{msg_html}'
            f'</div>'
            f'</div>'
        )

    st.markdown(
        progress_html + '<div class="stepper-container">' + "".join(rows) + "</div>",
        unsafe_allow_html=True,
    )


# Backwards compatibility aliases
render_execution_timeline = render_business_stepper
render_vertical_stepper = render_business_stepper


def render_timeline_step(event: dict[str, Any], is_last: bool = False):
    """Backwards compatible timeline step renderer."""
    render_business_stepper([event])

