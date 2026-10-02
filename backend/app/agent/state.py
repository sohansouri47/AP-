import operator
from typing import Annotated, Any, Literal
from langgraph.graph import MessagesState


class APEmployeeState(MessagesState):
    run_id: str
    thread_id: str
    lifecycle_status: str
    current_stage: str
    invoice_reference: str
    extracted_invoice: dict[str, Any] | None
    control_report: dict[str, Any] | None
    investigation_result: dict[str, Any] | None
    decision: dict[str, Any] | None
    explanation: str | None
    pending_human_action: dict[str, Any] | None
    human_action_history: Annotated[list[dict[str, Any]], operator.add]
    workflow_version: str
    registry_version: str
    dataset_version: str
    posting_package: dict[str, Any] | None
    langfuse_trace_id: str | None
    session_id: str | None
    safe_error: dict[str, Any] | None


class WorkflowImprovementState(MessagesState):
    proposal_id: str
    thread_id: str
    lifecycle_status: str
    current_stage: str
    feedback_ids: list[str]
    feedback_records: list[dict[str, Any]]
    proposal: dict[str, Any] | None
    regression_results: dict[str, Any] | None
    regression_passed: bool
    regression_count: int
    pending_human_action: dict[str, Any] | None
    human_action_history: Annotated[list[dict[str, Any]], operator.add]
    candidate_version: str | None
    active_version: str | None
    rollback_version: str | None
    langfuse_trace_id: str | None
    session_id: str | None
    safe_error: dict[str, Any] | None
