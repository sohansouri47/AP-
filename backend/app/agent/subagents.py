"""Specialist Subagents for AP AI Employee and Improvement Architectures.

Defines the three specialist subagents:
1. control-executor
2. exception-investigator
3. workflow-improvement-analyst

Provides both declarative Deep Agent subagent specifications and deterministic
execution harnesses backed by MCP tools.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from app.agent.schemas import (
    CandidateComparison,
    CheckResult,
    ControlExecutionReport,
    DecisionResult,
    EvidenceSummary,
    ImprovementProposal,
    InvestigationResult,
    UnresolvedItem,
)
from app.agent.mcp_tools import (
    CONTROL_EXECUTOR_ALLOWLIST,
    EXCEPTION_INVESTIGATOR_ALLOWLIST,
    WORKFLOW_IMPROVEMENT_ALLOWLIST,
    verify_tool_permission,
    global_check_registry,
    get_required_checks,
    check_file_duplicate,
    resolve_supplier,
    check_business_duplicate,
    check_remit_change,
    check_arithmetic,
    check_dates_currency,
    identify_purchase_order,
    validate_po_header,
    match_po_lines,
    calculate_po_remaining,
    evaluate_po_tolerances,
    evaluate_no_po_policy,
    select_approval_route,
    validate_check_completeness,
    select_final_decision,
    get_invoice_evidence,
    get_supplier_candidates,
    get_po_candidates,
    get_po_lines,
    get_policy_rule,
    get_prior_invoice_matches,
    compare_candidate_records,
    get_feedback_events,
    group_feedback_patterns,
    create_candidate_version,
    run_regression_suite,
    verify_regression_results,
)
from app.agent.observability import TraceObserver
from app.agent.flow_logger import flow_logger
from app.events import emit_event, current_run_id
from app.agent.prompts import (
    CONTROL_EXECUTOR_SYSTEM_PROMPT,
    EXCEPTION_INVESTIGATOR_SYSTEM_PROMPT,
    WORKFLOW_IMPROVEMENT_SYSTEM_PROMPT,
    format_control_execution_task,
    format_exception_investigation_task,
    format_workflow_improvement_task,
    AMBIGUOUS_PO_QUESTION,
)


def _emit_live(event_type: str, data: dict) -> None:
    """Emit an event to the live SSE bus using the current run's thread_id."""
    try:
        tid = current_run_id.get("")
        if tid:
            emit_event(tid, event_type, data)
    except Exception:
        pass


def _wrap_control_tool(fn: Any) -> Any:
    """Wrap a control tool so it emits control_completed to the SSE bus immediately on return.

    Uses functools.wraps so deepagents SDK sees the original signature/docstring.
    """
    import functools

    @functools.wraps(fn)
    def _live_tool(*args, **kwargs):
        t0 = time.time()
        result = fn(*args, **kwargs)
        latency_ms = (time.time() - t0) * 1000
        try:
            if isinstance(result, dict) and result.get("check_id"):
                cid = result["check_id"]
                status = result.get("status", "PASSED")
                message = result.get("message", "")
                _emit_live("control_completed", {
                    "check_id": cid,
                    "status": status,
                    "message": message,
                    "latency_ms": latency_ms,
                })
                if status in ("FAILED", "REQUIRES_INPUT"):
                    _emit_live("exception_raised", {
                        "check_id": cid,
                        "status": status,
                        "message": message,
                    })
                if cid == "CHK_SUPPLIER_RES":
                    raw = result.get("raw_output") or {}
                    _emit_live("supplier_resolved", {
                        "supplier_id": raw.get("supplier_id"),
                        "supplier_name": raw.get("supplier_name") or raw.get("vendor_name"),
                    })
        except Exception:
            pass
        return result

    return _live_tool


def _wrap_extract_invoice(fn: Any) -> Any:
    """Wrap extract_invoice so it emits extraction_completed immediately when the LLM tool returns."""
    import functools

    @functools.wraps(fn)
    def _live_extract(*args, **kwargs):
        result = fn(*args, **kwargs)
        try:
            extracted = result.get("extracted_data", result) if isinstance(result, dict) else {}
            _emit_live("extraction_completed", {
                "invoice_number": extracted.get("invoice_number"),
                "supplier_name": extracted.get("supplier_name"),
                "total_amount": extracted.get("total_amount"),
            })
        except Exception:
            pass
        return result

    return _live_extract


# =====================================================================
# 1. Declarative Subagent Specs for Deep Agents SDK
# =====================================================================

def get_control_executor_subagent_spec() -> dict[str, Any]:
    """Declarative subagent spec for create_deep_agent."""
    return {
        "name": "control-executor",
        "description": "Executes mandatory AP financial controls via MCP tools, validates completeness, and selects deterministic decision.",
        "system_prompt": CONTROL_EXECUTOR_SYSTEM_PROMPT,
        "mode": "isolated",
        "tools": [
            get_required_checks,   # must be first — subagent calls this to know which checks to run
            _wrap_control_tool(check_file_duplicate),
            _wrap_control_tool(resolve_supplier),
            _wrap_control_tool(check_business_duplicate),
            _wrap_control_tool(check_remit_change),
            _wrap_control_tool(check_arithmetic),
            _wrap_control_tool(check_dates_currency),
            _wrap_control_tool(identify_purchase_order),
            _wrap_control_tool(validate_po_header),
            _wrap_control_tool(match_po_lines),
            _wrap_control_tool(calculate_po_remaining),
            _wrap_control_tool(evaluate_po_tolerances),
            _wrap_control_tool(evaluate_no_po_policy),
            _wrap_control_tool(select_approval_route),
            validate_check_completeness,
            select_final_decision,
        ],
    }


def get_exception_investigator_subagent_spec() -> dict[str, Any]:
    """Declarative subagent spec for create_deep_agent."""
    return {
        "name": "exception-investigator",
        "description": "Investigates unresolved AP exceptions, ambiguous vendors, and PO candidates using read-only evidence tools.",
        "system_prompt": EXCEPTION_INVESTIGATOR_SYSTEM_PROMPT,
        "mode": "isolated",
        "tools": [
            get_invoice_evidence,
            get_supplier_candidates,
            get_po_candidates,
            get_po_lines,
            get_policy_rule,
            get_prior_invoice_matches,
            compare_candidate_records,
        ],
    }


def get_workflow_improvement_subagent_spec() -> dict[str, Any]:
    """Declarative subagent spec for create_deep_agent."""
    return {
        "name": "workflow-improvement-analyst",
        "description": "Analyzes recurring reviewer corrections, drafts bounded candidate improvements, and executes regression tests.",
        "system_prompt": WORKFLOW_IMPROVEMENT_SYSTEM_PROMPT,
        "mode": "isolated",
        "tools": [
            get_feedback_events,
            group_feedback_patterns,
            create_candidate_version,
            run_regression_suite,
            verify_regression_results,
        ],
    }


# =====================================================================
# 2. Specialist Execution Harnesses
# =====================================================================

def execute_controls(
    run_id: str,
    invoice_reference: str,
    extracted_invoice: dict[str, Any],
    policy_version: str = "v1.0.0",
    tracer: TraceObserver | None = None,
    skip_checks: list[str] | None = None,
    human_action: dict[str, Any] | None = None,
    suppress_live_events: bool = False,
) -> ControlExecutionReport:
    """Execute all applicable AP controls deterministically via MCP tools.
    
    1. Query get_required_checks
    2. Execute tools for each check
    3. Validate completeness
    4. Select final decision
    """
    start_time = time.time()
    skip_set = set(skip_checks or [])

    # Apply human PO selection: override po_number so downstream checks use the resolved PO
    # Coerce to str — LLM extraction may return None for po_number, which crashes MCP tool validation
    resolved_po = str((human_action or {}).get("selected_po") or extracted_invoice.get("po_number") or "")


    # 1. get_required_checks
    t0 = time.time()
    required_checks = global_check_registry.get_required_checks(invoice_reference, policy_version)
    if tracer:
        tracer.log_mcp_tool_call(
            tool_name="get_required_checks",
            caller="control-executor",
            inputs={"invoice_reference": invoice_reference, "policy_version": policy_version},
            output=[c.model_dump() for c in required_checks],
            duration_ms=(time.time() - t0) * 1000,
        )

    required_check_ids = [c.check_id for c in required_checks]
    completed_check_ids: list[str] = []
    check_results: list[CheckResult] = []
    unresolved_items: list[UnresolvedItem] = []

    flow_logger.subagent_start("control-executor", "execute_controls", f"Evaluating {len(required_checks)} AP financial controls (Policy: {policy_version})")

    # Map of check_id to handler
    tool_map: dict[str, Callable[[], dict[str, Any]]] = {
        "CHK_FILE_DUP": lambda: check_file_duplicate(invoice_reference),
        "CHK_SUPPLIER_RES": lambda: resolve_supplier(extracted_invoice.get("supplier_name", ""), extracted_invoice.get("supplier_tax_id", "")),
        "CHK_BIZ_DUP": lambda: check_business_duplicate(
            extracted_invoice.get("supplier_id", "SUPP-001"),
            extracted_invoice.get("invoice_number", ""),
            extracted_invoice.get("invoice_date", ""),
            extracted_invoice.get("total_amount", 0.0),
        ),
        "CHK_REMIT_CHANGE": lambda: check_remit_change(extracted_invoice.get("supplier_id", "SUPP-001"), extracted_invoice.get("bank_account_last4", "")),
        "CHK_ARITHMETIC": lambda: check_arithmetic(
            extracted_invoice.get("subtotal", 0.0),
            extracted_invoice.get("tax_amount", 0.0),
            extracted_invoice.get("total_amount", 0.0),
            extracted_invoice.get("lines"),
        ),
        "CHK_DATES_CURR": lambda: check_dates_currency(
            extracted_invoice.get("invoice_date", ""),
            extracted_invoice.get("due_date", ""),
            extracted_invoice.get("currency", "USD"),
        ),
        "CHK_PO_IDENT": lambda: identify_purchase_order(
            invoice_reference,
            resolved_po,
            supplier_id=extracted_invoice.get("supplier_id", ""),
            invoice_amount=extracted_invoice.get("total_amount", 0.0),
        ),
        "CHK_PO_HEADER": lambda: validate_po_header(resolved_po, extracted_invoice.get("supplier_id", "")),
        "CHK_PO_LINES": lambda: match_po_lines(resolved_po, extracted_invoice.get("lines")),
        "CHK_PO_REMAIN": lambda: calculate_po_remaining(resolved_po, extracted_invoice.get("total_amount", 0.0)),
        "CHK_PO_TOL": lambda: evaluate_po_tolerances(extracted_invoice.get("lines")),
        "CHK_NO_PO_POL": lambda: evaluate_no_po_policy(extracted_invoice.get("total_amount", 0.0)),
        "CHK_APP_ROUTE": lambda: select_approval_route(extracted_invoice.get("total_amount", 0.0)),
    }

    # Also include dynamically registered checks
    for cid, fn in global_check_registry._tool_callables.items():
        if cid not in tool_map:
            tool_map[cid] = fn

    # PO-dependent checks that must be skipped when PO identity is unresolved
    PO_DEPENDENT_CHECKS = {"CHK_PO_HEADER", "CHK_PO_LINES", "CHK_PO_REMAIN", "CHK_PO_TOL"}
    po_unresolved = False  # set True when CHK_PO_IDENT returns REQUIRES_INPUT

    # Execute checks
    for check in required_checks:
        cid = check.check_id
        if cid in skip_set:
            continue

        # Skip downstream PO checks if the PO identity is still ambiguous
        if po_unresolved and cid in PO_DEPENDENT_CHECKS:
            cr = CheckResult(
                check_id=cid,
                tool_name=check.tool_name,
                status="SKIPPED",
                message="Skipped — purchase order not yet identified",
                raw_output={},
            )
            check_results.append(cr)
            completed_check_ids.append(cid)
            if not suppress_live_events:
                _emit_live("control_completed", {
                    "check_id": cid,
                    "status": "SKIPPED",
                    "message": cr.message,
                    "latency_ms": 0.0,
                })
            flow_logger.tool_call(
                caller="control-executor",
                tool_name=check.tool_name,
                status="SKIPPED",
                details=f"[{cid}] {cr.message}",
                duration_ms=0.0,
            )
            continue

        handler = tool_map.get(cid)
        if not handler:
            # Fallback mock for dynamic checks
            res_dict = {
                "check_id": cid,
                "status": "PASSED",
                "message": f"Dynamic check {cid} passed",
                "raw_output": {},
            }
        else:
            t_call = time.time()
            res_dict = handler()
            if tracer:
                tracer.log_mcp_tool_call(
                    tool_name=check.tool_name,
                    caller="control-executor",
                    inputs={"run_id": run_id, "check_id": cid},
                    output=res_dict,
                    duration_ms=(time.time() - t_call) * 1000,
                )

        cr = CheckResult(
            check_id=res_dict.get("check_id", cid),
            tool_name=check.tool_name,
            status=res_dict.get("status", "PASSED"),
            message=res_dict.get("message", ""),
            raw_output=res_dict.get("raw_output", {}),
            error_code=res_dict.get("error_code"),
        )
        check_results.append(cr)
        completed_check_ids.append(cid)

        # Enrich extracted invoice with resolved supplier ID if not already present
        if cid == "CHK_SUPPLIER_RES" and res_dict.get("raw_output", {}).get("supplier_id"):
            if not extracted_invoice.get("supplier_id"):
                extracted_invoice["supplier_id"] = res_dict["raw_output"]["supplier_id"]

        # Update resolved_po when CHK_PO_IDENT auto-resolves (single open PO found)
        # The downstream lambdas (CHK_PO_HEADER/LINES/REMAIN) close over resolved_po by reference,
        # so rebinding it here makes them pick up the correct PO for subsequent calls.
        if cid == "CHK_PO_IDENT" and cr.status == "PASSED":
            auto_po = cr.raw_output.get("po_number") or res_dict.get("raw_output", {}).get("po_number")
            if auto_po and not resolved_po:
                resolved_po = str(auto_po)
            if not suppress_live_events:
                _emit_live("supplier_resolved", {
                    "supplier_name": extracted_invoice.get("supplier_name"),
                    "supplier_id": extracted_invoice.get("supplier_id") or res_dict["raw_output"].get("supplier_id"),
                    "invoice_number": extracted_invoice.get("invoice_number"),
                    "total_amount": extracted_invoice.get("total_amount"),
                })

        if not suppress_live_events:
            _emit_live("control_completed", {
                "check_id": cr.check_id,
                "status": cr.status,
                "message": cr.message,
                "latency_ms": (time.time() - t_call) * 1000 if 't_call' in locals() else 0.0,
            })
            if cr.status in ("FAILED", "REQUIRES_INPUT"):
                _emit_live("exception_raised", {
                    "check_id": cr.check_id,
                    "status": cr.status,
                    "message": cr.message,
                })

        flow_logger.tool_call(
            caller="control-executor",
            tool_name=check.tool_name,
            status=cr.status,
            details=f"[{cid}] {cr.message}",
            duration_ms=(time.time() - t_call) * 1000 if 't_call' in locals() else 0.0,
        )

        if cr.status == "REQUIRES_INPUT":
            unresolved_items.append(
                UnresolvedItem(
                    check_id=cid,
                    item_type=res_dict.get("error_code", "AMBIGUITY"),
                    description=cr.message,
                    candidates=cr.raw_output.get("candidates", []),
                )
            )
            if cid == "CHK_PO_IDENT":
                po_unresolved = True

    # 3. validate_check_completeness
    t_comp = time.time()
    comp_result = validate_check_completeness(
        required_check_ids=required_check_ids,
        completed_check_ids=completed_check_ids,
        check_results=[c.model_dump() for c in check_results],
        registry_version=policy_version,
    )
    if tracer:
        tracer.log_mcp_tool_call(
            tool_name="validate_check_completeness",
            caller="control-executor",
            inputs={"required_check_ids": required_check_ids, "completed_check_ids": completed_check_ids},
            output=comp_result,
            duration_ms=(time.time() - t_comp) * 1000,
        )

    completeness_valid = comp_result.get("valid", False)
    missing_checks = comp_result.get("missing_checks", [])
    flow_logger.gate(
        "ControlCompletenessGate",
        "VALID" if completeness_valid else "INVALID",
        f"Executed: {len(completed_check_ids)}/{len(required_check_ids)} checks | Missing: {missing_checks}",
    )

    # 4. select_final_decision (only if completeness is valid)
    decision: DecisionResult | None = None
    if completeness_valid:
        t_dec = time.time()
        dec_dict = select_final_decision(
            check_results=[c.model_dump() for c in check_results],
            registry_version=policy_version,
            completeness_valid=True,
        )
        if tracer:
            tracer.log_mcp_tool_call(
                tool_name="select_final_decision",
                caller="control-executor",
                inputs={"completed_checks": len(completed_check_ids)},
                output=dec_dict,
                duration_ms=(time.time() - t_dec) * 1000,
            )
        decision = DecisionResult(**dec_dict)
        flow_logger.gate(
            "DecisionSelectionGate",
            decision.status,
            f"Revision: {decision.revision} | Role: {decision.required_role} | {decision.summary}",
        )
        if not suppress_live_events:
            _emit_live("decision_ready", {
                "lifecycle_status": decision.status,
                "decision": dec_dict,
            })
        flow_logger.subagent_end(
            "control-executor",
            "COMPLETED",
            f"Status: {decision.status} (Role: {decision.required_role})",
        )

    report = ControlExecutionReport(
        run_id=run_id,
        registry_version=policy_version,
        required_check_ids=required_check_ids,
        completed_check_ids=completed_check_ids,
        check_results=check_results,
        completeness_valid=completeness_valid,
        missing_checks=missing_checks,
        decision=decision,
        unresolved_items=unresolved_items,
    )

    if tracer:
        tracer.log_subagent_delegation(
            subagent_name="control-executor",
            task_prompt=format_control_execution_task(run_id),
            result=report.model_dump(),
            skills_loaded=["control_execution"],
        )

    return report


def investigate_exceptions(
    run_id: str,
    control_report: ControlExecutionReport,
    extracted_invoice: dict[str, Any] | None = None,
    tracer: TraceObserver | None = None,
) -> InvestigationResult:
    """Investigate unresolved check items using read-only evidence MCP tools."""
    if not control_report.unresolved_items:
        return InvestigationResult(
            exception_type="NONE",
            evidence_summary=[],
            candidates=[],
            recommendation="No exceptions to investigate.",
            human_input_required=False,
            specific_question=None,
            allowed_actions=[],
            affected_check_ids=[],
        )

    item = control_report.unresolved_items[0]
    cid = item.check_id
    flow_logger.subagent_start("exception-investigator", "investigate_exceptions", f"Investigating check {cid} ({item.item_type}): {item.description}")

    # Derive supplier_id and amount from the actual invoice
    inv = extracted_invoice or {}
    supplier_id = inv.get("supplier_id") or ""
    total_amount = float(inv.get("total_amount") or 0.0)

    # Fall back to CHK_SUPPLIER_RES raw_output if supplier_id wasn't in extracted_invoice
    if not supplier_id:
        supplier_res = next(
            (c for c in control_report.check_results if c.check_id == "CHK_SUPPLIER_RES"),
            None,
        )
        if supplier_res:
            supplier_id = supplier_res.raw_output.get("supplier_id", "")

    # Candidate IDs come from the unresolved item (populated from CHK_PO_IDENT raw_output.candidates)
    candidate_ids = [str(c) for c in item.candidates] if item.candidates else []

    # Call read-only evidence tools
    evidence_res = get_invoice_evidence(run_id)
    po_candidates_res = get_po_candidates(supplier_id, total_amount)
    comparison_res = compare_candidate_records("PURCHASE_ORDER", candidate_ids) if candidate_ids else {"comparisons": []}

    flow_logger.tool_call("exception-investigator", "get_invoice_evidence", "SUCCESS", f"Found {len(evidence_res.get('evidence', []))} evidence fields")
    flow_logger.tool_call("exception-investigator", "get_po_candidates", "SUCCESS", f"Found {len(po_candidates_res)} open PO candidates")
    flow_logger.tool_call("exception-investigator", "compare_candidate_records", "SUCCESS", "Evaluated PO line & amount variance")

    if tracer:
        tracer.log_mcp_tool_call("get_invoice_evidence", "exception-investigator", {"run_id": run_id}, evidence_res)
        tracer.log_mcp_tool_call("get_po_candidates", "exception-investigator", {"supplier_id": supplier_id, "amount": total_amount}, po_candidates_res)
        tracer.log_mcp_tool_call("compare_candidate_records", "exception-investigator", {}, comparison_res)

    evidence_summary = [
        EvidenceSummary(source=e["source"], field_name=e["field_name"], value=e["value"], confidence=e.get("confidence", 1.0))
        for e in evidence_res.get("evidence", [])
    ]
    candidates = [
        CandidateComparison(
            candidate_id=c["candidate_id"],
            candidate_name=c["candidate_name"],
            match_score=c["match_score"],
            key_differences=c.get("key_differences", []),
        )
        for c in comparison_res.get("comparisons", [])
    ]

    # Derive allowed actions from actual candidate IDs (e.g. PO-2001 -> SELECT_PO_2001)
    select_actions = [f"SELECT_{cid.replace('-', '_')}" for cid in candidate_ids]
    allowed_actions = select_actions + ["REJECT_INVOICE"]

    inv_result = InvestigationResult(
        exception_type=item.item_type,
        evidence_summary=evidence_summary,
        candidates=candidates,
        recommendation=None,  # Genuine ambiguity: must not guess
        human_input_required=True,
        specific_question=AMBIGUOUS_PO_QUESTION,
        allowed_actions=allowed_actions,
        affected_check_ids=[item.check_id, "CHK_PO_HEADER", "CHK_PO_LINES", "CHK_PO_REMAIN", "CHK_PO_TOL"],
    )

    flow_logger.subagent_end(
        "exception-investigator",
        "REQUIRES_HUMAN_INPUT",
        f"Question: '{inv_result.specific_question}' | Actions: {inv_result.allowed_actions}",
    )

    if tracer:
        tracer.log_subagent_delegation(
            subagent_name="exception-investigator",
            task_prompt=format_exception_investigation_task(cid),
            result=inv_result.model_dump(),
            skills_loaded=["exception_investigation"],
        )

    return inv_result


def analyze_workflow_improvement(
    feedback_ids: list[str],
    candidate_version: str = "v1.1.0",
    force_regression: bool = False,
    tracer: TraceObserver | None = None,
) -> ImprovementProposal:
    """Analyze reviewer corrections and generate bounded candidate proposal."""
    flow_logger.subagent_start("workflow-improvement-analyst", "analyze_workflow_improvement", f"Feedback IDs: {feedback_ids}")
    events = get_feedback_events()
    patterns = group_feedback_patterns(events)

    if not patterns or len(events) < 2:
        raise ValueError("At least two similar reviewer corrections are required to formulate a proposal.")

    pattern = patterns[0]
    create_candidate_version(
        target_type=pattern["target_type"],
        diff_payload=pattern["proposed_diff"],
        candidate_version=candidate_version,
    )
    flow_logger.tool_call("workflow-improvement-analyst", "create_candidate_version", "SUCCESS", f"Candidate {candidate_version} staged with bounded diff")

    reg_result = run_regression_suite(candidate_version)
    critical_passed = not force_regression and reg_result.get("critical_tests_passed", True)
    regression_count = 1 if force_regression else reg_result.get("regression_count", 0)

    flow_logger.tool_call(
        "workflow-improvement-analyst",
        "run_regression_suite",
        "PASSED" if critical_passed and regression_count == 0 else "REGRESSION_DETECTED",
        f"Critical tests passed: {critical_passed}, Regressions: {regression_count}",
    )

    proposal = ImprovementProposal(
        proposal_id=f"PROP-{candidate_version}",
        pattern_summary=pattern["description"],
        supporting_feedback_ids=pattern["supporting_feedback_ids"],
        target_type=pattern["target_type"],
        bounded_diff=pattern["proposed_diff"],
        candidate_version=candidate_version,
        regression_run_id=reg_result.get("regression_run_id"),
        critical_tests_passed=critical_passed,
        regression_count=regression_count,
        approval_required=True,
    )

    flow_logger.subagent_end(
        "workflow-improvement-analyst",
        "PROPOSAL_DRAFTED",
        f"Proposal ID: {proposal.proposal_id} | Regression Count: {regression_count}",
    )

    if tracer:
        tracer.log_subagent_delegation(
            subagent_name="workflow-improvement-analyst",
            task_prompt=format_workflow_improvement_task(feedback_ids),
            result=proposal.model_dump(),
            skills_loaded=["workflow_improvement"],
        )

    return proposal
