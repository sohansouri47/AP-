"""Tests for AP control completeness validation and mandatory-check protection."""

import pytest
from app.agent.schemas import CheckResult
from app.agent.mcp_tools import (
    global_check_registry,
    validate_check_completeness,
    select_final_decision,
)
from app.agent.main_agent import run_ap_employee_pipeline


def test_missing_mandatory_check_fails_completeness():
    """Verify that omitting a mandatory check causes validate_check_completeness to return valid=False."""
    required = ["CHK_FILE_DUP", "CHK_SUPPLIER_RES", "CHK_BIZ_DUP", "CHK_ARITHMETIC"]
    completed = ["CHK_FILE_DUP", "CHK_SUPPLIER_RES"]  # Omitted CHK_BIZ_DUP and CHK_ARITHMETIC

    result = validate_check_completeness(
        required_check_ids=required,
        completed_check_ids=completed,
        check_results=[],
        registry_version="v1.0.0",
    )

    assert result["valid"] is False
    assert result["reason_code"] == "REQUIRED_CHECK_MISSING"
    assert "CHK_BIZ_DUP" in result["missing_checks"]
    assert "CHK_ARITHMETIC" in result["missing_checks"]


def test_select_final_decision_rejects_incomplete_checks():
    """Verify select_final_decision rejects execution when completeness is invalid."""
    with pytest.raises(ValueError, match="completeness validation failed"):
        select_final_decision(
            check_results=[{"check_id": "CHK_FILE_DUP", "status": "PASSED"}],
            registry_version="v1.0.0",
            completeness_valid=False,
        )


def test_pipeline_converts_missing_checks_to_failed():
    """Verify that a pipeline run with skipped checks results in FAILED status, never READY_FOR_APPROVAL."""
    extracted_inv, outcome = run_ap_employee_pipeline(
        run_id="run-incomplete-1",
        invoice_reference="inv-happy-001",
        force_skip_checks=["CHK_BIZ_DUP"],
    )

    assert outcome.status == "FAILED"
    assert outcome.control_report.completeness_valid is False
    assert "CHK_BIZ_DUP" in outcome.control_report.missing_checks
    assert "Missing checks: CHK_BIZ_DUP" in outcome.explanation
