"""Database initialization and baseline seeding for Accounts Payable Enterprise Data Layer."""

from __future__ import annotations

import json
import logging
from pathlib import Path
import psycopg
from psycopg.rows import dict_row

from app.db.connection import DATABASE_URL, get_db_connection

logger = logging.getLogger("ap_db.init")


def initialize_database(drop_existing: bool = False) -> None:
    """Apply DDL schema and seed baseline enterprise datasets."""
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    ddl_sql = schema_path.read_text()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            if drop_existing:
                logger.info("Dropping existing tables for clean schema re-creation...")
                cur.execute("""
                    DROP TABLE IF EXISTS audit_logs CASCADE;
                    DROP TABLE IF EXISTS workflow_proposals CASCADE;
                    DROP TABLE IF EXISTS review_feedback CASCADE;
                    DROP TABLE IF EXISTS workflow_versions CASCADE;
                    DROP TABLE IF EXISTS human_actions CASCADE;
                    DROP TABLE IF EXISTS check_executions CASCADE;
                    DROP TABLE IF EXISTS processing_runs CASCADE;
                    DROP TABLE IF EXISTS invoice_documents CASCADE;
                    DROP TABLE IF EXISTS invoice_lines CASCADE;
                    DROP TABLE IF EXISTS invoices CASCADE;
                    DROP TABLE IF EXISTS purchase_order_lines CASCADE;
                    DROP TABLE IF EXISTS purchase_orders CASCADE;
                    DROP TABLE IF EXISTS supplier_bank_accounts CASCADE;
                    DROP TABLE IF EXISTS suppliers CASCADE;
                """)

            logger.info("Applying PostgreSQL Enterprise DDL schema...")
            cur.execute(ddl_sql)

            # Seed Baseline Data
            logger.info("Seeding baseline enterprise master records...")

            # 1. Suppliers
            cur.execute("""
                INSERT INTO suppliers (supplier_id, name, legal_name, tax_id, status, payment_terms, currency)
                VALUES
                    ('SUPP-001', 'Acme Industrial Supplies LLC', 'Acme Industrial Supplies LLC', 'US-XX-9876543', 'ACTIVE', 'NET30', 'USD'),
                    ('SUPP-002', 'Globex Corp', 'Globex International Corporation', 'US-YY-1234567', 'ACTIVE', 'NET30', 'USD'),
                    ('SUPP-003', 'Vandelay Industries', 'Vandelay Latex Manufacturing Inc', 'US-ZZ-5566778', 'ACTIVE', 'NET45', 'USD'),
                    ('SUPP-004', 'Initech Software Systems', 'Initech LLC', 'US-AA-1122334', 'ACTIVE', 'NET30', 'USD')
                ON CONFLICT (supplier_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    tax_id = EXCLUDED.tax_id;
            """)

            # 2. Supplier Bank Accounts (Safe ref IDs, encrypted at rest full number, masked last 4)
            cur.execute("""
                INSERT INTO supplier_bank_accounts (bank_account_ref_id, supplier_id, bank_name, routing_number, account_number_encrypted, account_last4, currency, is_primary)
                VALUES
                    ('BANK-REF-SUPP-001-01', 'SUPP-001', 'JPMorgan Chase Bank', '021000021', 'ENC_JPM_7894561234321', '4321', 'USD', TRUE),
                    ('BANK-REF-SUPP-002-01', 'SUPP-002', 'Wells Fargo Bank NA', '121000358', 'ENC_WF_11223344558765', '8765', 'USD', TRUE),
                    ('BANK-REF-SUPP-003-01', 'SUPP-003', 'Citibank NA', '026009593', 'ENC_CITI_99887766551111', '1111', 'USD', TRUE)
                ON CONFLICT (bank_account_ref_id) DO NOTHING;
            """)

            # 3. Purchase Orders
            cur.execute("""
                INSERT INTO purchase_orders (po_number, supplier_id, buyer_entity, status, currency, total_amount, billed_amount, remaining_amount, issued_date)
                VALUES
                    ('PO-9001', 'SUPP-001', 'Acme Operations Corp', 'APPROVED', 'USD', 5000.00, 0.00, 5000.00, '2026-08-01'),
                    ('PO-2001', 'SUPP-002', 'Acme Operations Corp', 'APPROVED', 'USD', 3000.00, 0.00, 3000.00, '2026-08-15'),
                    ('PO-2002', 'SUPP-002', 'Acme Operations Corp', 'APPROVED', 'USD', 10000.00, 0.00, 10000.00, '2026-09-01'),
                    ('PO-8888', 'SUPP-003', 'Acme Operations Corp', 'APPROVED', 'USD', 2500.00, 500.00, 2000.00, '2026-07-20')
                ON CONFLICT (po_number) DO UPDATE SET
                    remaining_amount = EXCLUDED.remaining_amount,
                    status = EXCLUDED.status;
            """)

            # 4. Purchase Order Lines
            cur.execute("""
                -- Clear lines for idempotency
                DELETE FROM purchase_order_lines WHERE po_number IN ('PO-9001', 'PO-2001', 'PO-2002', 'PO-8888');

                INSERT INTO purchase_order_lines (po_number, line_number, sku, description, quantity, unit_price, line_total, billed_quantity, remaining_quantity)
                VALUES
                    ('PO-9001', 1, 'SKU-IND-100', 'Standard service unit', 5.0, 1000.00, 5000.00, 0.0, 5.0),
                    ('PO-2001', 1, 'SKU-CLD-201', 'Cloud hosting package', 2.0, 1200.00, 2400.00, 0.0, 2.0),
                    ('PO-2001', 2, 'SKU-SUP-202', 'Support add-on', 1.0, 600.00, 600.00, 0.0, 1.0),
                    ('PO-2002', 1, 'SKU-ENT-301', 'Enterprise consulting retainer', 1.0, 10000.00, 10000.00, 0.0, 1.0),
                    ('PO-8888', 1, 'SKU-LTX-001', 'Latex sample parts', 5.0, 100.00, 500.00, 5.0, 0.0);
            """)

            # 5. Baseline Workflow Version (v1.0.0 Active)
            policy_payload = {
                "version": "v1.0.0",
                "arithmetic_tolerance": 0.05,
                "price_tolerance_pct": 1.0,
                "qty_tolerance_pct": 5.0,
                "non_po_threshold": 2500.0,
                "auto_approve_threshold": 5000.0,
                "discrepancy_action": "ROUTE_FOR_APPROVAL",
                "rules": {
                    "require_po": True,
                    "check_duplicates": True,
                    "verify_remittance": True,
                },
            }
            cur.execute("""
                INSERT INTO workflow_versions (version, registry_version, is_active, rollback_target_version, policy_payload, change_summary, activated_by, activated_at)
                VALUES
                    ('v1.0.0', 'v1.0.0', TRUE, NULL, %s, 'Initial baseline production financial policy', 'system', NOW())
                ON CONFLICT (version) DO UPDATE SET
                    is_active = TRUE,
                    policy_payload = EXCLUDED.policy_payload;
            """, (json.dumps(policy_payload),))

            # 6. Prior Posted Invoices (Historical baseline for business duplicate detection)
            cur.execute("""
                INSERT INTO invoices (invoice_number, supplier_id, po_number, invoice_date, due_date, subtotal, tax_amount, total_amount, currency, lifecycle_status, posting_package_id, posted_at)
                VALUES
                    ('INV-DUP-999', 'SUPP-003', 'PO-8888', '2026-09-01', '2026-10-01', 500.00, 40.00, 540.00, 'USD', 'POSTED', 'PKG-POST-999', '2026-09-02 10:00:00+00')
                ON CONFLICT (supplier_id, invoice_number) DO NOTHING;
            """)

            # 7. Baseline Reviewer Feedback (For Improvement Subagent)
            cur.execute("""
                INSERT INTO review_feedback (feedback_id, reviewer_id, field_corrected, prior_value, corrected_value, comment, status)
                VALUES
                    ('FB-001', 'alice_reviewer', 'po_line_mapping', '{"line_index": 0}'::jsonb, '{"line_index": 1}'::jsonb, 'Line SKU A100 always maps to PO Line 1', 'OPEN'),
                    ('FB-002', 'bob_operator', 'po_line_mapping', '{"line_index": 0}'::jsonb, '{"line_index": 1}'::jsonb, 'Line SKU A100 mapped to PO Line 1 manually', 'OPEN')
                ON CONFLICT (feedback_id) DO NOTHING;
            """)

    logger.info("Database schema initialized and baseline data seeded successfully.")


def print_database_status() -> None:
    """Print count of records in all primary tables."""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            tables = [
                "suppliers",
                "supplier_bank_accounts",
                "purchase_orders",
                "purchase_order_lines",
                "invoices",
                "invoice_lines",
                "invoice_documents",
                "processing_runs",
                "check_executions",
                "human_actions",
                "workflow_versions",
                "review_feedback",
                "workflow_proposals",
                "audit_logs",
            ]
            print("=" * 65)
            print("POSTGRESQL ENTERPRISE DATA LAYER STATUS (zamp_ap)")
            print("=" * 65)
            for tbl in tables:
                cur.execute(f"SELECT COUNT(*) AS count FROM {tbl};")
                cnt = cur.fetchone()["count"]
                print(f"Table '{tbl}': {cnt} records")
            print("=" * 65)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    initialize_database(drop_existing=False)
    print_database_status()
