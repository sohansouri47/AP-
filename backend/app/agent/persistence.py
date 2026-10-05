"""Persistence and Checkpointing for AP AI Employee and Improvement Graphs.

Supports:
- PostgresSaver for production PostgreSQL checkpointing across server processes / pods
- In-memory MemorySaver for unit testing isolation
- Thread-level isolation (thread_id = run_id for invoice graph, thread_id = proposal_id for improvement)
"""

from __future__ import annotations

import logging
import os
import psycopg
from typing import Any, Optional
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres import PostgresSaver

from app.db.connection import DATABASE_URL, is_db_reachable

logger = logging.getLogger("ap_agent.persistence")


class CheckpointerManager:
    """Provides checkpointer instances and persistence lifecycle management."""

    def __init__(self, db_uri: str | None = None):
        self.db_uri = db_uri or DATABASE_URL
        self._shared_memory_saver = MemorySaver()
        self._setup_done = False
        self._connection: Optional[psycopg.Connection] = None

    def _get_connection(self) -> psycopg.Connection:
        if self._connection is None or self._connection.closed:
            self._connection = psycopg.connect(self.db_uri, autocommit=True)
        return self._connection

    def setup_tables(self) -> None:
        """Initialize PostgreSQL checkpoint tables (checkpoints, checkpoint_blobs, checkpoint_writes)."""
        if not self._setup_done and is_db_reachable(self.db_uri):
            try:
                conn = self._get_connection()
                saver = PostgresSaver(conn)
                saver.setup()
                self._setup_done = True
                logger.info("PostgreSQL checkpoint schema verified/created.")
            except Exception as e:
                logger.warning(f"Could not setup PostgreSQL checkpoint tables: {e}")

    def get_postgres_saver(self) -> BaseCheckpointSaver:
        """Return a persistent PostgresSaver instance connected to DATABASE_URL."""
        try:
            conn = self._get_connection()
            if not self._setup_done:
                self.setup_tables()
            return PostgresSaver(conn)
        except Exception as e:
            logger.warning(f"Failed to initialize PostgresSaver: {e}. Falling back to MemorySaver.")
            return self._shared_memory_saver

    def get_checkpointer(self, isolated: bool = False) -> BaseCheckpointSaver:
        """Return the appropriate checkpointer.
        
        If isolated=True, returns a fresh MemorySaver (ideal for isolated in-memory unit tests).
        If PostgreSQL is reachable, returns PostgresSaver.
        Otherwise falls back to shared in-memory checkpointer.
        """
        if isolated:
            return MemorySaver()
        if is_db_reachable(self.db_uri):
            return self.get_postgres_saver()
        return self._shared_memory_saver


# Global persistence manager instance
default_checkpointer_manager = CheckpointerManager()


def get_checkpointer(isolated: bool = False) -> BaseCheckpointSaver:
    """Retrieve global checkpointer (PostgresSaver if DB online, MemorySaver otherwise)."""
    return default_checkpointer_manager.get_checkpointer(isolated=isolated)


