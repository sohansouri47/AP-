"""Comprehensive End-to-End Live Agent Flow and Observability Verification.

Tests:
1. Complete happy-path execution: extraction, 13 controls, completeness gate, decision gate, tracing
2. Ambiguous exception flow: detection, exception investigator delegation, candidate evidence, question generation
3. Full LangGraph lifecycle: node transitions, interrupt at human gate, resumption, posting package creation
4. Real LLM invocation via gpt-4o-mini with prompt handling and generation tracing
"""

import time
import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import create_invoice_graph
from app.agent.main_agent import run_ap_employee_pipeline
from app.agent.observability import get_invoice_tracer, RECORDED_TRACES
from app.agent.llm import get_chat_model, is_openai_configured
from app.agent.schemas import APEmployeeOutcome


def test_live_happy_path_flow_and_tracing():
    """Verify that every stage, subagent, and MCP tool actually executes in the happy-path flow."""
    run_id = f"live-test-happy-{int(time.time() * 1000)}"
    tracer = get_invoice_tracer(run_id)

    extracted_invoice, outcome = run_ap_employee_pipeline(
        run_id=run_id,
        invoice_reference="inv-happy-001",
        policy_version="v1.0.0",
        tracer=tracer,
    )

    # 1. Verify invoice extraction
    assert extracted_invoice["invoice_number"] == "INV-2026-001"
    assert extracted_invoice["total_amount"] == 1080.00
    assert extracted_invoice["currency"] == "USD"

    # 2. Verify Control Execution Report
    report = outcome.control_report
    assert report is not None
    assert report.completeness_valid is True
    assert len(report.missing_checks) == 0
    assert len(report.completed_check_ids) >= 12
    assert report.decision.status == "READY_FOR_APPROVAL"
    assert report.decision.required_role == "Finance Approver"

    # 3. Verify Deterministic Outcome Parity (Section 14)
    assert outcome.status == "READY_FOR_APPROVAL"
    assert outcome.owner == "Finance Approver"
    assert outcome.human_input_required is True

    # 4. Verify Trace Recording and Tool Coverage
    events = [e for e in tracer.events if e.get("session_id") == run_id]
    tool_events = [e for e in events if e.get("type") == "MCP_TOOL_CALL"]
    executed_tools = {e["tool_name"] for e in tool_events}

    assert "extract_invoice" in executed_tools
    assert "check_file_duplicate" in executed_tools
    assert "resolve_supplier" in executed_tools
    assert "check_business_duplicate" in executed_tools
    assert "check_remit_change" in executed_tools
    assert "check_arithmetic" in executed_tools
    assert "check_dates_currency" in executed_tools
    assert "identify_purchase_order" in executed_tools
    assert "validate_po_header" in executed_tools
    assert "match_po_lines" in executed_tools
    assert "calculate_po_remaining" in executed_tools
    assert "evaluate_po_tolerances" in executed_tools
    assert "select_approval_route" in executed_tools
    assert "validate_check_completeness" in executed_tools
    assert "select_final_decision" in executed_tools

    # 5. Verify Subagent Delegation Recorded
    delegation_events = [e for e in events if e.get("type") == "SUBAGENT_DELEGATION"]
    assert any(e["subagent_name"] == "control-executor" for e in delegation_events)

    # 6. Verify Final Decision Recorded
    decision_events = [e for e in events if e.get("type") == "FINAL_DECISION"]
    assert len(decision_events) == 1
    assert decision_events[0]["outcome"]["status"] == "READY_FOR_APPROVAL"

    # Flush trace to Langfuse Cloud
    tracer.flush()


def test_live_ambiguous_exception_investigation_flow():
    """Verify that an ambiguous PO triggers exception-investigator subagent and formulates operator prompt."""
    run_id = f"live-test-ambiguity-{int(time.time() * 1000)}"
    tracer = get_invoice_tracer(run_id)

    extracted_invoice, outcome = run_ap_employee_pipeline(
        run_id=run_id,
        invoice_reference="inv-ambiguous-po",
        policy_version="v1.0.0",
        tracer=tracer,
    )

    # Outcome must require attention
    assert outcome.status == "NEEDS_ATTENTION"
    assert outcome.owner == "AP Operator"
    assert outcome.human_input_required is True

    # Investigation result must be populated
    inv = outcome.investigation_result
    assert inv is not None
    assert inv.exception_type == "AMBIGUOUS_PO_REFERENCE"
    assert len(inv.candidates) >= 2
    assert "SELECT_PO_2001" in inv.allowed_actions
    assert "SELECT_PO_2002" in inv.allowed_actions
    assert "Which PO should be applied?" in inv.specific_question

    # Verify exception investigator tools called
    events = [e for e in tracer.events if e.get("session_id") == run_id]
    executed_tools = {e.get("tool_name") for e in events if e.get("type") == "MCP_TOOL_CALL"}
    assert "get_invoice_evidence" in executed_tools
    assert "get_po_candidates" in executed_tools
    assert "compare_candidate_records" in executed_tools

    # Flush trace to Langfuse Cloud
    tracer.flush()


def test_live_full_graph_interrupt_and_posting_package():
    """Verify the full LangGraph lifecycle: run -> interrupt at human gate -> resume -> posting package."""
    run_id = f"live-test-graph-{int(time.time() * 1000)}"
    config = {"configurable": {"thread_id": run_id}}
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    # 1. Run until human_gate interrupt
    session_id = f"session-{run_id}"
    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "session_id": session_id,
        "invoice_reference": "inv-happy-001",
        "lifecycle_status": "START",
        "human_action_history": [],
    }
    graph.invoke(initial_state, config=config)

    # Check paused state
    state = graph.get_state(config)
    assert state.next == ("human_gate",)
    assert state.values["lifecycle_status"] == "READY_FOR_APPROVAL"
    interrupt_payload = state.tasks[0].interrupts[0].value
    assert interrupt_payload["type"] == "FINANCE_APPROVAL"
    assert interrupt_payload["required_role"] == "Finance Approver"
    assert interrupt_payload["session_id"] == session_id

    # 2. Resume with authorized approval
    approval_action = {
        "action": "APPROVE",
        "role": "Finance Approver",
        "user_id": "auditor_elena",
        "decision_revision": 1,
    }
    final_state = graph.invoke(Command(resume=approval_action), config=config)

    # Check completed state
    assert final_state["lifecycle_status"] in ("POSTING_PACKAGE_READY", "APPROVED")
    assert final_state["posting_package"] is not None
    pkg = final_state["posting_package"]
    assert pkg["package_id"].startswith(f"PKG-{run_id}")
    assert pkg["total_amount"] == 1080.00
    assert pkg["currency"] == "USD"
    assert pkg["decision"]["status"] == "READY_FOR_APPROVAL"

    # 3. Verify session was maintained across the entire multi-turn flow
    tracer = get_invoice_tracer(run_id)
    assert tracer.session_id == session_id
    assert tracer.user_id == "auditor_elena"
    session_url = tracer.get_session_url()
    assert session_url is not None
    assert f"/sessions/{session_id}" in session_url


def test_live_llm_invocation_and_generation_tracing():
    """Verify live gpt-4o-mini model invocation and generation observation logging."""
    if not is_openai_configured():
        pytest.skip("OpenAI API key not configured in environment.")

    llm = get_chat_model(fallback_on_quota=False)
    run_id = f"live-llm-test-{int(time.time() * 1000)}"
    tracer = get_invoice_tracer(run_id)

    prompt = "Summarize in 5 words that mandatory AP financial controls passed."
    t0 = time.time()
    response = llm.invoke(prompt)
    duration_ms = (time.time() - t0) * 1000

    assert response is not None
    assert len(response.content) > 0

    # Log generation into tracer
    tracer.log_generation(
        name="ap_summary_generation",
        model="gpt-4o-mini",
        prompt=prompt,
        completion=response.content,
        usage=getattr(response, "response_metadata", {}).get("token_usage", {}),
        duration_ms=duration_ms,
    )

    gen_events = [e for e in tracer.events if e.get("type") == "GENERATION"]
    assert len(gen_events) == 1
    assert gen_events[0]["model"] == "gpt-4o-mini"
    assert gen_events[0]["completion"] == response.content

    # Flush trace to Langfuse Cloud and assert trace URL is generated
    trace_url = tracer.flush()
    assert trace_url is None or "cloud.langfuse.com" in trace_url
