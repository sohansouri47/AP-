from typing import Any, Literal
from pydantic import BaseModel, Field


class RequiredCheck(BaseModel):
    check_id: str
    tool_name: str
    execution_order: int
    mandatory: bool
    applicability_reason: str
    policy_version: str


class CheckResult(BaseModel):
    check_id: str
    tool_name: str
    status: Literal["PASSED", "FAILED", "WARNING", "SKIPPED", "REQUIRES_INPUT"]
    message: str
    raw_output: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None


class UnresolvedItem(BaseModel):
    check_id: str
    item_type: str
    description: str
    candidates: list[Any] = Field(default_factory=list)


class DecisionResult(BaseModel):
    status: Literal["READY_FOR_APPROVAL", "NEEDS_ATTENTION", "BLOCKED", "FAILED"]
    reason_code: str
    summary: str
    revision: int = 1
    required_role: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class ControlExecutionReport(BaseModel):
    run_id: str
    registry_version: str
    required_check_ids: list[str]
    completed_check_ids: list[str]
    check_results: list[CheckResult]
    completeness_valid: bool
    missing_checks: list[str]
    decision: DecisionResult | None
    unresolved_items: list[UnresolvedItem] = Field(default_factory=list)


class EvidenceSummary(BaseModel):
    source: str
    field_name: str
    value: Any
    confidence: float = 1.0


class CandidateComparison(BaseModel):
    candidate_id: str
    candidate_name: str
    match_score: float
    key_differences: list[str] = Field(default_factory=list)


class InvestigationResult(BaseModel):
    exception_type: str
    evidence_summary: list[EvidenceSummary] = Field(default_factory=list)
    candidates: list[CandidateComparison] = Field(default_factory=list)
    recommendation: str | None = None
    human_input_required: bool = False
    specific_question: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)
    affected_check_ids: list[str] = Field(default_factory=list)


class ImprovementProposal(BaseModel):
    proposal_id: str
    pattern_summary: str
    supporting_feedback_ids: list[str]
    target_type: Literal[
        "SUPPLIER_ALIAS",
        "PO_LINE_MAPPING",
        "PROMPT_EXAMPLE",
        "SKILL_INSTRUCTION",
        "POLICY_RECOMMENDATION",
    ]
    bounded_diff: dict[str, Any]
    candidate_version: str
    regression_run_id: str | None = None
    critical_tests_passed: bool = False
    regression_count: int = 0
    approval_required: bool = True


class APEmployeeOutcome(BaseModel):
    run_id: str
    status: Literal[
        "READY_FOR_APPROVAL",
        "NEEDS_ATTENTION",
        "BLOCKED",
        "FAILED",
    ]
    control_report: ControlExecutionReport
    investigation_result: InvestigationResult | None = None
    explanation: str
    owner: str
    next_action: str
    human_input_required: bool
