"""Tests for Langfuse observability, nesting, safe redaction, and graceful degradation."""

import os
from unittest.mock import patch
import pytest

from app.agent.main_agent import run_ap_employee_pipeline
from app.agent.observability import (
    TraceObserver,
    mask_sensitive_data,
    get_invoice_tracer,
)


def test_parent_trace_nests_subagents_and_tools():
    """Verify trace records parent node execution, subagent delegations, and MCP tool calls."""
    run_id = "test-trace-nesting-1"
    tracer = get_invoice_tracer(run_id)

    run_ap_employee_pipeline(
        run_id=run_id,
        invoice_reference="inv-happy-001",
        tracer=tracer,
    )

    event_types = {e["type"] for e in tracer.events}
    assert "SUBAGENT_DELEGATION" in event_types
    assert "MCP_TOOL_CALL" in event_types
    assert "FINAL_DECISION" in event_types

    # Verify session ID correlation
    assert all(e["session_id"] == run_id for e in tracer.events)


def test_sensitive_data_redaction():
    """Verify sensitive invoice data (PDF bytes, full OCR, secrets, bank numbers) are redacted."""
    raw_payload = {
        "invoice_id": "INV-100",
        "pdf_bytes": b"%PDF-1.4 simulated binary data",
        "ocr_full_text": "Complete OCR dump with raw text",
        "bank_account_number": "1234567890",
        "api_key": "sk-secret-12345",
        "public_field": "Acme Corp",
    }

    masked = mask_sensitive_data(raw_payload)

    assert masked["public_field"] == "Acme Corp"
    assert masked["pdf_bytes"] == "[REDACTED]"
    assert masked["ocr_full_text"] == "[REDACTED]"
    assert masked["bank_account_number"] == "[REDACTED]"
    assert masked["api_key"] == "[REDACTED]"


def test_execution_succeeds_when_langfuse_disabled(monkeypatch):
    """Verify system runs smoothly when Langfuse environment variables are unset."""
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

    tracer = TraceObserver(trace_name="test-disabled", session_id="run-disabled-1")
    assert tracer._langfuse_client is None

    extracted_inv, outcome = run_ap_employee_pipeline(
        run_id="run-disabled-1",
        invoice_reference="inv-happy-001",
        tracer=tracer,
    )

    assert outcome.status == "READY_FOR_APPROVAL"


def test_execution_succeeds_when_langfuse_throws_exception():
    """Verify Langfuse errors or network timeouts degrade gracefully without failing workflow."""
    tracer = TraceObserver(trace_name="test-err", session_id="run-err-1")

    # Mock client flush that throws an exception
    class FlakyClient:
        def flush(self):
            raise ConnectionError("Langfuse cloud unreachable")

    tracer._langfuse_client = FlakyClient()

    # Flush should catch the error and log warning without raising
    tracer.flush()
