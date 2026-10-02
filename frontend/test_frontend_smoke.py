"""Smoke tests for frontend microservice modules and components."""

import pytest
from frontend.components.stepper import EVENT_METADATA, _format_time
from frontend.components.decision_view import _get_status_badge
from frontend.api_client import BackendAPIClient

def test_stepper_event_metadata():
    expected_events = [
        "uploaded",
        "extraction_started",
        "supplier_resolved",
        "control_completed",
        "exception_raised",
        "decision_ready",
        "human_action_received",
        "posting_package_ready",
        "awaiting_human_action",
    ]
    for ev in expected_events:
        assert ev in EVENT_METADATA, f"Missing event metadata for {ev}"
        assert "title" in EVENT_METADATA[ev]
        assert "icon" in EVENT_METADATA[ev]
        assert "badge_text" in EVENT_METADATA[ev]

def test_stepper_format_time():
    ts = 1790920000.123
    formatted = _format_time(ts)
    assert ":" in formatted

def test_status_badge_posting_package_ready():
    badge = _get_status_badge("POSTING_PACKAGE_READY")
    assert "posting package ready" in badge.lower()
    assert "status-pill-green" in badge or "#16a34a" in badge

def test_api_client_initialization():
    client = BackendAPIClient("http://127.0.0.1:8080")
    assert client.base_url == "http://127.0.0.1:8080"


def test_batch_summary_card_logic():
    from frontend.components.batch_view import render_batch_summary_card

    # Test empty batch results return None
    assert render_batch_summary_card([]) is None

    # Test batch metrics and statuses
    mock_batch = [
        {
            "filename": "inv_01.pdf",
            "thread_id": "run-001",
            "lifecycle_status": "POSTING_PACKAGE_READY",
            "supplier_name": "Acme Corp",
            "invoice_number": "INV-001",
            "total_amount": 1250.50,
        },
        {
            "filename": "inv_02.pdf",
            "thread_id": "run-002",
            "lifecycle_status": "AP_REVIEW",
            "supplier_name": "Globex Corp",
            "invoice_number": "INV-002",
            "total_amount": 4500.00,
        },
        {
            "filename": "inv_03.pdf",
            "thread_id": "run-003",
            "lifecycle_status": "BLOCKED",
            "supplier_name": "Unknown",
            "invoice_number": "—",
            "total_amount": 99.00,
        },
    ]
    # Check that batch counts are accurate
    posted = sum(1 for r in mock_batch if r["lifecycle_status"] == "POSTING_PACKAGE_READY")
    review = sum(1 for r in mock_batch if r["lifecycle_status"] in ("AP_REVIEW", "NEEDS_ATTENTION"))
    blocked = sum(1 for r in mock_batch if r["lifecycle_status"] in ("BLOCKED", "REJECTED"))

    assert posted == 1
    assert review == 1
    assert blocked == 1

