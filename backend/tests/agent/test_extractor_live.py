"""End-to-End Live Integration Tests for Multimodal LLM Extraction Engine.

Tests:
1. PyMuPDF in-memory rendering and digital text extraction from PDF
2. Raster PNG invoice image extraction
3. Structured outputs via gpt-4o-mini Vision with 100% field precision
4. Integration with run_ap_employee_pipeline using a real PDF invoice file
5. Full LangGraph lifecycle execution from PDF ingestion to Finance Approver sign-off
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from app.agent.extractor import (
    ExtractedInvoiceData,
    extract_invoice_from_document,
    prepare_document_multimodal_payload,
)
from app.agent.invoice_generator import (
    create_sample_invoice_pdf,
    create_sample_invoice_image,
)
from app.agent.main_agent import run_ap_employee_pipeline
from app.agent.graph import create_invoice_graph
from app.agent.observability import get_invoice_tracer, RECORDED_TRACES
from app.agent.llm import is_openai_configured


@pytest.fixture(scope="module")
def sample_pdf_path(tmp_path_factory) -> Path:
    """Generate a clean vector invoice PDF."""
    tmp_dir = tmp_path_factory.mktemp("invoices")
    pdf_path = tmp_dir / "invoice_apex_8801.pdf"
    create_sample_invoice_pdf(pdf_path)
    return pdf_path


@pytest.fixture(scope="module")
def sample_png_path(tmp_path_factory) -> Path:
    """Generate a clean raster invoice PNG image."""
    tmp_dir = tmp_path_factory.mktemp("invoices")
    png_path = tmp_dir / "invoice_apex_8801.png"
    create_sample_invoice_image(png_path)
    return png_path


def test_prepare_document_multimodal_payload_pdf(sample_pdf_path: Path):
    """Verify PyMuPDF renders PDF pages to PNG pixmaps and extracts digital text."""
    parts, digital_text, meta = prepare_document_multimodal_payload(sample_pdf_path)

    assert meta["format"] == "PDF"
    assert meta["total_pages"] == 1
    assert meta["pages_rendered"] == 1
    assert len(parts) >= 2  # 1 text prompt + 1 image_url part
    assert parts[0]["type"] == "text"
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")

    # Vector text layer must be present
    assert "Apex Industrial Supplies LLC" in digital_text
    assert "INV-2026-8801" in digital_text
    assert "PO-9001" in digital_text


def test_prepare_document_multimodal_payload_image(sample_png_path: Path):
    """Verify image payload preparation."""
    parts, digital_text, meta = prepare_document_multimodal_payload(sample_png_path)

    assert meta["format"] == "IMAGE"
    assert meta["pages_rendered"] == 1
    assert len(parts) == 2
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


@pytest.mark.skipif(not is_openai_configured(), reason="OpenAI API key required for live multimodal test")
def test_live_multimodal_extraction_pdf(sample_pdf_path: Path):
    """Verify gpt-4o-mini multimodal extraction from real PDF document."""
    run_id = "test-live-extract-pdf-001"
    tracer = get_invoice_tracer(run_id=run_id, session_id=f"session-{run_id}")

    res = extract_invoice_from_document(sample_pdf_path, run_id=run_id, tracer=tracer)

    assert res["status"] == "SUCCESS"
    assert res["method"] == "multimodal_vision_gpt4o_mini"
    data = res["extracted_data"]

    # Precision field verification
    assert data["invoice_number"] == "INV-2026-8801"
    assert "Apex" in data["supplier_name"]
    assert data["supplier_tax_id"] == "US-XX-9876543"
    assert data["invoice_date"] == "2026-09-20"
    assert data["due_date"] == "2026-10-20"
    assert data["currency"] == "USD"
    assert data["po_number"] == "PO-9001"
    assert data["bank_account_last4"] == "4321"

    # Financial arithmetic
    assert data["subtotal"] == 1200.00
    assert data["tax_amount"] == 96.00
    assert data["total_amount"] == 1296.00
    assert round(data["subtotal"] + data["tax_amount"], 2) == data["total_amount"]

    # Itemized lines
    assert len(data["lines"]) >= 2
    assert any("Valve" in line["description"] for line in data["lines"])


@pytest.mark.skipif(not is_openai_configured(), reason="OpenAI API key required for live multimodal test")
def test_live_pipeline_integration_with_real_pdf(sample_pdf_path: Path):
    """Verify end-to-end AP pipeline executes controls against real PDF invoice."""
    run_id = "test-live-pipeline-pdf"
    tracer = get_invoice_tracer(run_id=run_id, session_id=f"session-{run_id}")

    extracted_invoice, outcome = run_ap_employee_pipeline(
        run_id=run_id,
        invoice_reference=str(sample_pdf_path),
        policy_version="v1.0.0",
        tracer=tracer,
    )

    assert extracted_invoice["invoice_number"] == "INV-2026-8801"
    assert extracted_invoice["total_amount"] == 1296.00

    # Section 14 deterministic validation: all 13 controls must execute and pass
    assert outcome.control_report.completeness_valid is True
    assert outcome.status == "READY_FOR_APPROVAL"
    assert outcome.owner == "Finance Approver"
    assert outcome.human_input_required is True


@pytest.mark.skipif(not is_openai_configured(), reason="OpenAI API key required for live multimodal test")
def test_live_langgraph_flow_with_real_pdf(sample_pdf_path: Path):
    """Verify full LangGraph lifecycle: ingestion -> PDF extraction -> controls -> interrupt -> sign-off."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)
    run_id = "test-live-graph-pdf-001"
    config = {"configurable": {"thread_id": run_id}}

    # 1. Trigger flow with PDF file path
    res = graph.invoke(
        {
            "run_id": run_id,
            "thread_id": run_id,
            "session_id": f"session-{run_id}",
            "invoice_reference": str(sample_pdf_path),
            "lifecycle_status": "START",
            "human_action_history": [],
        },
        config=config,
    )

    state = graph.get_state(config)
    assert state.values["lifecycle_status"] == "READY_FOR_APPROVAL"
    assert state.values["extracted_invoice"]["invoice_number"] == "INV-2026-8801"

    # Verify interrupt occurred at human approval gate
    assert len(state.tasks) > 0
    interrupt_info = state.tasks[0].interrupts[0].value
    assert interrupt_info["type"] == "FINANCE_APPROVAL"
    assert interrupt_info["required_role"] == "Finance Approver"


    # 2. Resume with authorized Finance Approver
    final_res = graph.invoke(
        Command(resume={
            "action": "APPROVE",
            "role": "Finance Approver",
            "user_id": "sarah_cfo",
            "decision_revision": 1,
        }),
        config=config,
    )

    assert final_res["lifecycle_status"] in ("POSTING_PACKAGE_READY", "APPROVED")
    assert "posting_package" in final_res
    assert final_res["posting_package"]["package_id"].startswith("PKG-test-live-graph-pdf-001")
    assert final_res["posting_package"]["total_amount"] == 1296.00

