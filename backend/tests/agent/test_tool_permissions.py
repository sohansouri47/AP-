"""Tests for role allowlists, privilege boundaries, and forbidden tool enforcement."""

import pytest
from app.agent.mcp_tools import (
    verify_tool_permission,
    MAIN_AGENT_ALLOWLIST,
    CONTROL_EXECUTOR_ALLOWLIST,
    EXCEPTION_INVESTIGATOR_ALLOWLIST,
    WORKFLOW_IMPROVEMENT_ALLOWLIST,
    DETERMINISTIC_ONLY_ALLOWLIST,
)


def test_main_agent_forbidden_tools():
    """Verify Main AP AI Employee cannot invoke financial or activation tools."""
    for forbidden in ["authorize_approval", "activate_workflow_version", "check_arithmetic"]:
        with pytest.raises(PermissionError, match="Security Violation"):
            verify_tool_permission("main_agent", forbidden)


def test_control_executor_forbidden_tools():
    """Verify Control Executor cannot activate workflow versions or authorize approval."""
    for forbidden in ["activate_workflow_version", "rollback_workflow_version", "authorize_approval"]:
        with pytest.raises(PermissionError, match="Security Violation"):
            verify_tool_permission("control-executor", forbidden)


def test_exception_investigator_forbidden_tools():
    """Verify Exception Investigator cannot select final decision or approve."""
    for forbidden in ["select_final_decision", "authorize_approval", "activate_workflow_version"]:
        with pytest.raises(PermissionError, match="Security Violation"):
            verify_tool_permission("exception-investigator", forbidden)


def test_workflow_improvement_analyst_forbidden_tools():
    """Verify Improvement Analyst cannot self-activate proposals."""
    for forbidden in ["activate_workflow_version", "rollback_workflow_version", "authorize_approval"]:
        with pytest.raises(PermissionError, match="Security Violation"):
            verify_tool_permission("workflow-improvement-analyst", forbidden)


def test_deterministic_only_tools_restricted_to_app():
    """Verify privileged deterministic tools can only be invoked by deterministic application context."""
    for tool_name in DETERMINISTIC_ONLY_ALLOWLIST:
        # Calling as general agent roles fails
        for role in ["main_agent", "control-executor", "exception-investigator", "workflow-improvement-analyst"]:
            with pytest.raises(PermissionError):
                verify_tool_permission(role, tool_name)

        # Calling as deterministic application succeeds
        verify_tool_permission("deterministic_application", tool_name)
