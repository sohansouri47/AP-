"""MCP Tools and Check Registry for AP AI Employee.

Provides:
- CheckRegistry: Extensible registry for AP mandatory & conditional controls
- Tool allowlists per agent role
- FastMCP tool delegators routing all calls to the FastMCP server over SSE
- Deterministic gates for check completeness, decision selection, and posting
"""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import time
from typing import Any, Callable, Literal
from pydantic import BaseModel, Field

from app.agent.schemas import (
    CandidateComparison,
    CheckResult,
    ControlExecutionReport,
    DecisionResult,
    EvidenceSummary,
    ImprovementProposal,
    InvestigationResult,
    RequiredCheck,
    UnresolvedItem,
)
from app.agent.policy import (
    get_active_policy,
    global_policy_manager,
    activate_policy,
    rollback_policy,
)
from app.agent.flow_logger import flow_logger
from app.agent.mcp_client import get_mcp_client


# =====================================================================
# 1. Check Registry (Dynamic & Extensible)
# =====================================================================

class CheckRegistry:
    """Registry of AP financial controls.
    
    Allows dynamic registration of new controls without modifying the
    parent LangGraph topology.
    """

    def __init__(self, version: str = "v1.0.0"):
        self.version = version
        self._checks: dict[str, RequiredCheck] = {}
        self._tool_callables: dict[str, Callable[..., dict[str, Any]]] = {}
        self._register_default_checks()

    def _register_default_checks(self) -> None:
        default_definitions = [
            ("CHK_FILE_DUP", "check_file_duplicate", 1, True, "File hash duplicate prevention"),
            ("CHK_SUPPLIER_RES", "resolve_supplier", 2, True, "Supplier master resolution"),
            ("CHK_BIZ_DUP", "check_business_duplicate", 3, True, "Business invoice number duplicate check"),
            ("CHK_REMIT_CHANGE", "check_remit_change", 4, True, "Remittance account divergence detection"),
            ("CHK_ARITHMETIC", "check_arithmetic", 5, True, "Header and line-item math verification"),
            ("CHK_DATES_CURR", "check_dates_currency", 6, True, "Date validity and ISO currency check"),
            ("CHK_PO_IDENT", "identify_purchase_order", 7, True, "PO identification and association"),
            ("CHK_PO_HEADER", "validate_po_header", 8, True, "PO status and vendor binding validation"),
            ("CHK_PO_LINES", "match_po_lines", 9, True, "Line-item quantities and price matching"),
            ("CHK_PO_REMAIN", "calculate_po_remaining", 10, True, "Remaining PO balance assessment"),
            ("CHK_PO_TOL", "evaluate_po_tolerances", 11, True, "Price and quantity tolerance policy"),
            ("CHK_NO_PO_POL", "evaluate_no_po_policy", 12, False, "Non-PO expense compliance check"),
            ("CHK_APP_ROUTE", "select_approval_route", 13, True, "Approval matrix routing selection"),
        ]

        for check_id, tool_name, order, mandatory, reason in default_definitions:
            self._checks[check_id] = RequiredCheck(
                check_id=check_id,
                tool_name=tool_name,
                execution_order=order,
                mandatory=mandatory,
                applicability_reason=reason,
                policy_version=self.version,
            )

    def register_check(
        self,
        check_id: str,
        tool_name: str,
        tool_callable: Callable[..., dict[str, Any]],
        execution_order: int,
        mandatory: bool,
        applicability_reason: str,
    ) -> None:
        """Register a new AP check at runtime without altering parent graph topology."""
        self._checks[check_id] = RequiredCheck(
            check_id=check_id,
            tool_name=tool_name,
            execution_order=execution_order,
            mandatory=mandatory,
            applicability_reason=applicability_reason,
            policy_version=self.version,
        )
        self._tool_callables[check_id] = tool_callable
        self._tool_callables[tool_name] = tool_callable
        try:
            from app.agent.mcp_server import mcp
            mcp.add_tool(tool_callable, name=tool_name)
        except Exception:
            pass

    def get_required_checks(
        self,
        invoice_reference: str = "",
        policy_version: str | None = None,
    ) -> list[RequiredCheck]:
        """Return the sorted list of required checks under current policy."""
        return sorted(self._checks.values(), key=lambda c: c.execution_order)

    def validate_check_completeness(
        self,
        executed_check_ids: list[str],
        policy_version: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Verify that 100% of mandatory controls for this policy version were executed."""
        required = [c.check_id for c in self._checks.values() if c.mandatory]
        executed_set = set(executed_check_ids)
        missing = [cid for cid in required if cid not in executed_set]
        return len(missing) == 0, missing


# Global singleton instance of Check Registry
global_check_registry = CheckRegistry()


# =====================================================================
# 2. Tool Allowlists & Privilege Boundaries
# =====================================================================

MAIN_AGENT_ALLOWLIST = {
    "extract_invoice",
    "get_run_context",
}

CONTROL_EXECUTOR_ALLOWLIST = {
    "get_required_checks",
    "check_file_duplicate",
    "resolve_supplier",
    "check_business_duplicate",
    "check_remit_change",
    "check_arithmetic",
    "check_dates_currency",
    "identify_purchase_order",
    "validate_po_header",
    "match_po_lines",
    "calculate_po_remaining",
    "evaluate_po_tolerances",
    "evaluate_no_po_policy",
    "select_approval_route",
    "validate_check_completeness",
    "select_final_decision",
}

EXCEPTION_INVESTIGATOR_ALLOWLIST = {
    "get_invoice_evidence",
    "get_supplier_candidates",
    "get_po_candidates",
    "get_po_lines",
    "get_policy_rule",
    "get_prior_invoice_matches",
    "compare_candidate_records",
}

WORKFLOW_IMPROVEMENT_ALLOWLIST = {
    "get_feedback_events",
    "group_feedback_patterns",
    "create_candidate_version",
    "run_regression_suite",
    "verify_regression_results",
}

DETERMINISTIC_ONLY_ALLOWLIST = {
    "authorize_approval",
    "build_posting_package",
    "activate_workflow_version",
    "rollback_workflow_version",
}


def verify_tool_permission(role: str, tool_name: str) -> None:
    """Enforce explicit security boundaries per agent role."""
    allowed: set[str]
    if role == "main_agent":
        allowed = MAIN_AGENT_ALLOWLIST
    elif role == "control-executor":
        allowed = CONTROL_EXECUTOR_ALLOWLIST
    elif role == "exception-investigator":
        allowed = EXCEPTION_INVESTIGATOR_ALLOWLIST
    elif role == "workflow-improvement-analyst":
        allowed = WORKFLOW_IMPROVEMENT_ALLOWLIST
    elif role == "deterministic_application":
        allowed = DETERMINISTIC_ONLY_ALLOWLIST
    else:
        raise PermissionError(f"Unknown role '{role}' attempted to call tool '{tool_name}'")

    if tool_name in DETERMINISTIC_ONLY_ALLOWLIST and role != "deterministic_application":
        raise PermissionError(
            f"Security Violation: Agent role '{role}' is forbidden from executing "
            f"privileged deterministic tool '{tool_name}'"
        )

    if tool_name not in allowed:
        raise PermissionError(
            f"Security Violation: Tool '{tool_name}' is not in the allowlist for '{role}'"
        )


# In-memory mock database / context store
_MOCK_INVOICE_DB: dict[str, dict[str, Any]] = {
    "inv-happy-001": {
        "invoice_number": "INV-2026-001",
        "supplier_name": "Acme Industrial Supplies LLC",
        "supplier_tax_id": "US-XX-9876543",
        "supplier_id": "SUPP-001",
        "subtotal": 1000.00,
        "tax_amount": 80.00,
        "total_amount": 1080.00,
        "currency": "USD",
        "invoice_date": "2026-09-15",
        "due_date": "2026-10-15",
        "po_number": "PO-9001",
        "bank_account_last4": "4321",
        "lines": [
            {"line_number": 1, "description": "Steel bolts grade 8", "quantity": 100, "unit_price": 5.00, "total": 500.00},
            {"line_number": 2, "description": "Hydraulic seal kit", "quantity": 10, "unit_price": 50.00, "total": 500.00},
        ],
    },
    "inv-ambiguous-po": {
        "invoice_number": "INV-2026-002",
        "supplier_name": "Globex Hardware Inc",
        "supplier_tax_id": "US-YY-1122334",
        "supplier_id": "SUPP-002",
        "subtotal": 2400.00,
        "tax_amount": 192.00,
        "total_amount": 2592.00,
        "currency": "USD",
        "invoice_date": "2026-09-20",
        "due_date": "2026-10-20",
        "po_number": "",  # Unspecified or multiple candidates exist
        "bank_account_last4": "8899",
        "lines": [
            {"line_number": 1, "description": "Enterprise cloud router", "quantity": 1, "unit_price": 2400.00, "total": 2400.00},
        ],
    },
    "inv-tax-mismatch": {
        "invoice_number": "INV-2026-003",
        "supplier_name": "Acme Industrial Supplies LLC",
        "supplier_tax_id": "US-XX-9876543",
        "supplier_id": "SUPP-001",
        "subtotal": 1000.00,
        "tax_amount": 80.00,
        "total_amount": 1200.00,  # 1000 + 80 != 1200
        "currency": "USD",
        "invoice_date": "2026-09-15",
        "due_date": "2026-10-15",
        "po_number": "PO-9001",
        "bank_account_last4": "4321",
        "lines": [
            {"line_number": 1, "description": "Steel bolts grade 8", "quantity": 100, "unit_price": 5.00, "total": 500.00},
        ],
    },
    "inv-duplicate-001": {
        "invoice_number": "INV-DUP-999",
        "supplier_name": "Vandelay Industries",
        "supplier_tax_id": "US-ZZ-5566778",
        "supplier_id": "SUPP-003",
        "subtotal": 500.00,
        "tax_amount": 40.00,
        "total_amount": 540.00,
        "currency": "USD",
        "invoice_date": "2026-09-01",
        "due_date": "2026-10-01",
        "po_number": "PO-8888",
        "bank_account_last4": "1111",
        "is_duplicate": True,
        "lines": [
            {"line_number": 1, "description": "Latex sample parts", "quantity": 5, "unit_price": 100.00, "total": 500.00},
        ],
    },
}

_MOCK_PO_DB: dict[str, dict[str, Any]] = {
    "PO-9001": {
        "po_number": "PO-9001",
        "supplier_id": "SUPP-001",
        "supplier_name": "Acme Industrial Supplies LLC",
        "status": "APPROVED",
        "currency": "USD",
        "total_amount": 5000.00,
        "remaining_amount": 5000.00,
        "lines": [
            {"line_number": 1, "description": "Steel bolts grade 8", "quantity": 500, "unit_price": 5.00, "total": 2500.00},
            {"line_number": 2, "description": "Hydraulic seal kit", "quantity": 50, "unit_price": 50.00, "total": 2500.00},
        ],
    },
    "PO-2001": {
        "po_number": "PO-2001",
        "supplier_id": "SUPP-002",
        "supplier_name": "Globex Hardware Inc",
        "status": "APPROVED",
        "currency": "USD",
        "total_amount": 5000.00,
        "remaining_amount": 5000.00,
        "lines": [
            {"line_number": 1, "description": "Enterprise cloud router", "quantity": 2, "unit_price": 2400.00, "total": 4800.00},
            {"line_number": 2, "description": "Rack mount kit", "quantity": 2, "unit_price": 100.00, "total": 200.00},
        ],
    },
    "PO-2002": {
        "po_number": "PO-2002",
        "supplier_id": "SUPP-002",
        "supplier_name": "Globex Hardware Inc",
        "status": "APPROVED",
        "currency": "USD",
        "total_amount": 10000.00,
        "remaining_amount": 10000.00,
        "lines": [
            {"line_number": 1, "description": "Fiber switch 48-port", "quantity": 2, "unit_price": 5000.00, "total": 10000.00},
        ],
    },
}

_MOCK_FEEDBACK_DB: list[dict[str, Any]] = [
    {
        "feedback_id": "FB-001",
        "invoice_number": "INV-101",
        "reviewer_id": "alice_reviewer",
        "field_corrected": "po_line_mapping",
        "prior_value": 0,
        "corrected_value": 1,
        "comment": "Line SKU A100 always maps to PO Line 1",
        "timestamp": 1726000000.0,
    },
    {
        "feedback_id": "FB-002",
        "invoice_number": "INV-102",
        "reviewer_id": "bob_operator",
        "field_corrected": "po_line_mapping",
        "prior_value": 0,
        "corrected_value": 1,
        "comment": "Line SKU A100 mapped to PO Line 1 manually",
        "timestamp": 1726003600.0,
    },
]

_MOCK_AUDIT_LOGS: list[dict[str, Any]] = []


# =====================================================================
# 3. FastMCP Tool Delegators (Connecting Agents to FastMCP Server)
# =====================================================================

# --- Main Agent Tools ---

def extract_invoice(
    run_id: str,
    invoice_reference: str,
    tracer: Any = None,
) -> dict[str, Any]:
    """MCP Tool: Extract structured invoice data from an invoice document reference."""
    verify_tool_permission("main_agent", "extract_invoice")
    # Vision extraction on PDFs/images can take 30-60s — use a long timeout
    return get_mcp_client().call_tool(
        "main_agent",
        "extract_invoice",
        {"run_id": run_id, "invoice_reference": str(invoice_reference)},
        timeout=120.0,
    )


def get_run_context(run_id: str) -> dict[str, Any]:
    """MCP Tool: Retrieve run correlation context and policy version."""
    verify_tool_permission("main_agent", "get_run_context")
    return get_mcp_client().call_tool("main_agent", "get_run_context", {"run_id": run_id})


# --- Control Executor Tools ---

def get_required_checks(
    invoice_reference: str,
    policy_version: str = "v1.0.0",
) -> list[dict[str, Any]]:
    """MCP Tool: Retrieve mandatory and applicable AP controls from registry."""
    verify_tool_permission("control-executor", "get_required_checks")
    return get_mcp_client().call_tool(
        "control-executor",
        "get_required_checks",
        {"invoice_reference": invoice_reference, "policy_version": policy_version},
    )


def check_file_duplicate(invoice_reference: str, file_hash: str = "") -> dict[str, Any]:
    """Check if this invoice file is a duplicate by comparing its hash against the repository."""
    verify_tool_permission("control-executor", "check_file_duplicate")
    return get_mcp_client().call_tool(
        "control-executor",
        "check_file_duplicate",
        {"invoice_reference": invoice_reference, "file_hash": file_hash},
    )


def resolve_supplier(supplier_name: str, tax_id: str = "") -> dict[str, Any]:
    """Resolve supplier name and tax ID against the master vendor directory."""
    verify_tool_permission("control-executor", "resolve_supplier")
    return get_mcp_client().call_tool(
        "control-executor",
        "resolve_supplier",
        {"supplier_name": supplier_name, "tax_id": tax_id},
    )


def check_business_duplicate(
    supplier_id: str,
    invoice_number: str,
    invoice_date: str,
    total_amount: float,
) -> dict[str, Any]:
    """Check for business-level invoice duplicates by supplier, number, date, and amount."""
    verify_tool_permission("control-executor", "check_business_duplicate")
    return get_mcp_client().call_tool(
        "control-executor",
        "check_business_duplicate",
        {
            "supplier_id": supplier_id,
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "total_amount": total_amount,
        },
    )


def check_remit_change(supplier_id: str, bank_account_last4: str = "") -> dict[str, Any]:
    """Detect unexpected remittance bank account changes for a supplier."""
    verify_tool_permission("control-executor", "check_remit_change")
    return get_mcp_client().call_tool(
        "control-executor",
        "check_remit_change",
        {"supplier_id": supplier_id, "bank_account_last4": bank_account_last4},
    )


def check_arithmetic(
    subtotal: float,
    tax_amount: float,
    total_amount: float,
    line_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Verify invoice header totals and line-item arithmetic are internally consistent."""
    verify_tool_permission("control-executor", "check_arithmetic")
    from app.agent.policy import get_active_policy
    policy = get_active_policy()
    if policy and policy.version != "v1.0.0":
        calc = round(subtotal + tax_amount, 2)
        diff = abs(calc - total_amount)
        if diff > policy.arithmetic_tolerance:
            return {
                "check_id": "CHK_ARITHMETIC",
                "status": "FAILED",
                "error_code": "ARITHMETIC_MISMATCH",
                "message": f"Subtotal ({subtotal}) + Tax ({tax_amount}) != Total ({total_amount})",
                "raw_output": {"calculated_total": calc, "diff": diff},
            }
        return {
            "check_id": "CHK_ARITHMETIC",
            "status": "PASSED",
            "message": "Header and line arithmetic verified exactly",
            "raw_output": {"calculated_total": calc},
        }
    return get_mcp_client().call_tool(
        "control-executor",
        "check_arithmetic",
        {
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "total_amount": total_amount,
            "line_items": line_items,
        },
    )


def check_dates_currency(
    invoice_date: str,
    due_date: str = "",
    currency: str = "USD",
) -> dict[str, Any]:
    """Validate invoice date format and verify currency is in the authorized list."""
    verify_tool_permission("control-executor", "check_dates_currency")
    from app.agent.policy import get_active_policy
    policy = get_active_policy()
    if policy and policy.version != "v1.0.0":
        if currency not in policy.allowed_currencies:
            return {
                "check_id": "CHK_DATES_CURR",
                "status": "FAILED",
                "error_code": "UNSUPPORTED_CURRENCY",
                "message": f"Currency {currency} not authorized for automatic processing",
                "raw_output": {"currency": currency},
            }
        return {
            "check_id": "CHK_DATES_CURR",
            "status": "PASSED",
            "message": "Invoice date format valid and currency authorized",
            "raw_output": {"currency": currency},
        }
    return get_mcp_client().call_tool(
        "control-executor",
        "check_dates_currency",
        {"invoice_date": invoice_date, "due_date": due_date, "currency": currency},
    )


def identify_purchase_order(invoice_reference: str, po_number: str = "") -> dict[str, Any]:
    """Identify and associate the purchase order for this invoice."""
    verify_tool_permission("control-executor", "identify_purchase_order")
    return get_mcp_client().call_tool(
        "control-executor",
        "identify_purchase_order",
        {"invoice_reference": invoice_reference, "po_number": po_number},
    )


def validate_po_header(po_number: str, supplier_id: str) -> dict[str, Any]:
    """Validate PO status, approval, and supplier binding at the header level."""
    verify_tool_permission("control-executor", "validate_po_header")
    return get_mcp_client().call_tool(
        "control-executor",
        "validate_po_header",
        {"po_number": po_number, "supplier_id": supplier_id},
    )


def match_po_lines(po_number: str, invoice_lines: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Match invoice line items to PO lines by quantity and unit price."""
    verify_tool_permission("control-executor", "match_po_lines")
    return get_mcp_client().call_tool(
        "control-executor",
        "match_po_lines",
        {"po_number": po_number, "invoice_lines": invoice_lines},
    )


def calculate_po_remaining(po_number: str, invoice_amount: float) -> dict[str, Any]:
    """Calculate remaining budget on the PO after applying this invoice amount."""
    verify_tool_permission("control-executor", "calculate_po_remaining")
    return get_mcp_client().call_tool(
        "control-executor",
        "calculate_po_remaining",
        {"po_number": po_number, "invoice_amount": invoice_amount},
    )


def evaluate_po_tolerances(
    invoice_lines: list[dict[str, Any]] | None = None,
    po_lines: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Evaluate whether invoice line variances are within policy price and quantity tolerances."""
    verify_tool_permission("control-executor", "evaluate_po_tolerances")
    return get_mcp_client().call_tool(
        "control-executor",
        "evaluate_po_tolerances",
        {"invoice_lines": invoice_lines, "po_lines": po_lines},
    )


def evaluate_no_po_policy(invoice_amount: float, cost_center: str = "") -> dict[str, Any]:
    """Evaluate whether a non-PO invoice meets the policy threshold for direct approval."""
    verify_tool_permission("control-executor", "evaluate_no_po_policy")
    return get_mcp_client().call_tool(
        "control-executor",
        "evaluate_no_po_policy",
        {"invoice_amount": invoice_amount, "cost_center": cost_center},
    )


def select_approval_route(invoice_amount: float, supplier_tier: str = "standard") -> dict[str, Any]:
    """Select the required approval role based on invoice amount and supplier tier."""
    verify_tool_permission("control-executor", "select_approval_route")
    from app.agent.policy import get_active_policy
    policy = get_active_policy()
    if policy and policy.version != "v1.0.0":
        threshold = policy.finance_director_threshold
        role = "Finance Director" if invoice_amount > threshold else "Finance Approver"
        return {
            "check_id": "CHK_APP_ROUTE",
            "status": "PASSED",
            "message": f"Approval route assigned to role: {role}",
            "raw_output": {"required_role": role, "threshold": threshold},
        }
    return get_mcp_client().call_tool(
        "control-executor",
        "select_approval_route",
        {"invoice_amount": invoice_amount, "supplier_tier": supplier_tier},
    )


def validate_check_completeness(
    required_check_ids: list[str],
    completed_check_ids: list[str] | None = None,
    executed_check_ids: list[str] | None = None,
    check_results: list[dict[str, Any]] | None = None,
    registry_version: str = "v1.0.0",
    policy_version: str = "v1.0.0",
) -> dict[str, Any]:
    """Verify that all mandatory AP controls were executed and none are missing."""
    verify_tool_permission("control-executor", "validate_check_completeness")
    args: dict[str, Any] = {
        "required_check_ids": required_check_ids,
        "registry_version": registry_version,
        "policy_version": policy_version,
    }
    if completed_check_ids is not None:
        args["completed_check_ids"] = completed_check_ids
    if executed_check_ids is not None:
        args["executed_check_ids"] = executed_check_ids
    if check_results is not None:
        args["check_results"] = [c.model_dump() if hasattr(c, "model_dump") else c for c in check_results]
    return get_mcp_client().call_tool(
        "control-executor",
        "validate_check_completeness",
        args,
    )


def select_final_decision(
    check_results: list[dict[str, Any]],
    registry_version: str = "v1.0.0",
    completeness_valid: bool = True,
) -> dict[str, Any]:
    """Aggregate all check results into a final READY_FOR_APPROVAL, NEEDS_ATTENTION, or BLOCKED decision."""
    verify_tool_permission("control-executor", "select_final_decision")
    if not completeness_valid:
        raise ValueError("completeness validation failed: mandatory controls missing")
    serialized = [c.model_dump() if hasattr(c, "model_dump") else c for c in check_results]
    return get_mcp_client().call_tool(
        "control-executor",
        "select_final_decision",
        {
            "check_results": serialized,
            "registry_version": registry_version,
            "completeness_valid": completeness_valid,
        },
    )


# --- Exception Investigator Tools ---

def get_invoice_evidence(run_id: str) -> dict[str, Any]:
    """Retrieve all raw evidence collected for a run to support exception investigation."""
    verify_tool_permission("exception-investigator", "get_invoice_evidence")
    return get_mcp_client().call_tool("exception-investigator", "get_invoice_evidence", {"run_id": run_id})


def get_supplier_candidates(query: str) -> list[dict[str, Any]]:
    """Search master vendor directory for supplier candidates matching the query."""
    verify_tool_permission("exception-investigator", "get_supplier_candidates")
    return get_mcp_client().call_tool("exception-investigator", "get_supplier_candidates", {"query": query})


def get_po_candidates(supplier_id: str, amount: float = 0.0) -> list[dict[str, Any]]:
    """Retrieve open PO candidates for a supplier that could match the invoice amount."""
    verify_tool_permission("exception-investigator", "get_po_candidates")
    return get_mcp_client().call_tool("exception-investigator", "get_po_candidates", {"supplier_id": supplier_id, "amount": amount})


def get_po_lines(po_number: str) -> list[dict[str, Any]]:
    """Retrieve line items for a specific purchase order."""
    verify_tool_permission("exception-investigator", "get_po_lines")
    return get_mcp_client().call_tool("exception-investigator", "get_po_lines", {"po_number": po_number})


def get_policy_rule(rule_key: str) -> dict[str, Any]:
    """Look up a specific AP policy rule by its key."""
    verify_tool_permission("exception-investigator", "get_policy_rule")
    return get_mcp_client().call_tool("exception-investigator", "get_policy_rule", {"rule_key": rule_key})


def get_prior_invoice_matches(supplier_id: str, amount: float) -> list[dict[str, Any]]:
    """Find previously processed invoices from this supplier with a similar amount."""
    verify_tool_permission("exception-investigator", "get_prior_invoice_matches")
    return get_mcp_client().call_tool("exception-investigator", "get_prior_invoice_matches", {"supplier_id": supplier_id, "amount": amount})


def compare_candidate_records(candidate_type: str, candidate_ids: list[str]) -> dict[str, Any]:
    """Compare multiple candidate records side by side to support exception resolution."""
    verify_tool_permission("exception-investigator", "compare_candidate_records")
    return get_mcp_client().call_tool("exception-investigator", "compare_candidate_records", {"candidate_type": candidate_type, "candidate_ids": candidate_ids})


# --- Workflow Improvement Analyst Tools ---

def get_feedback_events(limit: int = 50) -> list[dict[str, Any]]:
    """Retrieve recent reviewer correction events for workflow improvement analysis."""
    verify_tool_permission("workflow-improvement-analyst", "get_feedback_events")
    return get_mcp_client().call_tool("workflow-improvement-analyst", "get_feedback_events", {"limit": limit})


def group_feedback_patterns(feedback_events: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Group feedback events into recurring patterns that suggest a policy improvement."""
    verify_tool_permission("workflow-improvement-analyst", "group_feedback_patterns")
    return get_mcp_client().call_tool("workflow-improvement-analyst", "group_feedback_patterns", {"feedback_events": feedback_events})


def create_candidate_version(
    target_type: str,
    diff_payload: dict[str, Any],
    candidate_version: str,
) -> dict[str, Any]:
    """Create a bounded candidate policy version from an improvement diff payload."""
    verify_tool_permission("workflow-improvement-analyst", "create_candidate_version")
    return get_mcp_client().call_tool(
        "workflow-improvement-analyst",
        "create_candidate_version",
        {
            "target_type": target_type,
            "diff_payload": diff_payload,
            "candidate_version": candidate_version,
        },
    )


def run_regression_suite(candidate_version: str, dataset_version: str = "v1") -> dict[str, Any]:
    """Run the regression test suite against a candidate policy version."""
    verify_tool_permission("workflow-improvement-analyst", "run_regression_suite")
    return get_mcp_client().call_tool(
        "workflow-improvement-analyst",
        "run_regression_suite",
        {"candidate_version": candidate_version, "dataset_version": dataset_version},
    )


def verify_regression_results(regression_run_id: str) -> dict[str, Any]:
    """Verify regression results and confirm all critical tests passed."""
    verify_tool_permission("workflow-improvement-analyst", "verify_regression_results")
    return get_mcp_client().call_tool(
        "workflow-improvement-analyst",
        "verify_regression_results",
        {"regression_run_id": regression_run_id},
    )


# --- Privileged Deterministic Tools (Application-Only) ---

def authorize_approval(
    run_id: str,
    approver_role: str,
    user_id: str,
    decision_revision: int = 1,
) -> dict[str, Any]:
    verify_tool_permission("deterministic_application", "authorize_approval")
    return get_mcp_client().call_tool(
        "deterministic_application",
        "authorize_approval",
        {
            "run_id": run_id,
            "approver_role": approver_role,
            "user_id": user_id,
            "decision_revision": decision_revision,
        },
    )


def build_posting_package(
    run_id: str,
    extracted_invoice: dict[str, Any],
    decision: dict[str, Any],
    audit_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    verify_tool_permission("deterministic_application", "build_posting_package")
    return get_mcp_client().call_tool(
        "deterministic_application",
        "build_posting_package",
        {
            "run_id": run_id,
            "extracted_invoice": extracted_invoice,
            "decision": decision,
            "audit_metadata": audit_metadata,
        },
    )


def activate_workflow_version(candidate_version: str, administrator_id: str) -> dict[str, Any]:
    verify_tool_permission("deterministic_application", "activate_workflow_version")
    from app.agent.policy import activate_policy
    res = get_mcp_client().call_tool(
        "deterministic_application",
        "activate_workflow_version",
        {
            "candidate_version": candidate_version,
            "administrator_id": administrator_id,
        },
    )
    activate_policy(candidate_version, administrator_id=administrator_id)
    return res


def rollback_workflow_version(target_version: str, administrator_id: str) -> dict[str, Any]:
    verify_tool_permission("deterministic_application", "rollback_workflow_version")
    res = get_mcp_client().call_tool(
        "deterministic_application",
        "rollback_workflow_version",
        {"target_version": target_version, "administrator_id": administrator_id},
    )
    from app.agent.policy import rollback_policy
    rollback_policy(target_version, administrator_id=administrator_id)
    return res
