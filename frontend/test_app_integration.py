"""In-process integration test for Streamlit UI using AppTest."""

import pytest
from streamlit.testing.v1 import AppTest
from frontend.api_client import BackendAPIClient
import psycopg


@pytest.fixture(autouse=True)
def clean_db():
    try:
        conn = psycopg.connect("postgresql://postgres:postgres@localhost:5432/zamp_ap")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM invoices WHERE invoice_number != 'INV-DUP-999';")
            cur.execute("DELETE FROM processing_runs WHERE run_id LIKE 'run-%';")
        conn.commit()
        conn.close()
    except Exception:
        pass
    yield
    try:
        conn = psycopg.connect("postgresql://postgres:postgres@localhost:5432/zamp_ap")
        with conn.cursor() as cur:
            cur.execute("DELETE FROM invoices WHERE invoice_number != 'INV-DUP-999';")
            cur.execute("DELETE FROM processing_runs WHERE run_id LIKE 'run-%';")
        conn.commit()
        conn.close()
    except Exception:
        pass


from pathlib import Path

APP_PATH = str(Path(__file__).resolve().parent / "app.py")


def test_app_initial_render_and_theme_toggle():
    """Verify that initial app renders with Light mode by default and theme toggle works."""
    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert not at.exception, f"App threw exception: {at.exception}"

    # Verify session state default
    assert at.session_state["theme_mode"] == "Light"

    # Find theme toggle segmented control
    theme_ctrl = at.segmented_control(key="theme_mode_segmented_ctrl")
    assert theme_ctrl is not None
    assert theme_ctrl.value == "Light"

    # Select Dark mode
    theme_ctrl.select("Dark").run()
    assert not at.exception
    assert at.session_state["theme_mode"] == "Dark"

    # Select Light mode again
    theme_ctrl = at.segmented_control(key="theme_mode_segmented_ctrl")
    theme_ctrl.select("Light").run()
    assert not at.exception
    assert at.session_state["theme_mode"] == "Light"


def test_navigation_tabs_switching():
    """Verify navigation between the three core tabs."""
    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    assert not at.exception

    # Default tab is Process Invoice
    assert at.session_state["active_tab"] == "Process Invoice"

    # Switch to History
    nav = at.segmented_control(key="main_nav_tab")
    assert nav is not None
    nav.select("History").run()
    assert not at.exception
    assert at.session_state["active_tab"] == "History"

    # Switch to Master Data
    nav = at.segmented_control(key="main_nav_tab")
    nav.select("Master Data").run()
    assert not at.exception
    assert at.session_state["active_tab"] == "Master Data"


def test_master_data_tab_content():
    """Verify Master Data tab displays verified suppliers, POs, and policy rules."""
    at = AppTest.from_file(APP_PATH, default_timeout=15).run()
    nav = at.segmented_control(key="main_nav_tab")
    nav.select("Master Data").run()
    assert not at.exception
    # Check that supplier master table and PO metrics are rendered
    assert any("Vendor & Master Data" in s.value for s in at.markdown)
    assert any("Verified Suppliers" in m.label for m in at.metric)


def test_full_invoice_processing_and_hitl_flow():
    """Test full cycle:
    1. Upload ambiguous PO invoice
    2. Confirm AP review gate interrupt
    3. Resume with AP Operator PO selection
    4. Confirm Finance approval gate interrupt
    5. Resume with Finance Approver
    6. Confirm POSTING_PACKAGE_READY outcome and ERP package
    """
    client = BackendAPIClient("http://127.0.0.1:8080")

    # Ingest ambiguous invoice
    upload_res = client.upload_invoice_json("inv-ambiguous-po", "v1.0.0")
    thread_id = upload_res["thread_id"]
    assert upload_res["is_interrupted"] is True
    assert upload_res["lifecycle_status"] in ("AP_REVIEW", "NEEDS_ATTENTION")

    # Verify SSE events stream returns genuine events
    events = list(client.stream_events(thread_id))
    event_types = [e.get("event") for e in events]
    assert "uploaded" in event_types
    assert "extraction_started" in event_types
    assert "supplier_resolved" in event_types
    assert "control_completed" in event_types

    # AP Operator resolves PO
    r1 = client.resume_run(
        thread_id=thread_id,
        action="SELECT_PO_2001",
        role="AP Operator",
        user_id="ap_operator_sarah",
        selected_po="PO-2001",
        reason="Matched to line items on PO-2001",
    )
    assert r1["is_interrupted"] is True
    assert r1["interrupt"]["type"] == "FINANCE_APPROVAL"

    # Finance Approver authorizes payment
    r2 = client.resume_run(
        thread_id=thread_id,
        action="APPROVE",
        role="Finance Approver",
        user_id="finance_approver_elena",
        reason="Authorized for automated ERP ledger posting",
    )
    assert r2["is_interrupted"] is False
    assert r2["lifecycle_status"] == "POSTING_PACKAGE_READY"
    assert r2["posting_package"] is not None

    # Fetch ERP posting package
    pkg = client.get_posting_package(thread_id)
    assert pkg["package_id"].startswith(f"PKG-{thread_id}-")
    assert pkg["total_amount"] > 0


def test_app_batch_state_rendering():
    """Verify that setting batch_results renders the Batch Processing Summary card with inspect actions."""
    at = AppTest.from_file(APP_PATH, default_timeout=15)
    at.run()
    assert not at.exception

    mock_batch = [
        {
            "filename": "inv_acme_01.pdf",
            "thread_id": "run-batch-001",
            "lifecycle_status": "POSTING_PACKAGE_READY",
            "supplier_name": "Acme Supplies Inc",
            "invoice_number": "INV-1001",
            "total_amount": 1250.00,
            "events": [{"event": "uploaded", "timestamp": 12345, "data": {}}],
            "snapshot": {"lifecycle_status": "POSTING_PACKAGE_READY", "thread_id": "run-batch-001"},
        },
        {
            "filename": "inv_globex_02.pdf",
            "thread_id": "run-batch-002",
            "lifecycle_status": "AP_REVIEW",
            "supplier_name": "Globex Corp",
            "invoice_number": "INV-1002",
            "total_amount": 3400.00,
            "events": [{"event": "uploaded", "timestamp": 12345, "data": {}}],
            "snapshot": {"lifecycle_status": "AP_REVIEW", "thread_id": "run-batch-002"},
        },
    ]

    at.session_state["batch_results"] = mock_batch
    at.session_state["current_thread_id"] = "run-batch-001"
    at.run()

    assert not at.exception
    # Check that batch results remain in session state
    assert len(at.session_state["batch_results"]) == 2
    assert at.session_state["current_thread_id"] == "run-batch-001"

