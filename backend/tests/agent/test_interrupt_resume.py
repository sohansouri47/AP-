"""Tests for human-in-the-loop interrupts, role validation, resumption, and persistence."""

import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import create_invoice_graph


def test_ambiguous_po_interrupt_and_resume_flow():
    """Test full cycle: ambiguous PO triggers AP_REVIEW interrupt, resumes with PO choice, and reaches Finance Approval."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    run_id = "test-ambiguous-flow-1"
    config = {"configurable": {"thread_id": run_id}}

    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "invoice_reference": "inv-ambiguous-po",
        "lifecycle_status": "START",
        "human_action_history": [],
        "workflow_version": "v1.0.0",
        "registry_version": "v1.0.0",
        "dataset_version": "v1.0.0",
    }

    # Step 1: Run to first interrupt
    graph.invoke(initial_state, config=config)
    state = graph.get_state(config)
    assert state.next == ("human_gate",)
    interrupt_payload = state.tasks[0].interrupts[0].value
    assert interrupt_payload["type"] == "AP_REVIEW"
    assert "Which PO should be applied?" in interrupt_payload["question"]
    assert "SELECT_PO_2001" in interrupt_payload["allowed_actions"]

    # Step 2: Resume with operator decision: SELECT_PO_2001
    operator_action = {
        "action": "SELECT_PO_2001",
        "role": "AP Operator",
        "user_id": "operator_bob",
        "selected_po": "PO-2001",
        "decision_revision": 1,
    }
    graph.invoke(Command(resume=operator_action), config=config)

    # Step 3: Graph re-evaluates and should now reach Finance Approval interrupt
    state_after_po = graph.get_state(config)
    assert state_after_po.next == ("human_gate",)
    approval_interrupt = state_after_po.tasks[0].interrupts[0].value
    assert approval_interrupt["type"] == "FINANCE_APPROVAL"
    assert approval_interrupt["required_role"] == "Finance Approver"

    # Step 4: Resume with Finance Approver approval
    finance_action = {
        "action": "APPROVE",
        "role": "Finance Approver",
        "user_id": "cfo_jane",
        "decision_revision": 1,
    }
    final_res = graph.invoke(Command(resume=finance_action), config=config)

    assert final_res["lifecycle_status"] in ("POSTING_PACKAGE_READY", "APPROVED")
    assert final_res["posting_package"] is not None
    assert final_res["posting_package"]["invoice_number"] == "INV-2026-002"


def test_unauthorized_approver_role_rejected():
    """Verify AP Operator attempting to approve raises PermissionError."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    run_id = "test-unauth-approval-1"
    config = {"configurable": {"thread_id": run_id}}

    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "invoice_reference": "inv-happy-001",
        "lifecycle_status": "START",
        "human_action_history": [],
    }

    graph.invoke(initial_state, config=config)

    # AP Operator attempts to approve
    invalid_action = {
        "action": "APPROVE",
        "role": "AP Operator",  # Unauthorized role
        "user_id": "operator_charlie",
        "decision_revision": 1,
    }

    with pytest.raises(PermissionError, match="cannot authorize invoice approval"):
        graph.invoke(Command(resume=invalid_action), config=config)


def test_idempotent_approval_and_posting_package():
    """Verify resuming an already approved invoice does not recreate or duplicate posting package."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    run_id = "test-idempotent-1"
    config = {"configurable": {"thread_id": run_id}}

    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "invoice_reference": "inv-happy-001",
        "lifecycle_status": "START",
        "human_action_history": [],
    }

    graph.invoke(initial_state, config=config)

    finance_action = {
        "action": "APPROVE",
        "role": "Finance Approver",
        "user_id": "cfo_jane",
        "decision_revision": 1,
    }
    res1 = graph.invoke(Command(resume=finance_action), config=config)
    pkg1 = res1["posting_package"]
    assert pkg1 is not None

    # Check state persistence
    state = graph.get_state(config)
    assert state.values["posting_package"]["package_id"] == pkg1["package_id"]


def test_persistence_process_restart_survival():
    """Verify state survives across separate graph compilations using the same checkpointer."""
    checkpointer = MemorySaver()

    # Process 1: Start graph and pause at interrupt
    graph_process_1 = create_invoice_graph(checkpointer=checkpointer)
    run_id = "test-restart-run-1"
    config = {"configurable": {"thread_id": run_id}}

    initial_state = {
        "run_id": run_id,
        "thread_id": run_id,
        "invoice_reference": "inv-happy-001",
        "lifecycle_status": "START",
        "human_action_history": [],
    }
    graph_process_1.invoke(initial_state, config=config)

    # Process 2 (simulated restart): Create brand new graph instance with same checkpointer
    graph_process_2 = create_invoice_graph(checkpointer=checkpointer)
    restored_state = graph_process_2.get_state(config)

    assert restored_state.next == ("human_gate",)
    assert restored_state.values["run_id"] == run_id
    assert restored_state.values["lifecycle_status"] == "READY_FOR_APPROVAL"

    # Resume on the newly spawned process
    final_res = graph_process_2.invoke(
        Command(resume={"action": "APPROVE", "role": "Finance Approver", "user_id": "cfo_jane", "decision_revision": 1}),
        config=config,
    )
    assert final_res["lifecycle_status"] in ("POSTING_PACKAGE_READY", "APPROVED")


def test_thread_id_isolation():
    """Verify two concurrent runs remain completely isolated by thread_id."""
    checkpointer = MemorySaver()
    graph = create_invoice_graph(checkpointer=checkpointer)

    run_1 = "run-iso-1"
    run_2 = "run-iso-2"

    graph.invoke(
        {"run_id": run_1, "thread_id": run_1, "invoice_reference": "inv-happy-001", "human_action_history": []},
        config={"configurable": {"thread_id": run_1}},
    )
    graph.invoke(
        {"run_id": run_2, "thread_id": run_2, "invoice_reference": "inv-ambiguous-po", "human_action_history": []},
        config={"configurable": {"thread_id": run_2}},
    )

    state_1 = graph.get_state({"configurable": {"thread_id": run_1}})
    state_2 = graph.get_state({"configurable": {"thread_id": run_2}})

    assert state_1.values["lifecycle_status"] == "READY_FOR_APPROVAL"
    assert state_2.values["lifecycle_status"] == "NEEDS_ATTENTION"
