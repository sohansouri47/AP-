"""Tests for APPolicy, PolicyManager, dynamic threshold enforcement, and version rollback."""

import pytest
from app.agent.policy import (
    APPolicy,
    PolicyManager,
    DEFAULT_POLICY_V1,
    get_active_policy,
    activate_policy,
    rollback_policy,
    global_policy_manager,
)
from app.agent.mcp_tools import (
    check_arithmetic,
    check_dates_currency,
    select_approval_route,
    activate_workflow_version,
    rollback_workflow_version,
)


def test_default_policy_baseline():
    """Verify default policy parameters and mandatory check assignments."""
    policy = DEFAULT_POLICY_V1
    assert policy.version == "v1.0.0"
    assert "USD" in policy.allowed_currencies
    assert "EUR" in policy.allowed_currencies
    assert policy.arithmetic_tolerance == 0.01
    assert policy.finance_director_threshold == 10000.00
    assert "CHK_FILE_DUP" in policy.mandatory_check_ids
    assert "CHK_ARITHMETIC" in policy.mandatory_check_ids
    assert len(policy.mandatory_check_ids) == 12


def test_policy_staging_and_activation():
    """Verify candidate policy staging, diff application, and admin activation."""
    mgr = PolicyManager()
    assert mgr.active_policy.version == "v1.0.0"

    # Stage candidate with SKU mapping
    candidate = mgr.stage_candidate_policy(
        candidate_version="v1.1.0",
        diff_payload={"vendor": "SUPP-001", "sku_map": {"WIDGET-X": 10}},
        target_type="PO_LINE_MAPPING",
    )
    assert candidate.version == "v1.1.0"
    assert candidate.vendor_sku_mappings["SUPP-001"]["WIDGET-X"] == 10
    # Active policy remains v1.0.0 until activated
    assert mgr.active_policy.version == "v1.0.0"

    # Activation requires administrator ID
    with pytest.raises(ValueError, match="Named Workflow Administrator ID is required"):
        mgr.activate_policy("v1.1.0", administrator_id="")

    activated = mgr.activate_policy("v1.1.0", administrator_id="admin_john")
    assert activated.version == "v1.1.0"
    assert mgr.active_policy.version == "v1.1.0"
    assert mgr.rollback_version == "v1.0.0"
    assert mgr.active_policy.vendor_sku_mappings["SUPP-001"]["WIDGET-X"] == 10


def test_policy_rollback():
    """Verify rollback restores previous active policy."""
    mgr = PolicyManager()
    mgr.stage_candidate_policy(
        candidate_version="v1.1.0",
        diff_payload={"vendor": "SUPP-001", "sku_map": {"ITEM-A": 1}},
        target_type="PO_LINE_MAPPING",
    )
    mgr.activate_policy("v1.1.0", administrator_id="admin_john")
    assert mgr.active_policy.version == "v1.1.0"

    # Roll back to v1.0.0
    reverted = mgr.rollback_policy("v1.0.0", administrator_id="admin_john")
    assert reverted.version == "v1.0.0"
    assert mgr.active_policy.version == "v1.0.0"
    assert "SUPP-001" not in mgr.active_policy.vendor_sku_mappings

    # Rollback to non-existent version raises KeyError
    with pytest.raises(KeyError, match="Historical policy version 'v99.0.0' not found"):
        mgr.rollback_policy("v99.0.0", administrator_id="admin_john")


def test_dynamic_policy_enforcement_in_mcp_tools():
    """Verify that updating active policy immediately adapts MCP tool decisions without code change."""
    # Ensure active policy is baseline
    global_policy_manager.rollback_policy("v1.0.0", administrator_id="admin_setup") if "v1.0.0" in global_policy_manager._history else None
    
    # Under v1.0.0, CAD is allowed, JPY is not
    res_cad = check_dates_currency(invoice_date="2026-03-01", currency="CAD")
    assert res_cad["status"] == "PASSED"

    res_jpy = check_dates_currency(invoice_date="2026-03-01", currency="JPY")
    assert res_jpy["status"] == "FAILED"
    assert res_jpy["error_code"] == "UNSUPPORTED_CURRENCY"

    # Stage and activate v1.2.0 policy with JPY authorized and arithmetic tolerance $0.05
    staged = global_policy_manager.stage_candidate_policy(
        candidate_version="v1.2.0",
        diff_payload={},
        target_type="TOLERANCE_ADJUSTMENT",
    )
    staged.allowed_currencies.add("JPY")
    staged.arithmetic_tolerance = 0.05
    staged.finance_director_threshold = 25000.00
    
    activate_workflow_version("v1.2.0", administrator_id="admin_lead")
    assert get_active_policy().version == "v1.2.0"

    # Now JPY is authorized
    res_jpy_new = check_dates_currency(invoice_date="2026-03-01", currency="JPY")
    assert res_jpy_new["status"] == "PASSED"

    # Diff of $0.03 now passes under $0.05 tolerance
    res_math = check_arithmetic(subtotal=100.00, tax_amount=10.00, total_amount=110.03)
    assert res_math["status"] == "PASSED"

    # $15,000 invoice now routes to Finance Approver (threshold was raised to $25,000)
    res_route = select_approval_route(invoice_amount=15000.00)
    assert res_route["raw_output"]["required_role"] == "Finance Approver"

    # Rollback to v1.0.0 restores original rules
    rollback_workflow_version("v1.0.0", administrator_id="admin_lead")
    assert get_active_policy().version == "v1.0.0"

    res_jpy_reverted = check_dates_currency(invoice_date="2026-03-01", currency="JPY")
    assert res_jpy_reverted["status"] == "FAILED"
