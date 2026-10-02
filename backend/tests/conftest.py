"""Pytest configuration and test database isolation fixtures."""

import logging
import pytest
from app.db.connection import is_db_reachable, get_db_cursor

logger = logging.getLogger("pytest.db_isolation")


def _clean_test_db():
    if not is_db_reachable():
        return
    try:
        with get_db_cursor() as cur:
            # 1. Clear check executions and human actions from prior test runs
            cur.execute("DELETE FROM check_executions WHERE run_id LIKE 'test-%' OR run_id LIKE 'run-%';")
            cur.execute("DELETE FROM human_actions WHERE run_id LIKE 'test-%' OR run_id LIKE 'run-%';")
            # 2. Clear test checkpoints
            cur.execute("DELETE FROM checkpoint_writes WHERE thread_id LIKE 'test-%' OR thread_id LIKE 'run-%';")
            cur.execute("DELETE FROM checkpoint_blobs WHERE thread_id LIKE 'test-%' OR thread_id LIKE 'run-%';")
            cur.execute("DELETE FROM checkpoints WHERE thread_id LIKE 'test-%' OR thread_id LIKE 'run-%';")
            # 3. Clear test processing runs
            cur.execute("DELETE FROM processing_runs WHERE run_id LIKE 'test-%' OR run_id LIKE 'run-%';")
            # 4. Disconnect any invoice references in processing_runs or review_feedback
            cur.execute("UPDATE processing_runs SET invoice_id = NULL WHERE invoice_id IS NOT NULL;")
            cur.execute("UPDATE review_feedback SET invoice_id = NULL WHERE invoice_id IS NOT NULL;")
            # 4. Remove invoice lines for non-baseline invoices
            cur.execute("""
                DELETE FROM invoice_lines 
                WHERE invoice_id IN (SELECT id FROM invoices WHERE invoice_number != 'INV-DUP-999');
            """)
            # 5. Remove any invoices posted during tests, preserving the seeded historical duplicate INV-DUP-999
            cur.execute("DELETE FROM invoices WHERE invoice_number != 'INV-DUP-999';")
    except Exception as e:
        logger.warning(f"Failed to clean test database: {e}")


@pytest.fixture(autouse=True)
def isolate_test_database():
    """Ensure each test runs with a clean state against the live PostgreSQL database."""
    _clean_test_db()
    yield
    _clean_test_db()
