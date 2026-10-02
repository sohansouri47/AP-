"""Centralized Financial Policies, Tolerances, Approval Matrices, and Version Management.

Defines:
- APPolicy: Versioned financial rules, tolerance thresholds, allowed currencies, and mappings
- PolicyManager: Manages active, staged candidate, and historical policy versions
- Global policy accessor for deterministic MCP tools and LangGraph orchestration
"""

from __future__ import annotations

import copy
import time
from typing import Any
from pydantic import BaseModel, Field


class APPolicy(BaseModel):
    """Declarative AP financial policy and governance rules."""
    version: str = "v1.0.0"
    description: str = "Default baseline AP policy"
    effective_date: str = "2026-01-01"
    
    # Currency and math controls
    allowed_currencies: set[str] = Field(default_factory=lambda: {"USD", "EUR", "GBP", "CAD"})
    arithmetic_tolerance: float = 0.01
    
    # 3-Way Matching Tolerances
    price_tolerance_pct: float = 0.0      # 0% price variance allowed
    quantity_tolerance_pct: float = 0.0   # 0% quantity variance allowed
    
    # Approval Authority Thresholds
    finance_director_threshold: float = 10000.00  # Invoices above $10,000 require Finance Director
    standard_approver_role: str = "Finance Approver"
    senior_approver_role: str = "Finance Director"
    
    # Human Review & Governance
    min_feedback_events_threshold: int = 2        # Minimum corrections before proposing changes
    max_allowed_regressions: int = 0              # Zero final-decision regressions allowed
    require_named_admin_for_activation: bool = True
    
    # Bounded Vendor Configurations
    vendor_sku_mappings: dict[str, dict[str, int]] = Field(default_factory=dict)
    supplier_aliases: dict[str, str] = Field(default_factory=dict)
    
    # Check Definitions
    mandatory_check_ids: list[str] = Field(
        default_factory=lambda: [
            "CHK_FILE_DUP",
            "CHK_SUPPLIER_RES",
            "CHK_BIZ_DUP",
            "CHK_REMIT_CHANGE",
            "CHK_ARITHMETIC",
            "CHK_DATES_CURR",
            "CHK_PO_IDENT",
            "CHK_PO_HEADER",
            "CHK_PO_LINES",
            "CHK_PO_REMAIN",
            "CHK_PO_TOL",
            "CHK_APP_ROUTE",
        ]
    )
    conditional_check_ids: list[str] = Field(default_factory=lambda: ["CHK_NO_PO_POL"])


DEFAULT_POLICY_V1 = APPolicy(
    version="v1.0.0",
    description="Standard Production Baseline Policy",
    effective_date="2026-01-01",
)


class PolicyManager:
    """Manages active, candidate, and historical policy versions."""

    def __init__(self, initial_policy: APPolicy | None = None):
        self._active_policy = initial_policy or copy.deepcopy(DEFAULT_POLICY_V1)
        self._history: dict[str, APPolicy] = {self._active_policy.version: copy.deepcopy(self._active_policy)}
        self._candidates: dict[str, APPolicy] = {}
        self._rollback_version: str | None = None

    @property
    def active_policy(self) -> APPolicy:
        return self._active_policy

    @property
    def rollback_version(self) -> str | None:
        return self._rollback_version

    def get_policy(self, version: str) -> APPolicy | None:
        return self._history.get(version) or self._candidates.get(version)

    def stage_candidate_policy(
        self,
        candidate_version: str,
        diff_payload: dict[str, Any],
        target_type: str,
    ) -> APPolicy:
        """Create an inactive candidate policy version incorporating proposed bounded changes."""
        candidate = copy.deepcopy(self._active_policy)
        candidate.version = candidate_version
        candidate.description = f"Candidate improvement targeting {target_type}"

        if target_type == "PO_LINE_MAPPING":
            # Apply SKU line mappings
            sku_map = diff_payload.get("sku_map", {})
            vendor = diff_payload.get("vendor", "default")
            if vendor not in candidate.vendor_sku_mappings:
                candidate.vendor_sku_mappings[vendor] = {}
            candidate.vendor_sku_mappings[vendor].update(sku_map)

        elif target_type == "SUPPLIER_ALIAS":
            aliases = diff_payload.get("aliases", {})
            candidate.supplier_aliases.update(aliases)

        self._candidates[candidate_version] = candidate
        return candidate

    def activate_policy(self, candidate_version: str, administrator_id: str) -> APPolicy:
        """Activate a staged candidate version with administrative audit trail and rollback retention."""
        if not administrator_id:
            raise ValueError("Named Workflow Administrator ID is required for policy activation.")

        candidate = self._candidates.get(candidate_version)
        if not candidate:
            # Fallback create if not pre-staged
            candidate = copy.deepcopy(self._active_policy)
            candidate.version = candidate_version

        # Retain current active version as the rollback target
        self._rollback_version = self._active_policy.version
        self._active_policy = candidate
        self._history[candidate_version] = copy.deepcopy(candidate)
        return self._active_policy

    def rollback_policy(self, target_version: str, administrator_id: str) -> APPolicy:
        """Revert active policy to a previously retained historical version."""
        if not administrator_id:
            raise ValueError("Named Workflow Administrator ID is required for rollback.")

        target = self._history.get(target_version)
        if not target:
            raise KeyError(f"Historical policy version '{target_version}' not found for rollback.")

        self._active_policy = copy.deepcopy(target)
        return self._active_policy


# Global singleton policy manager
global_policy_manager = PolicyManager()


def get_active_policy() -> APPolicy:
    """Retrieve the currently active financial policy."""
    return global_policy_manager.active_policy


def activate_policy(candidate_version: str, administrator_id: str) -> APPolicy:
    """Activate a candidate policy version."""
    return global_policy_manager.activate_policy(candidate_version, administrator_id)


def rollback_policy(target_version: str, administrator_id: str) -> APPolicy:
    """Roll back to a historical policy version."""
    return global_policy_manager.rollback_policy(target_version, administrator_id)
