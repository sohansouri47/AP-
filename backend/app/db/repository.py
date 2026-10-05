"""Repository functions for Accounts Payable Enterprise Data Layer."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional
import psycopg

from app.db.connection import get_db_connection, get_db_cursor

logger = logging.getLogger("ap_db.repository")


# ---------------------------------------------------------------------
# 1. Supplier / Vendor Master Repository
# ---------------------------------------------------------------------


def resolve_supplier_db(supplier_name: str, tax_id: str = "") -> Optional[dict[str, Any]]:
    """Resolve supplier by Tax ID (exact) or Name (fuzzy / exact)."""
    with get_db_cursor() as cur:
        # 1. Try exact Tax ID match if provided
        if tax_id:
            cur.execute("SELECT * FROM suppliers WHERE tax_id = %s;", (tax_id,))
            row = cur.fetchone()
            if row:
                return {
                    "supplier_id": row["supplier_id"],
                    "supplier_name": row["name"],
                    "tax_id": row["tax_id"],
                    "confidence": 1.0,
                    "matched_by": "tax_id",
                }

        # 2. Try exact name match
        cur.execute("SELECT * FROM suppliers WHERE LOWER(name) = LOWER(%s);", (supplier_name,))
        row = cur.fetchone()
        if row:
            return {
                "supplier_id": row["supplier_id"],
                "supplier_name": row["name"],
                "tax_id": row["tax_id"],
                "confidence": 0.99,
                "matched_by": "exact_name",
            }

        # 3. Fuzzy ILIKE search
        cur.execute(
            "SELECT * FROM suppliers WHERE name ILIKE %s OR legal_name ILIKE %s LIMIT 1;",
            (f"%{supplier_name}%", f"%{supplier_name}%"),
        )
        row = cur.fetchone()
        if row:
            return {
                "supplier_id": row["supplier_id"],
                "supplier_name": row["name"],
                "tax_id": row["tax_id"],
                "confidence": 0.95,
                "matched_by": "fuzzy_name",
            }

        return None


def search_supplier_candidates_db(query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search supplier candidates for ambiguity resolution."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT supplier_id, name, tax_id, status, payment_terms
            FROM suppliers
            WHERE name ILIKE %s OR supplier_id ILIKE %s
            LIMIT %s;
            """,
            (f"%{query}%", f"%{query}%", limit),
        )
        rows = cur.fetchall()
        return [
            {
                "supplier_id": r["supplier_id"],
                "name": r["name"],
                "tax_id": r["tax_id"],
                "status": r["status"],
            }
            for r in rows
        ]


# ---------------------------------------------------------------------
# 2. Banking Remittance Repository (Safe: Masked Last 4 & Ref ID Only)
# ---------------------------------------------------------------------

def verify_supplier_bank_account_db(
    supplier_id: str,
    account_last4: str,
) -> dict[str, Any]:
    """Verify bank account last 4 matches active supplier banking record at rest.
    
    CRITICAL: account_number_encrypted is NEVER fetched or surfaced to caller.
    """
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT bank_account_ref_id, bank_name, account_last4, is_verified, is_primary
            FROM supplier_bank_accounts
            WHERE supplier_id = %s AND account_last4 = %s AND is_verified = TRUE;
            """,
            (supplier_id, account_last4),
        )
        row = cur.fetchone()
        if row:
            return {
                "matched": True,
                "bank_account_ref_id": row["bank_account_ref_id"],
                "bank_name": row["bank_name"],
                "account_last4": row["account_last4"],
            }
        return {"matched": False}


# ---------------------------------------------------------------------
# 3. Purchase Orders Repository
# ---------------------------------------------------------------------

def get_purchase_order_db(po_number: str) -> Optional[dict[str, Any]]:
    """Retrieve PO header and its itemized line schedules."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT po.*, s.name as supplier_name
                FROM purchase_orders po
                JOIN suppliers s ON po.supplier_id = s.supplier_id
                WHERE po.po_number = %s;
                """,
                (po_number,),
            )
            header = cur.fetchone()
            if not header:
                return None

            cur.execute(
                """
                SELECT * FROM purchase_order_lines
                WHERE po_number = %s
                ORDER BY line_number ASC;
                """,
                (po_number,),
            )
            lines = cur.fetchall()

            return {
                "po_number": header["po_number"],
                "supplier_id": header["supplier_id"],
                "supplier_name": header["supplier_name"],
                "status": header["status"],
                "currency": header["currency"],
                "total_amount": float(header["total_amount"]),
                "billed_amount": float(header["billed_amount"]),
                "remaining_amount": float(header["remaining_amount"]),
                "lines": [
                    {
                        "id": str(l["id"]),
                        "line_number": l["line_number"],
                        "sku": l["sku"],
                        "description": l["description"],
                        "quantity": float(l["quantity"]),
                        "unit_price": float(l["unit_price"]),
                        "line_total": float(l["line_total"]),
                        "remaining_quantity": float(l["remaining_quantity"]),
                    }
                    for l in lines
                ],
            }


def get_po_candidates_db(supplier_id: str, amount: float = 0.0) -> list[dict[str, Any]]:
    """Retrieve open, approved PO candidates for a supplier."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT po_number, supplier_id, status, total_amount, remaining_amount, currency
            FROM purchase_orders
            WHERE supplier_id = %s AND status = 'APPROVED'
            ORDER BY po_number ASC;
            """,
            (supplier_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "po_number": r["po_number"],
                "supplier_id": r["supplier_id"],
                "status": r["status"],
                "total_amount": float(r["total_amount"]),
                "remaining_amount": float(r["remaining_amount"]),
                "currency": r["currency"],
            }
            for r in rows
        ]


# ---------------------------------------------------------------------
# 4. Invoices & Duplicate Checks
# ---------------------------------------------------------------------

def check_business_duplicate_db(supplier_id: str, invoice_number: str) -> Optional[dict[str, Any]]:
    """Check if an invoice has already been recorded for this supplier."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, invoice_number, total_amount, lifecycle_status, posting_package_id, posted_at
            FROM invoices
            WHERE supplier_id = %s AND invoice_number = %s;
            """,
            (supplier_id, invoice_number),
        )
        row = cur.fetchone()
        if row:
            return {
                "prior_invoice_id": str(row["id"]),
                "invoice_number": row["invoice_number"],
                "total_amount": float(row["total_amount"]),
                "lifecycle_status": row["lifecycle_status"],
                "posting_package_id": row["posting_package_id"],
                "posted_at": str(row["posted_at"]) if row["posted_at"] else None,
            }
        return None


def check_file_duplicate_db(file_hash_sha256: str) -> Optional[dict[str, Any]]:
    """Check if document file SHA-256 hash already exists in repository."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, file_name, file_hash_sha256, created_at
            FROM invoice_documents
            WHERE file_hash_sha256 = %s;
            """,
            (file_hash_sha256,),
        )
        row = cur.fetchone()
        if row:
            return {
                "document_id": str(row["id"]),
                "file_name": row["file_name"],
                "file_hash_sha256": row["file_hash_sha256"],
                "uploaded_at": str(row["created_at"]),
            }
        return None


def record_invoice_document_db(
    file_name: str,
    file_path: str,
    file_hash_sha256: str,
    file_size_bytes: int,
    mime_type: str = "application/pdf",
) -> str:
    """Record raw uploaded invoice document."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO invoice_documents (file_name, file_path, file_hash_sha256, file_size_bytes, mime_type)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (file_hash_sha256) DO UPDATE SET file_name = EXCLUDED.file_name
            RETURNING id;
            """,
            (file_name, file_path, file_hash_sha256, file_size_bytes, mime_type),
        )
        doc_id = cur.fetchone()["id"]
        return str(doc_id)


def record_posted_invoice_db(
    invoice_number: str,
    supplier_id: str,
    po_number: str | None,
    invoice_date: str,
    subtotal: float,
    tax_amount: float,
    total_amount: float,
    lifecycle_status: str,
    posting_package_id: str,
) -> str:
    """Record final approved and posted invoice."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO invoices (
                invoice_number, supplier_id, po_number, invoice_date,
                subtotal, tax_amount, total_amount, lifecycle_status,
                posting_package_id, posted_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (supplier_id, invoice_number) DO UPDATE SET
                lifecycle_status = EXCLUDED.lifecycle_status,
                posting_package_id = EXCLUDED.posting_package_id,
                posted_at = NOW()
            RETURNING id;
            """,
            (
                invoice_number,
                supplier_id,
                po_number,
                invoice_date,
                subtotal,
                tax_amount,
                total_amount,
                lifecycle_status,
                posting_package_id,
            ),
        )
        inv_id = cur.fetchone()["id"]
        return str(inv_id)


# ---------------------------------------------------------------------
# 5. Processing Runs & Check Executions
# ---------------------------------------------------------------------

def record_processing_run_db(
    run_id: str,
    session_id: str | None,
    workflow_version: str,
    lifecycle_status: str = "START",
) -> None:
    """Create or update a processing run (1:1 with LangGraph thread_id)."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO processing_runs (run_id, session_id, workflow_version, lifecycle_status, started_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (run_id) DO UPDATE SET
                lifecycle_status = EXCLUDED.lifecycle_status;
            """,
            (run_id, session_id, workflow_version, lifecycle_status),
        )


def update_processing_run_db(
    run_id: str,
    lifecycle_status: str,
    completed: bool = False,
    error_details: dict[str, Any] | None = None,
) -> None:
    """Update processing run lifecycle status and completion."""
    with get_db_cursor() as cur:
        if completed:
            cur.execute(
                """
                UPDATE processing_runs
                SET lifecycle_status = %s,
                    completed_at = NOW(),
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000,
                    error_details = %s
                WHERE run_id = %s;
                """,
                (lifecycle_status, json.dumps(error_details) if error_details else None, run_id),
            )
        else:
            cur.execute(
                "UPDATE processing_runs SET lifecycle_status = %s WHERE run_id = %s;",
                (lifecycle_status, run_id),
            )


# ---------------------------------------------------------------------
# 6. Human Actions Repository
# ---------------------------------------------------------------------

def record_human_action_db(
    run_id: str,
    gate_type: str,
    required_role: str,
    actor_user_id: str,
    actor_role: str,
    action: str,
    decision_revision: int,
    reason: str = "",
    action_payload: dict[str, Any] | None = None,
) -> None:
    """Record revision-safe human review / approval."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO human_actions (
                run_id, gate_type, required_role, actor_user_id,
                actor_role, action, decision_revision, reason, action_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            (
                run_id,
                gate_type,
                required_role,
                actor_user_id,
                actor_role,
                action,
                decision_revision,
                reason,
                json.dumps(action_payload or {}),
            ),
        )


# ---------------------------------------------------------------------
# 7. Audit Trail Repository (Append-Only)
# ---------------------------------------------------------------------

def record_audit_log_db(
    run_id: str,
    event_type: str,
    actor: str,
    actor_role: str,
    payload: dict[str, Any],
) -> None:
    """Append immutable audit log entry with SHA-256 payload hash."""
    payload_str = json.dumps(payload, sort_keys=True)
    payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

    with get_db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO audit_logs (run_id, event_type, actor, actor_role, payload, payload_hash)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (run_id, event_type, actor, actor_role, json.dumps(payload), payload_hash),
        )


def get_audit_trail_db(run_id: str) -> list[dict[str, Any]]:
    """Retrieve immutable audit trail for a processing run."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT id, run_id, event_type, actor, actor_role, payload, payload_hash, created_at
            FROM audit_logs
            WHERE run_id = %s
            ORDER BY id ASC;
            """,
            (run_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r["id"],
                "run_id": r["run_id"],
                "event_type": r["event_type"],
                "actor": r["actor"],
                "actor_role": r["actor_role"],
                "payload": r["payload"],
                "payload_hash": r["payload_hash"],
                "timestamp": str(r["created_at"]),
            }
            for r in rows
        ]


# ---------------------------------------------------------------------
# 8. Feedback & Proposals Repository
# ---------------------------------------------------------------------

def get_feedback_events_db(limit: int = 20) -> list[dict[str, Any]]:
    """Retrieve open reviewer feedback items."""
    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT feedback_id, reviewer_id, field_corrected, prior_value, corrected_value, comment, created_at
            FROM review_feedback
            WHERE status = 'OPEN'
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "feedback_id": r["feedback_id"],
                "reviewer_id": r["reviewer_id"],
                "field_corrected": r["field_corrected"],
                "prior_value": r["prior_value"],
                "corrected_value": r["corrected_value"],
                "comment": r["comment"],
                "timestamp": r["created_at"].timestamp() if r["created_at"] else 0.0,
            }
            for r in rows
        ]
