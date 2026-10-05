"""LangGraph Orchestration Layer for AP AI Employee and Workflow Improvement.

Implements:
1. Invoice Processing Graph (with human-in-the-loop interrupts and posting package creation)
2. Improvement Graph (with regression gates and administrator approval interrupt)
"""

from __future__ import annotations

import time
from typing import Any
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.agent.schemas import ControlExecutionReport
from app.agent.state import APEmployeeState, WorkflowImprovementState
from app.agent.main_agent import run_ap_employee_pipeline, verify_and_sanitize_outcome
from app.agent.routing import (
    route_human_action,
    route_outcome_decision,
)
from app.agent.mcp_tools import (
    activate_workflow_version,
    authorize_approval,
    build_posting_package,
    get_feedback_events,
    run_regression_suite,
)
from app.agent.observability import get_improvement_tracer, get_invoice_tracer
from app.agent.persistence import get_checkpointer
from app.agent.policy import global_policy_manager
from app.agent.flow_logger import flow_logger


# =====================================================================
# 1. Invoice Processing Graph Nodes
# =====================================================================

def initialize_run(state: APEmployeeState) -> dict[str, Any]:
    """Initialize state, correlation IDs, and observability tracer."""
    run_id = state.get("run_id") or f"run-{int(time.time() * 1000)}"
    thread_id = state.get("thread_id") or run_id
    session_id = state.get("session_id") or thread_id
    flow_logger.node_start("InvoiceProcessingGraph", "initialize_run", "INIT", run_id)
    tracer = get_invoice_tracer(run_id=run_id, session_id=session_id)
    tracer.log_node_execution(
        node_name="initialize_run",
        stage="INIT",
        input_data={"run_id": run_id, "session_id": session_id, "invoice_ref": state.get("invoice_reference")},
    )
    return {
        "run_id": run_id,
        "thread_id": thread_id,
        "session_id": session_id,
        "lifecycle_status": "INITIALIZED",
        "current_stage": "INIT",
        "human_action_history": state.get("human_action_history") or [],
        "langfuse_trace_id": tracer.trace_id,
    }


def run_ap_employee(state: APEmployeeState) -> dict[str, Any]:
    """Execute main AP AI employee pipeline with specialist delegations."""
    run_id = state["run_id"]
    session_id = state.get("session_id") or state.get("thread_id") or run_id
    invoice_ref = state["invoice_reference"]
    policy_ver = state.get("registry_version") or "v1.0.0"
    flow_logger.node_start("InvoiceProcessingGraph", "run_ap_employee", "ANALYSIS", run_id)
    tracer = get_invoice_tracer(run_id=run_id, session_id=session_id)

    # Check if there is an applied human action to pass in
    history = state.get("human_action_history") or []
    last_human_action = history[-1] if history else None

    # Check for test-forced missing checks if any
    force_skip = state.get("safe_error", {}).get("force_skip_checks") if state.get("safe_error") else None

    # On resume, pass the already-extracted invoice so pre-extraction is skipped.
    # Re-extraction is non-deterministic (GPT-4o vision) and can return different
    # field values, corrupting checks like CHK_ARITHMETIC on the second pass.
    frozen_extracted = state.get("extracted_invoice") or None

    extracted_invoice, outcome = run_ap_employee_pipeline(
        run_id=run_id,
        invoice_reference=invoice_ref,
        policy_version=policy_ver,
        human_action=last_human_action,
        tracer=tracer,
        force_skip_checks=force_skip,
        frozen_extracted_invoice=frozen_extracted,
    )
    flow_logger.node_end("InvoiceProcessingGraph", "run_ap_employee", outcome.status, next_step="verify_agent_output")

    return {
        "extracted_invoice": extracted_invoice,
        "control_report": outcome.control_report.model_dump(),
        "investigation_result": outcome.investigation_result.model_dump() if outcome.investigation_result else None,
        "decision": outcome.control_report.decision.model_dump() if outcome.control_report.decision else None,
        "explanation": outcome.explanation,
        "lifecycle_status": outcome.status,
        "current_stage": "ANALYSIS_COMPLETE",
    }


def verify_agent_output(state: APEmployeeState) -> dict[str, Any]:
    """Validate model output against Section 14 rules and ensure deterministic parity."""
    run_id = state["run_id"]
    flow_logger.node_start("InvoiceProcessingGraph", "verify_agent_output", "VERIFY", run_id)
    raw_report = state.get("control_report")
    if not raw_report:
        return {
            "lifecycle_status": "FAILED",
            "current_stage": "VERIFIED",
            "explanation": "Fatal: No control execution report produced.",
        }

    control_report = ControlExecutionReport(**raw_report)
    inv_data = state.get("investigation_result")
    inv_res = None
    if inv_data:
        from app.agent.schemas import InvestigationResult
        inv_res = InvestigationResult(**inv_data)

    outcome = verify_and_sanitize_outcome(
        run_id=run_id,
        control_report=control_report,
        investigation_result=inv_res,
        raw_explanation=state.get("explanation"),
    )
    flow_logger.gate(
        "Section14DeterministicParity",
        "VERIFIED",
        f"Parity with MCP decision: {outcome.status}",
    )

    return {
        "lifecycle_status": outcome.status,
        "current_stage": "VERIFIED",
        "explanation": outcome.explanation,
        "decision": outcome.control_report.decision.model_dump() if outcome.control_report.decision else None,
    }


def route_outcome(state: APEmployeeState) -> dict[str, Any]:
    """Parent node capturing the determined routing state."""
    return {"current_stage": "ROUTING"}


def human_gate(state: APEmployeeState) -> dict[str, Any]:
    """LangGraph interrupt node pausing execution for human AP review or Finance approval."""
    status = state["lifecycle_status"]
    decision = state.get("decision") or {}
    run_id = state["run_id"]
    session_id = state.get("session_id") or state.get("thread_id") or run_id
    revision = decision.get("revision", 1)
    tracer = get_invoice_tracer(run_id=run_id, session_id=session_id)

    if status == "NEEDS_ATTENTION":
        inv = state.get("investigation_result") or {}
        interrupt_payload = {
            "type": "AP_REVIEW",
            "run_id": run_id,
            "session_id": session_id,
            "decision_revision": revision,
            "question": inv.get("specific_question"),
            "allowed_actions": inv.get("allowed_actions") or ["SELECT_PO_2001", "SELECT_PO_2002", "REJECT_INVOICE"],
            "evidence_ids": [e["field_name"] for e in inv.get("evidence_summary", [])],
        }
    elif status == "READY_FOR_APPROVAL":
        interrupt_payload = {
            "type": "FINANCE_APPROVAL",
            "run_id": run_id,
            "session_id": session_id,
            "decision_revision": revision,
            "decision_summary": decision.get("summary", ""),
            "required_role": decision.get("required_role", "Finance Approver"),
            "allowed_actions": ["APPROVE", "REJECT"],
        }
    else:
        return {}

    tracer.log_interrupt(interrupt_payload["type"], interrupt_payload)
    flow_logger.interrupt(
        interrupt_type=interrupt_payload["type"],
        role=interrupt_payload.get("required_role", "AP Operator"),
        question=interrupt_payload.get("question") or interrupt_payload.get("decision_summary", ""),
        allowed_actions=interrupt_payload.get("allowed_actions"),
    )

    # Real LangGraph interrupt
    human_response = interrupt(interrupt_payload)
    return {"pending_human_action": human_response}


def apply_human_action(state: APEmployeeState) -> dict[str, Any]:
    """Validate human action outside LLM, enforce roles, and perform idempotent side effects."""
    action = state.get("pending_human_action") or {}
    run_id = state["run_id"]
    session_id = state.get("session_id") or state.get("thread_id") or run_id
    user_id = action.get("user_id")
    tracer = get_invoice_tracer(run_id=run_id, session_id=session_id, user_id=user_id)
    tracer.log_resume(action)

    action_type = action.get("action")
    role = action.get("role", "")
    revision = action.get("decision_revision")
    current_decision = state.get("decision") or {}
    current_rev = current_decision.get("revision", 1)

    flow_logger.resume(
        user_id=action.get("user_id", "operator"),
        role=role or "Operator",
        action=action_type or "ACTION",
        revision=current_rev,
    )

    # Validate decision revision (prevent stale actions)
    if revision is not None and revision != current_rev:
        raise ValueError(
            f"Stale action rejected: Action revision {revision} != Current decision revision {current_rev}"
        )

    # Role validation outside LLM
    if action_type == "APPROVE":
        if role not in ("Finance Approver", "Finance Director"):
            raise PermissionError(
                f"Unauthorized action: Role '{role}' cannot authorize invoice approval. Required: Finance Approver."
            )

        # Idempotent posting package generation
        posting_pkg = state.get("posting_package")
        if not posting_pkg:
            authorize_approval(
                run_id=run_id,
                approver_role=role,
                user_id=action.get("user_id", "user_unknown"),
                decision_revision=current_rev,
            )
            posting_pkg = build_posting_package(
                run_id=run_id,
                extracted_invoice=state.get("extracted_invoice") or {},
                decision=current_decision,
                audit_metadata={"approved_by": action.get("user_id"), "role": role},
            )

        return {
            "posting_package": posting_pkg,
            "lifecycle_status": "POSTING_PACKAGE_READY",
            "current_stage": "ACTION_APPLIED",
            "human_action_history": [action],
            "pending_human_action": None,
        }

    elif action_type == "REJECT":
        return {
            "lifecycle_status": "REJECTED",
            "current_stage": "ACTION_APPLIED",
            "human_action_history": [action],
            "pending_human_action": None,
        }

    # Operator exception resolution (e.g. SELECT_PO_2001)
    return {
        "current_stage": "ACTION_APPLIED",
        "human_action_history": [action],
        "pending_human_action": None,
    }


def finalize_run(state: APEmployeeState) -> dict[str, Any]:
    """Finalize run, set completed stage, and flush observability trace."""
    run_id = state.get("run_id", "unknown")
    session_id = state.get("session_id") or state.get("thread_id") or run_id
    tracer = get_invoice_tracer(run_id=run_id, session_id=session_id)
    tracer.log_node_execution("finalize_run", "COMPLETED", {"status": state.get("lifecycle_status")})
    tracer.flush()
    flow_logger.node_end("InvoiceProcessingGraph", "finalize_run", state.get("lifecycle_status", "COMPLETED"))
    return {"current_stage": "COMPLETED"}


def create_invoice_graph(checkpointer=None):
    """Build and compile the parent AP Employee LangGraph."""
    workflow = StateGraph(APEmployeeState)

    # Add nodes
    workflow.add_node("initialize_run", initialize_run)
    workflow.add_node("run_ap_employee", run_ap_employee)
    workflow.add_node("verify_agent_output", verify_agent_output)
    workflow.add_node("route_outcome", route_outcome)
    workflow.add_node("human_gate", human_gate)
    workflow.add_node("apply_human_action", apply_human_action)
    workflow.add_node("finalize_run", finalize_run)

    # Add edges
    workflow.add_edge(START, "initialize_run")
    workflow.add_edge("initialize_run", "run_ap_employee")
    workflow.add_edge("run_ap_employee", "verify_agent_output")
    workflow.add_edge("verify_agent_output", "route_outcome")

    # Conditional routing from route_outcome
    workflow.add_conditional_edges(
        "route_outcome",
        route_outcome_decision,
        {
            "human_gate": "human_gate",
            "finalize_run": "finalize_run",
        },
    )

    # After human gate resumes, apply action
    workflow.add_edge("human_gate", "apply_human_action")

    # Conditional routing after human action
    workflow.add_conditional_edges(
        "apply_human_action",
        route_human_action,
        {
            "finalize_run": "finalize_run",
            "run_ap_employee": "run_ap_employee",
        },
    )

    workflow.add_edge("finalize_run", END)

    cp = checkpointer if checkpointer is not None else get_checkpointer()
    return workflow.compile(checkpointer=cp)


# =====================================================================
# 2. Workflow Improvement Graph Nodes (Section 13)
# =====================================================================

def load_feedback(state: WorkflowImprovementState) -> dict[str, Any]:
    """Load repeated reviewer-feedback events."""
    events = get_feedback_events()
    proposal_id = state.get("proposal_id") or f"prop-{int(time.time() * 1000)}"
    thread_id = state.get("thread_id") or proposal_id
    session_id = state.get("session_id") or thread_id
    tracer = get_improvement_tracer(proposal_id=proposal_id, session_id=session_id)
    tracer.log_node_execution("load_feedback", "INIT", {"events_count": len(events)})

    return {
        "proposal_id": proposal_id,
        "thread_id": thread_id,
        "session_id": session_id,
        "feedback_records": events,
        "feedback_ids": [e["feedback_id"] for e in events],
        "lifecycle_status": "FEEDBACK_LOADED",
        "current_stage": "FEEDBACK_LOADED",
        "human_action_history": state.get("human_action_history") or [],
        "langfuse_trace_id": tracer.trace_id,
    }


def run_workflow_improvement_analyst(state: WorkflowImprovementState) -> dict[str, Any]:
    """Run Workflow Improvement Analyst to formulate bounded proposal."""
    proposal_id = state["proposal_id"]
    session_id = state.get("session_id") or state.get("thread_id") or proposal_id
    tracer = get_improvement_tracer(proposal_id=proposal_id, session_id=session_id)
    force_reg = state.get("safe_error", {}).get("force_regression", False) if state.get("safe_error") else False

    from app.agent.deep_agent import run_workflow_improvement_deep_agent
    proposal = run_workflow_improvement_deep_agent(
        feedback_ids=state["feedback_ids"],
        candidate_version="v1.1.0",
        force_regression=force_reg,
        tracer=tracer,
    )

    return {
        "proposal": proposal.model_dump(),
        "candidate_version": proposal.candidate_version,
        "current_stage": "PROPOSAL_DRAFTED",
    }


def create_candidate(state: WorkflowImprovementState) -> dict[str, Any]:
    """Ensure candidate is registered in inactive state."""
    return {"current_stage": "CANDIDATE_CREATED"}


def run_regression(state: WorkflowImprovementState) -> dict[str, Any]:
    """Execute deterministic regression suite."""
    proposal = state["proposal"] or {}
    cand_ver = proposal.get("candidate_version", "v1.1.0")
    force_reg = state.get("safe_error", {}).get("force_regression", False) if state.get("safe_error") else False

    res = run_regression_suite(cand_ver)
    if force_reg:
        res["critical_tests_passed"] = False
        res["regression_count"] = 1

    return {
        "regression_results": res,
        "regression_passed": res.get("critical_tests_passed", True),
        "regression_count": res.get("regression_count", 0),
        "current_stage": "REGRESSION_RUN",
    }


def verify_regression(state: WorkflowImprovementState) -> dict[str, Any]:
    """Verify release gate: 0 regressions, all critical tests pass."""
    reg_passed = state.get("regression_passed", False)
    reg_count = state.get("regression_count", 0)

    if not reg_passed or reg_count > 0:
        flow_logger.gate("RegressionReleaseGate", "FAILED", f"Critical passed: {reg_passed}, Regressions: {reg_count}")
        proposal_id = state["proposal_id"]
        session_id = state.get("session_id") or state.get("thread_id") or proposal_id
        tracer = get_improvement_tracer(proposal_id=proposal_id, session_id=session_id)
        tracer.log_node_execution("verify_regression", "REGRESSION_FAILED", {"reg_count": reg_count})
        tracer.flush()
        return {
            "lifecycle_status": "REGRESSION_FAILED",
            "current_stage": "GATE_FAILED",
        }

    flow_logger.gate("RegressionReleaseGate", "PASSED", "Zero regressions detected across test suite")
    return {
        "lifecycle_status": "ADMIN_REVIEW",
        "current_stage": "READY_FOR_ADMIN",
    }


def administrator_gate(state: WorkflowImprovementState) -> dict[str, Any]:
    """Human gate interrupt requiring named Workflow Administrator approval."""
    if state.get("lifecycle_status") != "ADMIN_REVIEW":
        return {}

    proposal = state["proposal"] or {}
    proposal_id = state["proposal_id"]
    session_id = state.get("session_id") or state.get("thread_id") or proposal_id
    tracer = get_improvement_tracer(proposal_id=proposal_id, session_id=session_id)

    interrupt_payload = {
        "type": "WORKFLOW_ADMINISTRATOR_APPROVAL",
        "proposal_id": proposal_id,
        "session_id": session_id,
        "candidate_version": state["candidate_version"],
        "pattern_summary": proposal.get("pattern_summary"),
        "target_type": proposal.get("target_type"),
        "allowed_actions": ["ACTIVATE", "REJECT"],
    }
    tracer.log_interrupt("WORKFLOW_ADMINISTRATOR_APPROVAL", interrupt_payload)
    flow_logger.interrupt(
        interrupt_type="WORKFLOW_ADMINISTRATOR_APPROVAL",
        role="Workflow Administrator",
        question=f"Activate candidate version '{state['candidate_version']}'?",
        allowed_actions=["ACTIVATE", "REJECT"],
    )

    human_response = interrupt(interrupt_payload)
    return {"pending_human_action": human_response}


def activate_or_reject(state: WorkflowImprovementState) -> dict[str, Any]:
    """Process administrator decision deterministically with rollback preservation."""
    action = state.get("pending_human_action") or {}
    action_type = action.get("action")
    admin_id = action.get("administrator_id")
    proposal_id = state["proposal_id"]
    session_id = state.get("session_id") or state.get("thread_id") or proposal_id
    tracer = get_improvement_tracer(proposal_id=proposal_id, session_id=session_id, user_id=admin_id)

    flow_logger.resume(
        user_id=admin_id or "admin_unknown",
        role="Workflow Administrator",
        action=action_type or "ACTION",
    )

    if action_type == "ACTIVATE":
        if not admin_id:
            raise ValueError("Named Workflow Administrator ID is required for activation.")

        act_res = activate_workflow_version(state["candidate_version"], administrator_id=admin_id)
        tracer.log_node_execution("activate_or_reject", "ACTIVATED", {"version": state["candidate_version"]})

        rollback_ver = global_policy_manager.rollback_version or "v1.0.0"
        flow_logger.gate(
            "PolicyActivationGate",
            "ACTIVATED",
            f"Active Version: {state['candidate_version']} | Rollback Version: {rollback_ver}",
        )
        tracer.flush()
        return {
            "active_version": act_res.get("active_version", state["candidate_version"]),
            "rollback_version": rollback_ver,
            "lifecycle_status": "ACTIVATED",
            "current_stage": "ACTIVATED",
            "human_action_history": [action],
        }

    tracer.flush()
    return {
        "lifecycle_status": "REJECTED",
        "current_stage": "REJECTED",
        "human_action_history": [action],
    }


def create_improvement_graph(checkpointer=None):
    """Build and compile the Workflow Improvement LangGraph."""
    workflow = StateGraph(WorkflowImprovementState)

    workflow.add_node("load_feedback", load_feedback)
    workflow.add_node("run_workflow_improvement_analyst", run_workflow_improvement_analyst)
    workflow.add_node("create_candidate", create_candidate)
    workflow.add_node("run_regression", run_regression)
    workflow.add_node("verify_regression", verify_regression)
    workflow.add_node("administrator_gate", administrator_gate)
    workflow.add_node("activate_or_reject", activate_or_reject)

    workflow.add_edge(START, "load_feedback")
    workflow.add_edge("load_feedback", "run_workflow_improvement_analyst")
    workflow.add_edge("run_workflow_improvement_analyst", "create_candidate")
    workflow.add_edge("create_candidate", "run_regression")
    workflow.add_edge("run_regression", "verify_regression")

    # If regression failed, route directly to END; otherwise to administrator_gate
    def route_post_regression(state: WorkflowImprovementState) -> str:
        if state.get("lifecycle_status") == "REGRESSION_FAILED":
            return END
        return "administrator_gate"

    workflow.add_conditional_edges("verify_regression", route_post_regression, {"administrator_gate": "administrator_gate", END: END})
    workflow.add_edge("administrator_gate", "activate_or_reject")
    workflow.add_edge("activate_or_reject", END)

    cp = checkpointer if checkpointer is not None else get_checkpointer()
    return workflow.compile(checkpointer=cp)
