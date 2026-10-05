"""AP AI Employee using the Deep Agents SDK (deepagents.create_deep_agent).

Architecture:
- Main AP Employee: create_deep_agent
  └── control-executor subagent: all 16 control tools + get_required_checks (isolated)
  └── exception-investigator subagent: 7 read-only evidence tools (isolated)
- Workflow Improvement Analyst: create_deep_agent
  └── workflow-improvement-analyst subagent: 5 improvement tools (isolated)

The parent agent calls extract_invoice, then delegates control execution to
control-executor and (if exceptions) exception-investigator. Each subagent
returns a JSON block parsed into typed Pydantic schemas. The Section 14
deterministic parity gate always runs as a final verification step.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from deepagents import create_deep_agent
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.mcp_tools import extract_invoice as mcp_extract_invoice, get_run_context
from app.agent.prompts import MAIN_AP_EMPLOYEE_SYSTEM_PROMPT, WORKFLOW_IMPROVEMENT_SYSTEM_PROMPT
from app.agent.schemas import (
    APEmployeeOutcome,
    CandidateComparison,
    CheckResult,
    ControlExecutionReport,
    DecisionResult,
    EvidenceSummary,
    ImprovementProposal,
    InvestigationResult,
    UnresolvedItem,
)
from app.agent.subagents import (
    get_control_executor_subagent_spec,
    get_exception_investigator_subagent_spec,
    get_workflow_improvement_subagent_spec,
    _wrap_extract_invoice,
)
from app.agent.flow_logger import flow_logger
from app.agent.llm import get_chat_model
from app.agent.observability import TraceObserver

logger = logging.getLogger(__name__)


def _get_model():
    """Return a ChatOpenAI instance locked to the standard Chat Completions API.

    deepagents passes its internal task() tool as type='builtin', which triggers
    langchain_openai to route through /responses instead of /chat/completions.
    use_responses_api=False forces the standard endpoint regardless of tool types.
    """
    callbacks = []
    try:
        from app.main import _lf_handler
        if _lf_handler is not None:
            callbacks.append(_lf_handler)
    except Exception:
        pass
    return get_chat_model(fallback_on_quota=True, use_responses_api=False, callbacks=callbacks or None)


# =====================================================================
# Helpers
# =====================================================================

def _extract_json(content: Any) -> dict | list:
    """Extract JSON from agent message content in any format.

    Handles: plain dict/list, JSON string, markdown code block,
    LangChain content list [{"type":"text","text":"..."}], and
    JSON embedded within prose (finds first { ... } block).
    """
    # Already a parsed object
    if isinstance(content, dict):
        return content
    if isinstance(content, list):
        # LangChain multi-modal content blocks
        if content and isinstance(content[0], dict) and "type" in content[0]:
            parts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
            content = "\n".join(parts)
        else:
            return content

    text = str(content).strip()
    if not text:
        return {}

    # Strategy 1: markdown ```json ... ``` block
    if "```" in text:
        for marker in ("```json", "```"):
            if marker in text:
                try:
                    block = text.split(marker, 1)[-1].split("```")[0].strip()
                    result = json.loads(block)
                    return result
                except Exception:
                    pass

    # Strategy 2: direct JSON parse
    try:
        return json.loads(text)
    except Exception:
        pass

    # Strategy 3: find the outermost JSON object in the text
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    logger.debug("_extract_json: could not parse content (len=%d): %.200s", len(text), text)
    return {}


def _build_tool_call_map(messages: list) -> dict[str, str]:
    """Map tool_call_id -> tool_name from AIMessage tool_calls."""
    mapping: dict[str, str] = {}
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                mapping[tc["id"]] = tc["name"]
    return mapping


def _find_subagent_name(messages: list, tool_call_id: str) -> str:
    """Find which subagent was called for a given task() tool_call_id.

    Tries multiple arg key names since deepagents SDK versions differ.
    """
    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc["id"] == tool_call_id and tc["name"] == "task":
                    args = tc.get("args", {})
                    return (
                        args.get("subagent_name")
                        or args.get("agent")
                        or args.get("name")
                        or args.get("agent_name")
                        or ""
                    )
    return ""


# =====================================================================
# Output Parsers
# =====================================================================

def _parse_control_report(data: dict, run_id: str, policy_version: str) -> ControlExecutionReport:
    """Parse raw subagent JSON dict into a ControlExecutionReport."""
    check_results = []
    for c in data.get("check_results", []):
        if isinstance(c, dict):
            check_results.append(CheckResult(
                check_id=c.get("check_id", ""),
                tool_name=c.get("tool_name", c.get("check_id", "")),
                status=c.get("status", "PASSED"),
                message=c.get("message", ""),
                raw_output=c.get("raw_output", {}),
                error_code=c.get("error_code"),
            ))
    decision_data = data.get("decision")
    decision = DecisionResult(**decision_data) if isinstance(decision_data, dict) and decision_data else None
    unresolved_items = [UnresolvedItem(**u) for u in data.get("unresolved_items", []) if isinstance(u, dict)]
    completed_ids = data.get("completed_check_ids") or [c.check_id for c in check_results]
    required_ids = data.get("required_check_ids") or completed_ids

    return ControlExecutionReport(
        run_id=run_id,
        registry_version=policy_version,
        required_check_ids=required_ids,
        completed_check_ids=completed_ids,
        check_results=check_results,
        completeness_valid=bool(data.get("completeness_valid", False)),
        missing_checks=data.get("missing_checks", []),
        decision=decision,
        unresolved_items=unresolved_items,
    )


def _parse_investigation_result(data: dict) -> InvestigationResult:
    """Parse raw subagent JSON dict into an InvestigationResult."""
    evidence = [
        EvidenceSummary(**e) for e in data.get("evidence_summary", []) if isinstance(e, dict)
    ]
    candidates = [
        CandidateComparison(**c) for c in data.get("candidates", []) if isinstance(c, dict)
    ]
    return InvestigationResult(
        exception_type=data.get("exception_type", "AMBIGUITY"),
        evidence_summary=evidence,
        candidates=candidates,
        recommendation=data.get("recommendation"),
        human_input_required=bool(data.get("human_input_required", True)),
        specific_question=data.get("specific_question"),
        allowed_actions=data.get("allowed_actions", []),
        affected_check_ids=data.get("affected_check_ids", []),
    )


def _parse_improvement_proposal(data: dict) -> ImprovementProposal:
    """Parse raw subagent JSON dict into an ImprovementProposal."""
    return ImprovementProposal(
        proposal_id=data.get("proposal_id", "PROP-unknown"),
        pattern_summary=data.get("pattern_summary", ""),
        supporting_feedback_ids=data.get("supporting_feedback_ids", []),
        target_type=data.get("target_type", "PO_LINE_MAPPING"),
        bounded_diff=data.get("bounded_diff", {}),
        candidate_version=data.get("candidate_version", "v1.1.0"),
        regression_run_id=data.get("regression_run_id"),
        critical_tests_passed=bool(data.get("critical_tests_passed", False)),
        regression_count=int(data.get("regression_count", 0)),
        approval_required=bool(data.get("approval_required", True)),
    )


# =====================================================================
# Main AP Employee Deep Agent
# =====================================================================

def build_ap_employee_deep_agent():
    """Create the Main AP Employee as a Deep Agent with specialist subagents."""
    return create_deep_agent(
        model=_get_model(),
        tools=[_wrap_extract_invoice(mcp_extract_invoice), get_run_context],
        subagents=[
            get_control_executor_subagent_spec(),
            get_exception_investigator_subagent_spec(),
        ],
        system_prompt=MAIN_AP_EMPLOYEE_SYSTEM_PROMPT,
    )


def run_ap_employee_deep_agent(
    run_id: str,
    invoice_reference: str,
    policy_version: str = "v1.0.0",
    human_action: dict[str, Any] | None = None,
    tracer: TraceObserver | None = None,
    force_skip_checks: list[str] | None = None,
    frozen_extracted_invoice: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], APEmployeeOutcome]:
    """Invoke the AP Employee Deep Agent and parse its output.

    Flow:
      1. Deep agent calls extract_invoice → ToolMessage
      2. Deep agent delegates to control-executor subagent → task() ToolMessage
      3. (Optional) Deep agent delegates to exception-investigator → task() ToolMessage
      4. Parse each ToolMessage into typed schemas
      5. Fallback to deterministic harness if any parse step fails
      6. Section 14 parity gate always runs
    """
    from app.agent.main_agent import verify_and_sanitize_outcome

    flow_logger.agent_start(
        "MainAPEmployee-DeepAgent",
        "run_ap_employee_deep_agent",
        f"Invoice: {invoice_reference} | Policy: {policy_version}",
    )

    # Pre-extract invoice data so it's always available for the deterministic fallback.
    # On resume (frozen_extracted_invoice provided), skip re-extraction: GPT-4o vision
    # is non-deterministic and can return different field values on a second pass,
    # which would corrupt checks like CHK_ARITHMETIC that compare subtotal+tax vs total.
    pre_extracted: dict[str, Any] = {}
    if frozen_extracted_invoice:
        pre_extracted = frozen_extracted_invoice
        logger.info("Using frozen extracted invoice (resume run): invoice=%s supplier=%s total=%s po=%s",
                    pre_extracted.get("invoice_number"),
                    pre_extracted.get("supplier_name"),
                    pre_extracted.get("total_amount"),
                    pre_extracted.get("po_number"))
    else:
        try:
            from app.agent.extractor import extract_invoice_from_document
            _res = extract_invoice_from_document(invoice_reference, run_id=run_id, tracer=tracer)
            pre_extracted = _res.get("extracted_data", {})
            logger.info("Pre-extraction done: invoice=%s supplier=%s total=%s po=%s",
                        pre_extracted.get("invoice_number"),
                        pre_extracted.get("supplier_name"),
                        pre_extracted.get("total_amount"),
                        pre_extracted.get("po_number"))
        except Exception as exc:
            logger.warning("Pre-extraction failed (will rely on deep agent): %s", exc)

    parts = [
        f"Process invoice reference: {invoice_reference}",
        f"Run ID: {run_id}",
        f"Policy Version: {policy_version}",
    ]
    if pre_extracted:
        parts.append(f"Extracted invoice data: {json.dumps(pre_extracted)}")
    if human_action:
        parts.append(f"Human resolution already applied: {json.dumps(human_action)}")
        selected_po = human_action.get("selected_po")
        if selected_po:
            parts.append(f"Use PO number {selected_po} for all PO-related checks.")
    if force_skip_checks:
        parts.append(f"Skip these check IDs: {force_skip_checks}")
    task_message = "\n".join(parts)

    agent = build_ap_employee_deep_agent()
    messages: list = []
    try:
        result = agent.invoke(
            {"messages": [("human", task_message)]},
            config={"recursion_limit": 50},
        )
        messages = result.get("messages", [])
        logger.info("Deep agent finished | message count: %d", len(messages))
    except Exception as exc:
        logger.warning("Deep agent invocation failed, falling back: %s", exc)

    tool_call_map = _build_tool_call_map(messages)

    # Seed from pre-extraction; overridden below if deep agent returns a richer result
    extracted_invoice: dict[str, Any] = dict(pre_extracted)
    control_report_data: dict | None = None
    investigation_data: dict | None = None

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        tool_name = tool_call_map.get(msg.tool_call_id, "")
        logger.debug("ToolMessage tool=%s content_type=%s content_preview=%.200s",
                     tool_name, type(msg.content).__name__, str(msg.content)[:200])

        if tool_name == "extract_invoice":
            content = _extract_json(msg.content)
            extracted_invoice = content.get("extracted_data", content) if isinstance(content, dict) else {}
            logger.info("Deep agent extract_invoice: number=%s supplier=%s total=%s",
                        extracted_invoice.get("invoice_number"),
                        extracted_invoice.get("supplier_name"),
                        extracted_invoice.get("total_amount"))
            # extraction_completed is already emitted live by _wrap_extract_invoice when the tool returns

        elif tool_name == "task":
            subagent = _find_subagent_name(messages, msg.tool_call_id)
            parsed = _extract_json(msg.content)
            logger.info("Deep agent task() subagent=%r parsed_keys=%s",
                        subagent, list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__)

            if "control" in subagent.lower() and isinstance(parsed, dict):
                control_report_data = parsed
            elif ("exception" in subagent.lower() or "investigat" in subagent.lower()) and isinstance(parsed, dict):
                investigation_data = parsed

    # --- Control report ---
    if control_report_data:
        try:
            control_report = _parse_control_report(control_report_data, run_id, policy_version)
            logger.info("Deep agent control report parsed: decision=%s checks=%d",
                        control_report.decision.status if control_report.decision else "NONE",
                        len(control_report.check_results))
            flow_logger.tool_call(
                "MainAPEmployee-DeepAgent", "control-executor", "SUCCESS",
                f"Decision: {control_report.decision.status if control_report.decision else 'NONE'}",
            )
            if tracer:
                tracer.log_subagent_delegation("control-executor", task_message,
                                               control_report.model_dump(), ["control_execution"])
        except Exception as exc:
            logger.warning("control report parse failed, using deterministic harness: %s", exc)
            control_report = _run_deterministic_controls(
                run_id, invoice_reference, extracted_invoice, policy_version, tracer, force_skip_checks, human_action
            )
    else:
        logger.warning("No control report from deep agent subagent, using deterministic harness.")
        control_report = _run_deterministic_controls(
            run_id, invoice_reference, extracted_invoice, policy_version, tracer, force_skip_checks, human_action
        )

    # --- Investigation result ---
    investigation_result: InvestigationResult | None = None
    if investigation_data:
        try:
            investigation_result = _parse_investigation_result(investigation_data)
            logger.info("Deep agent investigation parsed: human_input=%s",
                        investigation_result.human_input_required)
            flow_logger.tool_call(
                "MainAPEmployee-DeepAgent", "exception-investigator", "SUCCESS",
                f"Human input required: {investigation_result.human_input_required}",
            )
            if tracer:
                tracer.log_subagent_delegation("exception-investigator", task_message,
                                               investigation_result.model_dump(), ["exception_investigation"])
        except Exception as exc:
            logger.warning("investigation result parse failed: %s", exc)

    # Run deterministic investigator if deep agent didn't produce one but there are unresolved items
    if not investigation_result and control_report.unresolved_items:
        from app.agent.subagents import investigate_exceptions
        try:
            investigation_result = investigate_exceptions(
                run_id=run_id,
                control_report=control_report,
                extracted_invoice=extracted_invoice,
                tracer=tracer,
            )
        except Exception as exc:
            logger.warning("Deterministic investigate_exceptions failed: %s", exc)

    # Section 14 parity gate — always runs
    outcome = verify_and_sanitize_outcome(run_id, control_report, investigation_result)

    if tracer:
        tracer.log_final_decision(outcome.model_dump())

    flow_logger.outcome(outcome.status, outcome.owner, outcome.explanation)
    return extracted_invoice, outcome


def _run_deterministic_controls(
    run_id: str,
    invoice_reference: str,
    extracted_invoice: dict[str, Any],
    policy_version: str,
    tracer: TraceObserver | None,
    force_skip_checks: list[str] | None,
    human_action: dict[str, Any] | None = None,
) -> ControlExecutionReport:
    """Run controls via the deterministic harness (fallback or override)."""
    from app.agent.subagents import execute_controls
    from app.events import EVENT_BUS, current_run_id
    # If the deep agent's wrapped tools already emitted control_completed events live,
    # suppress re-emission from the deterministic fallback to avoid duplicates.
    tid = current_run_id.get("")
    already_emitted = tid and any(
        e.get("event") == "control_completed" for e in EVENT_BUS.get(tid, [])
    )
    return execute_controls(
        run_id=run_id,
        invoice_reference=invoice_reference,
        extracted_invoice=extracted_invoice,
        policy_version=policy_version,
        tracer=tracer,
        skip_checks=force_skip_checks,
        human_action=human_action,
        suppress_live_events=bool(already_emitted),
    )


# =====================================================================
# Workflow Improvement Deep Agent
# =====================================================================

def build_workflow_improvement_deep_agent():
    """Create the Workflow Improvement Analyst as a Deep Agent."""
    return create_deep_agent(
        model=_get_model(),
        subagents=[get_workflow_improvement_subagent_spec()],
        system_prompt=WORKFLOW_IMPROVEMENT_SYSTEM_PROMPT,
    )


def run_workflow_improvement_deep_agent(
    feedback_ids: list[str],
    candidate_version: str = "v1.1.0",
    force_regression: bool = False,
    tracer: TraceObserver | None = None,
) -> ImprovementProposal:
    """Invoke the Workflow Improvement Deep Agent and parse its ImprovementProposal output."""
    flow_logger.agent_start(
        "WorkflowImprovementAnalyst-DeepAgent",
        "run_workflow_improvement_deep_agent",
        f"Feedback: {feedback_ids} | Candidate: {candidate_version}",
    )

    task_message = (
        f"Analyze reviewer feedback and draft a bounded improvement proposal.\n"
        f"Feedback IDs: {feedback_ids}\n"
        f"Candidate Version: {candidate_version}\n"
        + ("Force regression failure for testing.\n" if force_regression else "")
    )

    agent = build_workflow_improvement_deep_agent()
    messages: list = []
    try:
        result = agent.invoke(
            {"messages": [("human", task_message)]},
            config={"recursion_limit": 30},
        )
        messages = result.get("messages", [])
    except Exception as exc:
        logger.warning("Workflow improvement deep agent failed, using deterministic harness: %s", exc)

    tool_call_map = _build_tool_call_map(messages)
    proposal_data: dict | None = None

    for msg in messages:
        if not isinstance(msg, ToolMessage):
            continue
        tool_name = tool_call_map.get(msg.tool_call_id, "")
        if tool_name == "task":
            parsed = _extract_json(msg.content)
            if isinstance(parsed, dict) and "proposal_id" in parsed:
                proposal_data = parsed
                break

    # Fallback to last AI message
    if not proposal_data:
        last_ai = next((m for m in reversed(messages) if isinstance(m, AIMessage)), None)
        if last_ai:
            parsed = _extract_json(last_ai.content)
            if isinstance(parsed, dict) and parsed:
                proposal_data = parsed

    if proposal_data:
        try:
            proposal = _parse_improvement_proposal(proposal_data)
            if force_regression:
                proposal = proposal.model_copy(update={"critical_tests_passed": False, "regression_count": 1})
            flow_logger.subagent_end("workflow-improvement-analyst", "PROPOSAL_DRAFTED",
                                     f"Proposal: {proposal.proposal_id}")
            if tracer:
                tracer.log_subagent_delegation("workflow-improvement-analyst", task_message,
                                               proposal.model_dump(), ["workflow_improvement"])
            return proposal
        except Exception as exc:
            logger.warning("Deep agent proposal parse failed, using deterministic harness: %s", exc)

    from app.agent.subagents import analyze_workflow_improvement
    return analyze_workflow_improvement(feedback_ids, candidate_version, force_regression, tracer)
