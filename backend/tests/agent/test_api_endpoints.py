"""Integration tests for FastAPI endpoints with PostgresSaver and Human-in-the-Loop workflows."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.agent.invoice_generator import create_sample_invoice_pdf


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def sample_pdf_path(tmp_path_factory):
    pdf_dir = tmp_path_factory.mktemp("pdf_test")
    pdf_path = pdf_dir / "test_api_invoice.pdf"
    create_sample_invoice_pdf(pdf_path)
    return pdf_path


def test_api_health_endpoint(client):
    """Verify health endpoint reports PostgreSQL and FastMCP connection."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("healthy", "degraded")
    assert "database" in data
    assert "checkpointer" in data


def test_ambiguous_po_upload_and_full_resume_flow(client):
    """Test full interactive cycle via FastAPI endpoints:
    1. Upload ambiguous PO invoice -> Returns 200 with AP_REVIEW interrupt
    2. Check status endpoint -> Confirms state persisted in PostgresSaver
    3. Resume with AP Operator -> Advances to FINANCE_APPROVAL interrupt
    4. Attempt resume with unauthorized role -> Returns 403 Forbidden
    5. Resume with Finance Approver -> Returns 200 with APPROVED status and posting package
    """
    # 1. Ingest ambiguous invoice
    upload_res = client.post(
        "/api/invoices/upload-json",
        json={"invoice_reference": "inv-ambiguous-po", "workflow_version": "v1.0.0"},
    )
    assert upload_res.status_code == 200
    body = upload_res.json()
    thread_id = body["thread_id"]
    assert thread_id.startswith("run-")
    assert body["is_interrupted"] is True
    assert body["interrupt"]["type"] == "AP_REVIEW"
    assert "Which PO should be applied?" in body["interrupt"]["question"]
    assert "SELECT_PO_2001" in body["interrupt"]["allowed_actions"]

    # 2. Verify status endpoint reads directly from PostgresSaver
    status_res = client.get(f"/api/invoices/{thread_id}/status")
    assert status_res.status_code == 200
    assert status_res.json()["thread_id"] == thread_id
    assert status_res.json()["is_interrupted"] is True

    # 3. Resume with AP Operator: Select PO-2001
    operator_payload = {
        "action": "SELECT_PO_2001",
        "role": "AP Operator",
        "user_id": "bob_operator",
        "selected_po": "PO-2001",
        "decision_revision": 1,
    }
    resume_1_res = client.post(f"/api/invoices/{thread_id}/resume", json=operator_payload)
    assert resume_1_res.status_code == 200
    r1_body = resume_1_res.json()
    assert r1_body["is_interrupted"] is True
    assert r1_body["interrupt"]["type"] == "FINANCE_APPROVAL"
    assert r1_body["interrupt"]["required_role"] == "Finance Approver"

    # 4. Unauthorized role attempt (AP Operator tries to sign off for Finance)
    unauth_payload = {
        "action": "APPROVE",
        "role": "AP Operator",  # Unauthorized!
        "user_id": "charlie_operator",
        "decision_revision": 1,
    }
    unauth_res = client.post(f"/api/invoices/{thread_id}/resume", json=unauth_payload)
    assert unauth_res.status_code == 403
    assert "cannot authorize invoice approval" in unauth_res.json()["detail"]

    # 5. Authorized Finance Approver signs off
    finance_payload = {
        "action": "APPROVE",
        "role": "Finance Approver",
        "user_id": "sarah_cfo",
        "decision_revision": 1,
    }
    resume_2_res = client.post(f"/api/invoices/{thread_id}/resume", json=finance_payload)
    assert resume_2_res.status_code == 200
    r2_body = resume_2_res.json()
    assert r2_body["is_interrupted"] is False
    assert r2_body["lifecycle_status"] in ("POSTING_PACKAGE_READY", "APPROVED")
    assert r2_body["posting_package"] is not None
    assert r2_body["posting_package"]["package_id"].startswith(f"PKG-{thread_id}-")


def test_upload_multipart_pdf_document(client, sample_pdf_path):
    """Test uploading a real PDF file via multipart/form-data."""
    with open(sample_pdf_path, "rb") as f:
        response = client.post(
            "/api/invoices/upload",
            files={"file": ("test_invoice.pdf", f, "application/pdf")},
            data={"workflow_version": "v1.0.0"},
        )
    assert response.status_code == 200
    data = response.json()
    assert "thread_id" in data
    assert data["lifecycle_status"] in ("READY_FOR_APPROVAL", "NEEDS_ATTENTION", "BLOCKED")


def test_list_invoices_endpoint(client):
    """Verify listing historical invoice runs from PostgreSQL."""
    response = client.get("/api/invoices")
    assert response.status_code == 200
    data = response.json()
    assert "runs" in data
    assert "count" in data


def test_events_sse_stream_endpoint(client):
    """Verify GET /api/invoices/{thread_id}/events returns text/event-stream with canonical events."""
    # Ingest run to generate events
    upload_res = client.post(
        "/api/invoices/upload-json",
        json={"invoice_reference": "inv-ambiguous-po", "workflow_version": "v1.0.0"},
    )
    assert upload_res.status_code == 200
    thread_id = upload_res.json()["thread_id"]

    # Stream events
    res = client.get(f"/api/invoices/{thread_id}/events")
    assert res.status_code == 200
    assert "text/event-stream" in res.headers["content-type"]
    text = res.text
    assert "uploaded" in text
    assert "extraction_started" in text
    assert "supplier_resolved" in text
    assert "control_completed" in text


def test_posting_package_endpoint(client):
    """Verify GET /api/invoices/{thread_id}/posting-package retrieves ERP package."""
    # 1. Ingest ambiguous invoice and advance through both gates to POSTING_PACKAGE_READY
    upload_res = client.post(
        "/api/invoices/upload-json",
        json={"invoice_reference": "inv-ambiguous-po", "workflow_version": "v1.0.0"},
    )
    thread_id = upload_res.json()["thread_id"]

    # Before approval, posting package should return 404
    pkg_early = client.get(f"/api/invoices/{thread_id}/posting-package")
    assert pkg_early.status_code == 404

    # AP Operator resolves PO
    client.post(
        f"/api/invoices/{thread_id}/resume",
        json={
            "action": "SELECT_PO_2001",
            "role": "AP Operator",
            "user_id": "operator_test",
            "selected_po": "PO-2001",
            "decision_revision": 1,
        },
    )

    # Finance Approver signs off
    client.post(
        f"/api/invoices/{thread_id}/resume",
        json={
            "action": "APPROVE",
            "role": "Finance Approver",
            "user_id": "approver_test",
            "decision_revision": 1,
        },
    )

    # Now posting package must return 200 with ERP ledger payload
    pkg_res = client.get(f"/api/invoices/{thread_id}/posting-package")
    assert pkg_res.status_code == 200
    pkg_body = pkg_res.json()
    assert pkg_body["package_id"].startswith(f"PKG-{thread_id}-")
    assert pkg_body["total_amount"] > 0

