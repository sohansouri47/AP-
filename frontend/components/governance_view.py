"""Governance Component.

Surfaces continuous workflow improvement, version management, and regression gates.
"""

from __future__ import annotations

import json
from typing import Any
import streamlit as st

from api_client import BackendAPIClient


def render_governance_page(client: BackendAPIClient):
    """Render the Workflow Governance and Continuous Improvement view."""
    st.markdown("### 🏛️ Financial Policy & Workflow Governance")
    st.markdown(
        """
        The Accounts Payable AI Employee enforces **bounded autonomous self-improvement**. 
        Changes to mapping rules, tolerances, or supplier aliases are never directly deployed; 
        they are staged as versioned candidates and must pass a 50-test golden regression gate before named Administrator sign-off.
        """
    )

    c1, c2, c3 = st.columns(3)
    c1.metric("Active Policy Version", "v1.0.0", delta="Production Active")
    c2.metric("Golden Regression Gate", "50 / 50 Passing", delta="0 Violations")
    c3.metric("Rollback Target", "v1.0.0", delta="Known-Good")

    st.markdown("---")

    col_left, col_right = st.columns([1, 1])

    with col_left:
        st.markdown("#### 🔄 Continuous Improvement Lifecycle")
        st.markdown(
            """
            1. **Reviewer Feedback Ingestion:** Captures AP operator corrections (e.g. SKU line mappings).
            2. **Pattern Synthesis:** `WorkflowImprovementAnalyst` groups recurring corrections (frequency ≥ 2).
            3. **Candidate Staging:** Produces bounded declarative diff (e.g. candidate `v1.1.0`).
            4. **Regression Gate Execution:** Validates candidate against golden test dataset without touching production state.
            5. **Administrator Sign-off:** Requires named administrator authentication (`activate_workflow_version`).
            """
        )

        st.markdown("##### 📝 Operator Feedback Log (Recent Corrections)")
        mock_feedback = [
            {
                "feedback_id": "FB-001",
                "invoice_number": "INV-2026-002",
                "user_id": "ap_operator_sarah",
                "target_type": "PO_LINE_MAPPING",
                "correction": "Mapped Router SKU A100 to PO-2001 Line 1",
            },
            {
                "feedback_id": "FB-002",
                "invoice_number": "INV-2026-005",
                "user_id": "ap_operator_marcus",
                "target_type": "PO_LINE_MAPPING",
                "correction": "Mapped Router SKU A100 to PO-2001 Line 1",
            },
        ]
        st.dataframe(mock_feedback, use_container_width=True, hide_index=True)

    with col_right:
        st.markdown("#### 🧪 Staged Candidate Evaluation")
        st.markdown(
            """
            <div style="background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                    <span style="font-weight: 700; color: #1e293b;">Candidate: <code>v1.1.0-staged</code></span>
                    <span style="background: #fef3c7; color: #92400e; font-size: 0.72rem; font-weight: 700; padding: 2px 8px; border-radius: 9999px;">STAGED (INACTIVE)</span>
                </div>
                <div style="font-size: 0.8rem; color: #475569; margin-bottom: 8px;">
                    Target: <code>PO_LINE_MAPPING</code> — Automate SKU A100 line assignment based on verified operator feedback PAT-001.
                </div>
                <pre style="background: #0f172a; color: #f8fafc; padding: 10px; border-radius: 6px; font-size: 0.75rem;">
{
  "target_type": "PO_LINE_MAPPING",
  "diff": {
    "sku_map": {
      "A100": 1
    }
  },
  "candidate_version": "v1.1.0"
}
                </pre>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
        st.markdown("##### 🛡️ Regression Safety Verification")
        st.markdown(
            """
            - **Dataset Version:** `v1-golden` (50 synthetic edge cases)
            - **Critical Security Controls:** 100% Passed (Double payment, bank fraud, tax tampering)
            - **Regression Delta:** 0 regressions detected
            """
        )
