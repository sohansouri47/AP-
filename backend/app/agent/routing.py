"""Routing Logic and Gates for Invoice and Improvement LangGraphs."""

from __future__ import annotations

from typing import Literal
from app.agent.state import APEmployeeState


def route_outcome_decision(state: APEmployeeState) -> Literal["human_gate", "finalize_run"]:
    """Determine next node based on verified outcome status."""
    status = state.get("lifecycle_status")
    if status in ("READY_FOR_APPROVAL", "NEEDS_ATTENTION"):
        return "human_gate"
    return "finalize_run"


def route_human_action(state: APEmployeeState) -> Literal["finalize_run", "run_ap_employee"]:
    """Determine next step after human action is applied.
    
    If action is approval/rejection or blocked, proceed to finalize_run.
    If action resolves an exception (e.g. PO clarification), rerun affected checks.
    """
    history = state.get("human_action_history") or []
    if not history:
        return "finalize_run"

    last_action = history[-1]
    action_type = last_action.get("action")

    if action_type in ("APPROVE", "REJECT", "CANCEL"):
        return "finalize_run"

    # Operator provided exception resolution -> re-execute controls
    return "run_ap_employee"

