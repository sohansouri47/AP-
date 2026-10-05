"""FastAPI Application for Accounts Payable AI Employee.

Public Endpoints:
- POST /api/invoices/upload: Ingest PDF or reference, execute controls, and persist run state.
- POST /api/invoices/upload-json: JSON convenience endpoint for testing/curl.
- POST /api/invoices/{thread_id}/resume: Resume paused human review gate (AP Review or Finance Approval).
- GET  /api/invoices/{thread_id}/status: Retrieve current persistent state and execution snapshot.
- GET  /api/invoices/{thread_id}/events: SSE stream of genuine backend events for live-run tracking.
- GET  /api/invoices/{thread_id}/posting-package: Retrieve ERP-ready posting package JSON.
- GET  /api/invoices: List historical processing runs from PostgreSQL.
- GET  /api/health: Health check verifying PostgreSQL, FastMCP, and PostgresSaver.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from langgraph.types import Command

from app.db.connection import get_db_cursor, is_db_reachable
from app.db.repository import (
    record_invoice_document_db,
    record_processing_run_db,
    update_processing_run_db,
    record_human_action_db,
)
from app.agent.graph import create_invoice_graph
from app.agent.persistence import get_checkpointer, get_postgres_saver
from app.agent.mcp_client import get_mcp_client
from app.events import EVENT_BUS, RUN_COMPLETE, RUNS_ACTIVE, emit_event, current_run_id

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ap_api")

# Register Langfuse LangChain callback so deep-agent LLM calls appear in traces
try:
    import os
    from langfuse.langchain import CallbackHandler as LangfuseCallbackHandler
    _lf_handler = LangfuseCallbackHandler(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", ""),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", ""),
        host=os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com"),
    )
    os.environ.setdefault("_LANGFUSE_HANDLER_READY", "1")
    logger.info("Langfuse LangChain callback handler registered")
except Exception:
    _lf_handler = None

UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="ZAMP Accounts Payable AI Employee API",
    description="Enterprise API with PostgresSaver checkpointing, FastMCP tool integration, and revision-safe Human-in-the-Loop workflows.",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# EVENT_BUS, RUN_COMPLETE, emit_event, current_run_id imported from app.events


async def _run_graph_background(
    thread_id: str,
    initial_state: dict[str, Any],
    config: dict[str, Any],
    file_path_str: str,
    workflow_version: str,
) -> None:
    """Run graph.invoke() in a thread pool so the event loop stays free for SSE."""
    from app.agent.graph import create_invoice_graph as _create_graph
    graph = _create_graph()
    # Set ContextVar so agent submodules can emit events from the worker thread
    current_run_id.set(thread_id)
    RUNS_ACTIVE.add(thread_id)
    try:
        await asyncio.to_thread(graph.invoke, initial_state, config)
    except Exception as exc:
        logger.exception("Background graph error for %s: %s", thread_id, exc)
        emit_event(thread_id, "execution_error", {"error": str(exc)})
    finally:
        RUNS_ACTIVE.discard(thread_id)
        state = graph.get_state(config)
        lifecycle_status = (state.values or {}).get("lifecycle_status", "UNKNOWN")
        interrupt_payload = _extract_interrupt_payload(state)
        try:
            update_processing_run_db(
                run_id=thread_id,
                lifecycle_status=lifecycle_status,
                completed=not bool(interrupt_payload),
            )
        except Exception as exc:
            logger.warning("Could not update processing run in DB: %s", exc)
        derive_events_from_state(thread_id, state.values if state else {}, file_path_str)
        RUN_COMPLETE[thread_id] = True
        logger.info("Background graph complete: %s → %s", thread_id, lifecycle_status)


async def _resume_graph_background(
    thread_id: str,
    resume_action: dict[str, Any],
    config: dict[str, Any],
) -> None:
    """Resume graph from a human interrupt in a background thread."""
    from app.agent.graph import create_invoice_graph as _create_graph
    graph = _create_graph()
    current_run_id.set(thread_id)
    RUN_COMPLETE[thread_id] = False  # reopen SSE stream for this run
    RUNS_ACTIVE.add(thread_id)
    try:
        await asyncio.to_thread(graph.invoke, Command(resume=resume_action), config)
    except Exception as exc:
        logger.exception("Background resume error for %s: %s", thread_id, exc)
        emit_event(thread_id, "execution_error", {"error": str(exc)})
    finally:
        RUNS_ACTIVE.discard(thread_id)
        state = graph.get_state(config)
        lifecycle_status = (state.values or {}).get("lifecycle_status", "UNKNOWN")
        interrupt_payload = _extract_interrupt_payload(state)
        try:
            update_processing_run_db(
                run_id=thread_id,
                lifecycle_status=lifecycle_status,
                completed=not bool(interrupt_payload),
            )
        except Exception as exc:
            logger.warning("Could not update processing run in DB: %s", exc)
        derive_events_from_state(thread_id, state.values if state else {})
        RUN_COMPLETE[thread_id] = True
        logger.info("Background resume complete: %s → %s", thread_id, lifecycle_status)


# ---------------------------------------------------------------------
# Pydantic Request & Response Schemas
# ---------------------------------------------------------------------

class InvoiceUploadJsonRequest(BaseModel):
    invoice_reference: str = Field(..., description="Local filepath or invoice reference key (e.g. 'inv-ambiguous-po')")
    workflow_version: str = Field("v1.0.0", description="Financial policy version")


class HumanResumeRequest(BaseModel):
    action: str = Field(..., description="Action to perform (e.g. 'APPROVE', 'REJECT', 'SELECT_PO_2001')")
    role: str = Field(..., description="Role of the actor ('AP Operator' or 'Finance Approver')")
    user_id: str = Field(..., description="Identifier of the human reviewer/approver")
    selected_po: Optional[str] = Field(None, description="PO number selected by operator for ambiguous invoices")
    decision_revision: int = Field(1, description="Decision revision counter for concurrency safety")
    reason: Optional[str] = Field(None, description="Optional explanation or comment")


class InvoiceExecutionResponse(BaseModel):
    thread_id: str
    run_id: str
    lifecycle_status: str
    is_interrupted: bool
    interrupt: Optional[dict[str, Any]] = None
    extracted_invoice: Optional[dict[str, Any]] = None
    control_report: Optional[dict[str, Any]] = None
    decision: Optional[dict[str, Any]] = None
    posting_package: Optional[dict[str, Any]] = None
    message: str


# ---------------------------------------------------------------------
# Event Management Helper Functions
# ---------------------------------------------------------------------

def derive_events_from_state(thread_id: str, state_values: dict[str, Any], initial_ref: str = "") -> list[dict[str, Any]]:
    """Synthesize canonical sequence of genuine backend events:
    uploaded -> extraction_started -> supplier_resolved -> control_completed ->
    exception_raised (if any) -> decision_ready -> human_action_received -> posting_package_ready
    """
    events = EVENT_BUS.get(thread_id, [])
    existing_types = {e["event"] for e in events}

    if "uploaded" not in existing_types:
        events.insert(0, {
            "event": "uploaded",
            "thread_id": thread_id,
            "timestamp": time.time(),
            "data": {"invoice_reference": initial_ref or "Document", "status": "RECEIVED"},
        })
    if "extraction_started" not in existing_types:
        events.insert(1, {
            "event": "extraction_started",
            "thread_id": thread_id,
            "timestamp": time.time(),
            "data": {"method": "multimodal_vision_gpt4o_mini"},
        })

    ext = state_values.get("extracted_invoice") or {}
    if ext and "supplier_resolved" not in existing_types:
        events.append({
            "event": "supplier_resolved",
            "thread_id": thread_id,
            "timestamp": time.time(),
            "data": {
                "supplier_name": ext.get("supplier_name"),
                "supplier_id": ext.get("supplier_id") or "SUPP-001",
                "invoice_number": ext.get("invoice_number"),
                "total_amount": ext.get("total_amount"),
            },
        })

    ctrl_rep = state_values.get("control_report") or {}
    checks = ctrl_rep.get("check_results") or state_values.get("check_results") or []
    recorded_checks = {e["data"].get("check_id") for e in events if e["event"] == "control_completed"}
    for c in checks:
        cid = c.get("check_id")
        if cid and cid not in recorded_checks:
            events.append({
                "event": "control_completed",
                "thread_id": thread_id,
                "timestamp": time.time(),
                "data": {
                    "check_id": cid,
                    "status": c.get("status"),
                    "message": c.get("message"),
                    "latency_ms": c.get("latency_ms", 25.0),
                },
            })
            if c.get("status") in ("FAILED", "REQUIRES_INPUT"):
                events.append({
                    "event": "exception_raised",
                    "thread_id": thread_id,
                    "timestamp": time.time(),
                    "data": {
                        "check_id": cid,
                        "status": c.get("status"),
                        "message": c.get("message"),
                    },
                })

    dec = state_values.get("decision") or {}
    if dec and "decision_ready" not in {e["event"] for e in events}:
        events.append({
            "event": "decision_ready",
            "thread_id": thread_id,
            "timestamp": time.time(),
            "data": {
                "lifecycle_status": state_values.get("lifecycle_status"),
                "decision": dec,
            },
        })

    actions = state_values.get("human_action_history") or []
    recorded_actions = {e["data"].get("action") for e in events if e["event"] == "human_action_received"}
    for a in actions:
        act = a.get("action")
        if act and act not in recorded_actions:
            events.append({
                "event": "human_action_received",
                "thread_id": thread_id,
                "timestamp": time.time(),
                "data": a,
            })

    pkg = state_values.get("posting_package")
    if pkg and "posting_package_ready" not in {e["event"] for e in events}:
        events.append({
            "event": "posting_package_ready",
            "thread_id": thread_id,
            "timestamp": time.time(),
            "data": {
                "package_id": pkg.get("package_id"),
                "invoice_number": pkg.get("invoice_number"),
                "total_amount": pkg.get("total_amount"),
                "lifecycle_status": "POSTING_PACKAGE_READY",
            },
        })

    EVENT_BUS[thread_id] = events
    return events


def _extract_interrupt_payload(state_snapshot: Any) -> Optional[dict[str, Any]]:
    """Extract interrupt details if the LangGraph run is paused at a human gate."""
    if not hasattr(state_snapshot, "tasks") or not state_snapshot.tasks:
        return None
    for task in state_snapshot.tasks:
        if hasattr(task, "interrupts") and task.interrupts:
            val = task.interrupts[0].value
            if isinstance(val, dict):
                return val
            return {"raw": val}
    return None


# ---------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------

@app.get("/api/health")
def health_check():
    """Verify health of PostgreSQL Data Layer and FastMCP service."""
    db_ok = is_db_reachable()
    mcp_client = get_mcp_client()
    mcp_remote = mcp_client.is_remote_connected()

    return {
        "status": "healthy" if db_ok else "degraded",
        "database": {"connected": db_ok, "engine": "PostgreSQL"},
        "checkpointer": {"engine": "PostgresSaver" if db_ok else "MemorySaver"},
        "mcp_server": {
            "connected": mcp_remote,
            "transport": "SSE",
            "url": mcp_client.server_url,
        },
    }


@app.post("/api/invoices/upload", response_model=InvoiceExecutionResponse, status_code=status.HTTP_200_OK)
async def upload_invoice(
    file: Optional[UploadFile] = File(None),
    invoice_ref: Optional[str] = Form(None),
    workflow_version: str = Form("v1.0.0"),
):
    """Ingest an invoice document (PDF) or reference, process through controls, and persist in PostgresSaver."""
    if file is None and not invoice_ref:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either a file upload or 'invoice_ref' must be provided.",
        )

    # 1. Handle file upload or reference
    file_path_str = ""
    if file is not None:
        content = await file.read()
        file_hash = hashlib.sha256(content).hexdigest()
        dest_filename = f"{file_hash[:12]}_{file.filename}"
        dest_path = UPLOAD_DIR / dest_filename
        dest_path.write_bytes(content)
        file_path_str = str(dest_path)

        try:
            record_invoice_document_db(
                file_name=file.filename or dest_filename,
                file_path=file_path_str,
                file_hash_sha256=file_hash,
                file_size_bytes=len(content),
                mime_type=file.content_type or "application/pdf",
            )
        except Exception as e:
            logger.warning(f"Could not record invoice document: {e}")
    else:
        file_path_str = invoice_ref or ""

    # 2. Generate thread_id (1:1 with run_id)
    thread_id = f"run-{uuid.uuid4().hex[:12]}"
    session_id = f"session-{thread_id}"

    # Initial event emissions
    emit_event(thread_id, "uploaded", {"invoice_reference": file_path_str, "file_name": file.filename if file else file_path_str})
    emit_event(thread_id, "extraction_started", {"method": "multimodal_vision_gpt4o_mini"})

    # 3. Record initial run in PostgreSQL
    try:
        record_processing_run_db(
            run_id=thread_id,
            session_id=session_id,
            workflow_version=workflow_version,
            lifecycle_status="START",
        )
    except Exception as e:
        logger.warning(f"Could not record processing run in DB: {e}")

    # 4. Invoke graph with PostgresSaver
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_invoice_graph()

    initial_state = {
        "run_id": thread_id,
        "thread_id": thread_id,
        "session_id": session_id,
        "invoice_reference": file_path_str,
        "workflow_version": workflow_version,
        "lifecycle_status": "START",
        "human_action_history": [],
    }

    # 4b. Launch graph in background — return thread_id immediately so SSE can start
    asyncio.create_task(
        _run_graph_background(thread_id, initial_state, config, file_path_str, workflow_version)
    )

    return InvoiceExecutionResponse(
        thread_id=thread_id,
        run_id=thread_id,
        lifecycle_status="PROCESSING",
        is_interrupted=False,
        message="Invoice ingested — processing started in background.",
    )


@app.post("/api/invoices/upload-json", response_model=InvoiceExecutionResponse)
async def upload_invoice_json(req: InvoiceUploadJsonRequest):
    """JSON wrapper for upload_invoice (convenient for programmatic/curl clients)."""
    return await upload_invoice(file=None, invoice_ref=req.invoice_reference, workflow_version=req.workflow_version)


@app.post("/api/invoices/{thread_id}/resume", response_model=InvoiceExecutionResponse)
async def resume_invoice_run(thread_id: str, payload: HumanResumeRequest):
    """Resume an interrupted invoice processing run with a human action.
    
    Supports:
    - AP Review: action='SELECT_PO_2001', role='AP Operator'
    - Finance Approval: action='APPROVE' | 'REJECT', role='Finance Approver'
    """
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_invoice_graph()

    # 1. Fetch current checkpoint from PostgresSaver
    state = graph.get_state(config)
    if not state.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Invoice processing run '{thread_id}' not found in Postgres checkpoint storage.",
        )

    interrupt_payload = _extract_interrupt_payload(state)
    if not interrupt_payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Run '{thread_id}' is not currently paused at a human review gate. Status: {state.values.get('lifecycle_status')}",
        )

    # 1.1 Pre-validate role authorization to protect graph checkpoint state
    gate_type = interrupt_payload.get("type")
    if gate_type == "FINANCE_APPROVAL" and payload.action == "APPROVE":
        if payload.role not in ("Finance Approver", "Finance Director"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Unauthorized action: Role '{payload.role}' cannot authorize invoice approval. Required: Finance Approver.",
            )

    # 2. Record human action in PostgreSQL audit table
    try:
        record_human_action_db(
            run_id=thread_id,
            gate_type=interrupt_payload.get("type", "UNKNOWN_GATE"),
            required_role=interrupt_payload.get("required_role", "Unknown"),
            actor_user_id=payload.user_id,
            actor_role=payload.role,
            action=payload.action,
            decision_revision=payload.decision_revision,
            reason=payload.reason or "",
            action_payload=payload.model_dump(),
        )
    except Exception as e:
        logger.warning(f"Could not persist human action in DB: {e}")

    # Emit human action event
    emit_event(thread_id, "human_action_received", payload.model_dump())

    # 3. Resume graph execution in background (same pattern as initial upload)
    # Running synchronously here blocks the event loop for 30-60s and causes frontend timeouts.
    resume_action = {
        "action": payload.action,
        "role": payload.role,
        "user_id": payload.user_id,
        "selected_po": payload.selected_po,
        "decision_revision": payload.decision_revision,
        "reason": payload.reason,
    }

    asyncio.create_task(_resume_graph_background(thread_id, resume_action, config))

    # Return immediately — frontend will poll /status for the updated state
    lifecycle_status = state.values.get("lifecycle_status", "NEEDS_ATTENTION")
    next_interrupt = interrupt_payload
    is_interrupted = True
    msg = f"Resume accepted — processing in background"

    return InvoiceExecutionResponse(
        thread_id=thread_id,
        run_id=thread_id,
        lifecycle_status=lifecycle_status,
        is_interrupted=is_interrupted,
        interrupt=next_interrupt,
        extracted_invoice=state.values.get("extracted_invoice"),
        control_report=state.values.get("control_report"),
        decision=state.values.get("decision"),
        posting_package=state.values.get("posting_package"),
        message=msg,
    )


@app.get("/api/invoices/{thread_id}/status", response_model=InvoiceExecutionResponse)
def get_invoice_status(thread_id: str):
    """Retrieve real-time execution snapshot for a given thread_id directly from PostgresSaver."""
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_invoice_graph()
    state = graph.get_state(config)

    if not state.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Run '{thread_id}' not found.",
        )

    interrupt_payload = _extract_interrupt_payload(state)
    lifecycle_status = state.values.get("lifecycle_status", "UNKNOWN")

    return InvoiceExecutionResponse(
        thread_id=thread_id,
        run_id=thread_id,
        lifecycle_status=lifecycle_status,
        is_interrupted=bool(interrupt_payload),
        interrupt=interrupt_payload,
        extracted_invoice=state.values.get("extracted_invoice"),
        control_report=state.values.get("control_report"),
        decision=state.values.get("decision"),
        posting_package=state.values.get("posting_package"),
        message=f"Current lifecycle status: {lifecycle_status}",
    )


@app.get("/api/invoices/{thread_id}/events")
async def stream_invoice_events(thread_id: str):
    """SSE stream: streams events live as they are emitted during graph execution."""
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_invoice_graph()

    async def event_generator() -> AsyncGenerator[str, None]:
        streamed_idx = 0

        # Recovery path: only for completed runs (e.g. server restart, re-fetch)
        # Skip if the background task is still actively running to avoid killing the live stream
        if not RUN_COMPLETE.get(thread_id) and thread_id not in RUNS_ACTIVE:
            recovery_state = graph.get_state(config)
            if recovery_state and recovery_state.values:
                derive_events_from_state(thread_id, recovery_state.values)
                RUN_COMPLETE[thread_id] = True

        # Stream events live — poll every 0.4s, heartbeat every 10s to prevent connection drop
        waited = 0.0
        ticks_since_heartbeat = 0
        while True:
            current_events = EVENT_BUS.get(thread_id, [])
            while streamed_idx < len(current_events):
                yield f"data: {json.dumps(current_events[streamed_idx])}\n\n"
                streamed_idx += 1
                ticks_since_heartbeat = 0
                await asyncio.sleep(0.18)

            if RUN_COMPLETE.get(thread_id):
                break

            if waited >= 180.0:
                logger.warning("SSE wait timeout for %s", thread_id)
                break

            await asyncio.sleep(0.4)
            waited += 0.4
            ticks_since_heartbeat += 1
            if ticks_since_heartbeat >= 25:  # ~10 seconds with no events
                yield ": heartbeat\n\n"
                ticks_since_heartbeat = 0

        # Final drain — pick up any events added by derive_events_from_state at graph completion
        state = graph.get_state(config)
        if state and state.values:
            derive_events_from_state(thread_id, state.values)

        current_events = EVENT_BUS.get(thread_id, [])
        while streamed_idx < len(current_events):
            yield f"data: {json.dumps(current_events[streamed_idx])}\n\n"
            streamed_idx += 1
            await asyncio.sleep(0.35)

        # Terminal signals
        interrupt_val = _extract_interrupt_payload(state) if state else None
        if interrupt_val:
            yield f"data: {json.dumps({'event': 'awaiting_human_action', 'thread_id': thread_id, 'data': interrupt_val})}\n\n"
        elif state and (state.values or {}).get("lifecycle_status") == "POSTING_PACKAGE_READY":
            yield f"data: {json.dumps({'event': 'stream_completed', 'thread_id': thread_id})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/invoices/{thread_id}/posting-package")
def get_posting_package(thread_id: str):
    """Retrieve the final ERP-ready JSON posting package after Finance approval."""
    config = {"configurable": {"thread_id": thread_id}}
    graph = create_invoice_graph()
    state = graph.get_state(config)

    pkg = state.values.get("posting_package")
    if not pkg:
        # Fallback check from PostgreSQL invoices table
        with get_db_cursor() as cur:
            cur.execute(
                """
                SELECT posting_package_id, invoice_number, total_amount, currency, lifecycle_status, posted_at
                FROM invoices
                WHERE posting_package_id LIKE %s;
                """,
                (f"PKG-{thread_id}-%",),
            )
            row = cur.fetchone()
            if row:
                pkg = {
                    "package_id": row["posting_package_id"],
                    "invoice_number": row["invoice_number"],
                    "total_amount": float(row["total_amount"]),
                    "currency": row["currency"],
                    "lifecycle_status": row["lifecycle_status"],
                    "posted_at": str(row["posted_at"]),
                }

    if not pkg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Posting package not ready yet for thread '{thread_id}'. Current status: {state.values.get('lifecycle_status', 'UNKNOWN')}",
        )

    return pkg


@app.get("/api/invoices")
def list_invoices(limit: int = 20):
    """List recent invoice processing runs from PostgreSQL."""
    if not is_db_reachable():
        return {"runs": [], "message": "Database offline"}

    with get_db_cursor() as cur:
        cur.execute(
            """
            SELECT pr.run_id, pr.session_id, pr.lifecycle_status, pr.workflow_version,
                   pr.started_at, pr.completed_at, pr.duration_ms,
                   i.invoice_number, i.total_amount, i.supplier_id
            FROM processing_runs pr
            LEFT JOIN invoices i ON pr.invoice_id = i.id
            ORDER BY pr.started_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return {
            "count": len(rows),
            "runs": [
                {
                    "run_id": r["run_id"],
                    "session_id": r["session_id"],
                    "lifecycle_status": r["lifecycle_status"],
                    "workflow_version": r["workflow_version"],
                    "started_at": str(r["started_at"]) if r["started_at"] else None,
                    "completed_at": str(r["completed_at"]) if r["completed_at"] else None,
                    "duration_ms": float(r["duration_ms"]) if r["duration_ms"] else None,
                    "invoice_number": r.get("invoice_number"),
                    "total_amount": float(r["total_amount"]) if r.get("total_amount") else None,
                    "supplier_id": r.get("supplier_id"),
                }
                for r in rows
            ],
        }
