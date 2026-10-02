"""Main AP AI Employee Pipeline.

Orchestrates:
1. Extraction of invoice data
2. Mandatory delegation of controls to Control Executor
3. Delegation of unresolved exceptions to Exception Investigator
4. Strict schema validation and deterministic output verification (Section 14)
"""

from __future__ import annotations

import time
from typing import Any

from app.agent.schemas import (
    APEmployeeOutcome,
    ControlExecutionReport,
    DecisionResult,
    InvestigationResult,
)
from app.agent.mcp_tools import (
    MAIN_AGENT_ALLOWLIST,
    extract_invoice,
    get_run_context,
    verify_tool_permission,
)
from app.agent.subagents import (
    execute_controls,
    get_control_executor_subagent_spec,
    get_exception_investigator_subagent_spec,
    investigate_exceptions,
)
from app.agent.observability import TraceObserver
from app.agent.flow_logger import flow_logger
from app.agent.llm import get_chat_model
from app.agent.prompts import (
    MAIN_AP_EMPLOYEE_SYSTEM_PROMPT,
    EXPLANATION_READY_FOR_APPROVAL,
    EXPLANATION_BLOCKED_TEMPLATE,
    EXPLANATION_NEEDS_ATTENTION_TEMPLATE,
    EXPLANATION_FAILED_TEMPLATE,
)




def verify_and_sanitize_outcome(
    run_id: str,
    control_report: ControlExecutionReport,
    investigation_result: InvestigationResult | None,
    raw_explanation: str | None = None,
) -> APEmployeeOutcome:
    """Validate outcome against Section 14 rules and ensure deterministic parity."""
    # Check completeness
    if not control_report.completeness_valid:
        missing_str = ", ".join(control_report.missing_checks)
        return APEmployeeOutcome(
            run_id=run_id,
            status="FAILED",
            control_report=control_report,
            investigation_result=investigation_result,
            explanation=EXPLANATION_FAILED_TEMPLATE.format(
                reason=f"Mandatory control completeness failed. Missing checks: {missing_str}."
            ),
            owner="AP AI Employee",
            next_action="Review check configuration and rerun required controls.",
            human_input_required=False,
        )

    # Determine status from deterministic MCP decision
    decision = control_report.decision
    if not decision:
        return APEmployeeOutcome(
            run_id=run_id,
            status="FAILED",
            control_report=control_report,
            investigation_result=investigation_result,
            explanation=EXPLANATION_FAILED_TEMPLATE.format(
                reason="No decision could be derived from check outputs."
            ),
            owner="AP AI Employee",
            next_action="Investigate execution logs.",
            human_input_required=False,
        )

    mcp_status = decision.status

    # If investigation found human input required, enforce NEEDS_ATTENTION
    if investigation_result and investigation_result.human_input_required:
        mcp_status = "NEEDS_ATTENTION"

    # Deterministic explanation template from prompts.py
    if mcp_status == "READY_FOR_APPROVAL":
        explanation = EXPLANATION_READY_FOR_APPROVAL
        owner = decision.required_role or "Finance Approver"
        next_action = "Awaiting Finance Approver digital sign-off."
        human_req = True
    elif mcp_status == "NEEDS_ATTENTION":
        q = investigation_result.specific_question if investigation_result else decision.summary
        explanation = EXPLANATION_NEEDS_ATTENTION_TEMPLATE.format(
            summary=decision.summary, question=q
        )
        owner = "AP Operator"
        next_action = "Awaiting AP Operator clarification."
        human_req = True
    elif mcp_status == "BLOCKED":
        explanation = EXPLANATION_BLOCKED_TEMPLATE.format(summary=decision.summary)
        owner = "AP Manager"
        next_action = "Invoice marked as BLOCKED. Return to vendor or cancel."
        human_req = False
    else:
        explanation = f"Processing failed: {decision.summary}."
        owner = "AP System"
        next_action = "Investigate system error."
        human_req = False

    return APEmployeeOutcome(
        run_id=run_id,
        status=mcp_status,
        control_report=control_report,
        investigation_result=investigation_result,
        explanation=explanation,
        owner=owner,
        next_action=next_action,
        human_input_required=human_req,
    )


def run_ap_employee_pipeline(
    run_id: str,
    invoice_reference: str,
    policy_version: str = "v1.0.0",
    human_action: dict[str, Any] | None = None,
    tracer: TraceObserver | None = None,
    force_skip_checks: list[str] | None = None,
) -> tuple[dict[str, Any], APEmployeeOutcome]:
    """Execute the end-to-end AP Employee flow with specialist subagent delegations."""
    flow_logger.agent_start(
        agent_name="MainAPEmployee",
        method_name="run_ap_employee_pipeline",
        details=f"InvoiceRef: '{invoice_reference}' | Policy: '{policy_version}'",
    )

    # 1. Extract invoice
    t0 = time.time()
    ext_res = extract_invoice(run_id, invoice_reference, tracer=tracer)
    extracted_invoice = ext_res.get("extracted_data", {})
    inv_num = extracted_invoice.get("invoice_number", "UNKNOWN")
    tot_amt = extracted_invoice.get("total_amount", 0.0)
    curr = extracted_invoice.get("currency", "USD")


    flow_logger.tool_call(
        caller="MainAPEmployee",
        tool_name="extract_invoice",
        status="SUCCESS",
        details=f"Extracted Invoice #{inv_num} | Vendor: '{extracted_invoice.get('vendor_name', 'Unknown')}' | Total: ${tot_amt:,.2f} {curr}",
        duration_ms=(time.time() - t0) * 1000,
    )

    if tracer:
        tracer.log_mcp_tool_call(
            tool_name="extract_invoice",
            caller="main_agent",
            inputs={"run_id": run_id, "invoice_reference": invoice_reference},
            output=ext_res,
        )

    # If resuming from human action (e.g. human selected a PO)
    if human_action:
        selected_po = human_action.get("selected_po")
        if selected_po:
            extracted_invoice["po_number"] = selected_po
            flow_logger.agent_start(
                agent_name="MainAPEmployee",
                method_name="apply_human_resolution",
                details=f"Applied Human Resolved PO: '{selected_po}'",
            )

    # 2. Delegate controls to Control Executor
    control_report = execute_controls(
        run_id=run_id,
        invoice_reference=invoice_reference,
        extracted_invoice=extracted_invoice,
        policy_version=policy_version,
        tracer=tracer,
        skip_checks=force_skip_checks,
    )

    # 3. Delegate unresolved cases to Exception Investigator
    investigation_result: InvestigationResult | None = None
    if control_report.unresolved_items and control_report.completeness_valid:
        investigation_result = investigate_exceptions(
            run_id=run_id,
            control_report=control_report,
            tracer=tracer,
        )

    # 4. Synthesize, validate, and verify outcome
    outcome = verify_and_sanitize_outcome(
        run_id=run_id,
        control_report=control_report,
        investigation_result=investigation_result,
    )

    flow_logger.outcome(
        status=outcome.status,
        owner=outcome.owner,
        explanation=outcome.explanation,
    )

    if tracer:
        tracer.log_final_decision(outcome.model_dump())

    return extracted_invoice, outcome
