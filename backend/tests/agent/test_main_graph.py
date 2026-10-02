"""Tests for the parent AP Employee LangGraph orchestration and extensibility."""

import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import create_invoice_graph
from app.agent.mcp_tools import global_check_registry


def test_happy_path_orchestration_to_approval():
    """Verify happy-path invoice runs through the graph, pauses at Finance Approval, and completes."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    run_id = "test-happy-run-1"
    config = {"configurable": {"thread_id": run_id}}

    # 1. Run initial execution
    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "invoice_reference": "inv-happy-001",
        "lifecycle_status": "START",
        "human_action_history": [],
        "workflow_version": "v1.0.0",
        "registry_version": "v1.0.0",
        "dataset_version": "v1.0.0",
    }

    # Execute until interrupt
    result = graph.invoke(initial_state, config=config)

    # State should be interrupted at human_gate for FINANCE_APPROVAL
    state = graph.get_state(config)
    assert state.next == ("human_gate",)
    assert len(state.tasks) > 0
    interrupt_info = state.tasks[0].interrupts[0].value
    assert interrupt_info["type"] == "FINANCE_APPROVAL"
    assert interrupt_info["required_role"] == "Finance Approver"

    # 2. Resume with authorized Finance Approver action
    resume_payload = {
        "action": "APPROVE",
        "role": "Finance Approver",
        "user_id": "finance_lead_1",
        "decision_revision": 1,
    }
    final_res = graph.invoke(Command(resume=resume_payload), config=config)

    # Verify completion and posting package
    assert final_res["current_stage"] == "COMPLETED"
    assert final_res["lifecycle_status"] in ("POSTING_PACKAGE_READY", "APPROVED")
    assert final_res["posting_package"] is not None
    assert final_res["posting_package"]["invoice_number"] == "INV-2026-001"
    assert final_res["posting_package"]["total_amount"] == 1080.00


def test_extensibility_new_mcp_check_no_graph_change():
    """Verify adding a new MCP check and registry entry requires zero graph topology changes."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    new_check_called = False

    def check_vendor_sanctions() -> dict:
        nonlocal new_check_called
        new_check_called = True
        return {
            "check_id": "CHK_VENDOR_SANCTIONS",
            "status": "PASSED",
            "message": "Vendor cleared global sanctions screening",
            "raw_output": {"screened": True},
        }

    # Dynamically register the new check in global registry
    global_check_registry.register_check(
        check_id="CHK_VENDOR_SANCTIONS",
        tool_name="check_vendor_sanctions",
        tool_callable=check_vendor_sanctions,
        execution_order=14,
        mandatory=True,
        applicability_reason="OFAC and international sanctions screening",
    )

    run_id = "test-extensibility-run-1"
    config = {"configurable": {"thread_id": run_id}}

    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "invoice_reference": "inv-happy-001",
        "lifecycle_status": "START",
        "human_action_history": [],
        "workflow_version": "v1.0.0",
        "registry_version": "v1.0.0",
        "dataset_version": "v1.0.0",
    }

    # Execute graph WITHOUT any recompilation or graph topology alteration
    graph.invoke(initial_state, config=config)

    state = graph.get_state(config)
    assert state.next == ("human_gate",)
    completed_checks = state.values["control_report"]["completed_check_ids"]
    assert "CHK_VENDOR_SANCTIONS" in completed_checks
    assert new_check_called is True
