"""Tests proving specialist subagent delegation and role responsibilities."""

import pytest
from app.agent.main_agent import run_ap_employee_pipeline
from app.agent.subagents import (
    execute_controls,
    investigate_exceptions,
    get_control_executor_subagent_spec,
    get_exception_investigator_subagent_spec,
)
from app.agent.observability import TraceObserver


def test_main_agent_delegates_to_control_executor():
    """Verify main agent delegates controls to Control Executor, which calls get_required_checks first."""
    tracer = TraceObserver(trace_name="test-trace", session_id="run-subagent-1")
    extracted_inv, outcome = run_ap_employee_pipeline(
        run_id="run-subagent-1",
        invoice_reference="inv-happy-001",
        tracer=tracer,
    )

    # Verify delegation event
    delegations = [e for e in tracer.events if e["type"] == "SUBAGENT_DELEGATION"]
    assert any(d["subagent_name"] == "control-executor" for d in delegations)

    # Verify get_required_checks was called first
    mcp_calls = [e for e in tracer.events if e["type"] == "MCP_TOOL_CALL"]
    assert len(mcp_calls) > 0
    control_calls = [c for c in mcp_calls if c["caller"] == "control-executor"]
    assert control_calls[0]["tool_name"] == "get_required_checks"


def test_exception_investigator_delegation_on_ambiguity():
    """Verify unresolved cases delegate to Exception Investigator and produce specific question."""
    tracer = TraceObserver(trace_name="test-trace", session_id="run-subagent-2")
    extracted_inv, outcome = run_ap_employee_pipeline(
        run_id="run-subagent-2",
        invoice_reference="inv-ambiguous-po",
        tracer=tracer,
    )

    # Verify exception-investigator delegation was triggered
    delegations = [e for e in tracer.events if e["type"] == "SUBAGENT_DELEGATION"]
    assert any(d["subagent_name"] == "exception-investigator" for d in delegations)

    assert outcome.status == "NEEDS_ATTENTION"
    assert outcome.investigation_result is not None
    assert outcome.investigation_result.human_input_required is True
    assert "Which PO should be applied?" in (outcome.investigation_result.specific_question or "")
    assert len(outcome.investigation_result.candidates) >= 2


def test_declarative_subagent_specs():
    """Verify declarative specs conform to Deep Agents SDK requirements."""
    spec_ctrl = get_control_executor_subagent_spec()
    assert spec_ctrl["name"] == "control-executor"
    assert "get_required_checks" in spec_ctrl["system_prompt"]

    spec_inv = get_exception_investigator_subagent_spec()
    assert spec_inv["name"] == "exception-investigator"
    assert "read-only evidence" in spec_inv["system_prompt"]
