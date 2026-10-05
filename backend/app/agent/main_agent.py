"""Main AP AI Employee Pipeline.

Orchestrates:
1. Extraction of invoice data
2. Mandatory delegation of controls to Control Executor
3. Delegation of unresolved exceptions to Exception Investigator
4. Strict schema validation and deterministic output verification (Section 14)
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import (
    APEmployeeOutcome,
    ControlExecutionReport,
    InvestigationResult,
)
from app.agent.observability import TraceObserver
from app.agent.flow_logger import flow_logger
from app.agent.prompts import (
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
    """Execute the end-to-end AP Employee flow via the Deep Agent with specialist subagents.

    Delegates to run_ap_employee_deep_agent which orchestrates:
    1. extract_invoice (main agent tool)
    2. control-executor subagent (15 control tools, isolated)
    3. exception-investigator subagent (7 read-only tools, isolated, if needed)
    4. verify_and_sanitize_outcome (deterministic Section 14 gate, always runs)
    """
    from app.agent.deep_agent import run_ap_employee_deep_agent

    return run_ap_employee_deep_agent(
        run_id=run_id,
        invoice_reference=invoice_reference,
        policy_version=policy_version,
        human_action=human_action,
        tracer=tracer,
        force_skip_checks=force_skip_checks,
    )
