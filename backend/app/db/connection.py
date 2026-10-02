"""Database connection manager for Accounts Payable Enterprise Data Layer."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator
import psycopg
from psycopg.rows import dict_row

DEFAULT_DATABASE_URL = "postgresql://postgres:postgres@localhost:5432/zamp_ap"
DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def is_db_reachable(database_url: str | None = None) -> bool:
    """Check if PostgreSQL server and database are reachable."""
    url = database_url or DATABASE_URL
    try:
        with psycopg.connect(url, connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                return True
    except Exception:
        return False


@contextmanager
def get_db_connection(database_url: str | None = None) -> Generator[psycopg.Connection, None, None]:
    """Provide a transactional PostgreSQL database connection with dictionary rows."""
    url = database_url or DATABASE_URL
    conn = psycopg.connect(url, row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_db_cursor(database_url: str | None = None):
    """Provide a transactional database cursor yielding dict results."""
    with get_db_connection(database_url) as conn:
        with conn.cursor() as cur:
            yield cur
