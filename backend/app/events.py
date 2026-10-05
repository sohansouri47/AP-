"""Shared in-memory event bus for SSE live-run tracking.

Isolated here to avoid circular imports between main.py and agent submodules.
"""
from __future__ import annotations

import time
from contextvars import ContextVar
from typing import Any

# Thread-safe (CPython GIL) in-memory stores
EVENT_BUS: dict[str, list[dict[str, Any]]] = {}
RUN_COMPLETE: dict[str, bool] = {}
RUNS_ACTIVE: set[str] = set()  # thread_ids currently being processed by a background task

# ContextVar propagated into asyncio.to_thread worker threads
current_run_id: ContextVar[str] = ContextVar("current_run_id", default="")


def emit_event(thread_id: str, event_type: str, data: dict[str, Any]) -> None:
    """Append a lifecycle event to the in-memory event bus."""
    if not thread_id:
        return
    if thread_id not in EVENT_BUS:
        EVENT_BUS[thread_id] = []
    EVENT_BUS[thread_id].append({
        "event": event_type,
        "thread_id": thread_id,
        "timestamp": time.time(),
        "data": data,
    })
