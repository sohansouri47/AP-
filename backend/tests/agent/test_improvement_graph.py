"""Tests for the Workflow Improvement Graph, regression release gates, and admin approval."""

import pytest
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver

from app.agent.graph import create_improvement_graph


def test_improvement_graph_happy_path_activation():
    """Verify improvement graph groups repeated feedback, passes regressions, and activates with admin approval."""
    checkpointer = MemorySaver()
    graph = create_improvement_graph(checkpointer=checkpointer)

    proposal_id = "test-prop-001"
    config = {"configurable": {"thread_id": proposal_id}}

    initial_state = {
        "proposal_id": proposal_id,
        "thread_id": proposal_id,
        "feedback_ids": ["FB-001", "FB-002"],
        "human_action_history": [],
    }

    # Step 1: Run to administrator gate interrupt
    graph.invoke(initial_state, config=config)
    state = graph.get_state(config)

    assert state.next == ("administrator_gate",)
    interrupt_payload = state.tasks[0].interrupts[0].value
    assert interrupt_payload["type"] == "WORKFLOW_ADMINISTRATOR_APPROVAL"
    assert interrupt_payload["candidate_version"] == "v1.1.0"

    # Step 2: Resume with named Workflow Administrator approval
    admin_action = {
        "action": "ACTIVATE",
        "administrator_id": "admin_sarah",
    }
    final_res = graph.invoke(Command(resume=admin_action), config=config)

    assert final_res["lifecycle_status"] == "ACTIVATED"
    assert final_res["active_version"] == "v1.1.0"
    assert final_res["rollback_version"] == "v1.0.0"


def test_improvement_regression_blocks_activation():
    """Verify that any detected regression halts the proposal and never reaches administrator gate."""
    checkpointer = MemorySaver()
    graph = create_improvement_graph(checkpointer=checkpointer)

    proposal_id = "test-prop-regression"
    config = {"configurable": {"thread_id": proposal_id}}

    initial_state = {
        "proposal_id": proposal_id,
        "thread_id": proposal_id,
        "feedback_ids": ["FB-001", "FB-002"],
        "human_action_history": [],
        "safe_error": {"force_regression": True},  # Force a regression failure in test suite
    }

    final_res = graph.invoke(initial_state, config=config)

    # Graph should terminate without reaching administrator_gate
    assert final_res["lifecycle_status"] == "REGRESSION_FAILED"
    assert final_res["regression_count"] > 0
    state = graph.get_state(config)
    assert state.next == ()  # Reached END directly
