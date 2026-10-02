"""Langfuse Observability & Tracing for AP AI Employee.

Provides:
- Safe data masking (redacting PDF bytes, full OCR text, raw bank details, secrets)
- Trace management for invoice runs (`ap-invoice-run`) and improvements (`ap-workflow-improvement`)
- Span tracking across parent nodes, subagents, and MCP tools using Langfuse SDK v4
- Real-time formatted console logging via FlowLogger
- 32-character lowercase hex trace ID compliance for OpenTelemetry and Langfuse Cloud
- Graceful degradation (Langfuse errors or missing keys never fail the business workflow)
"""

from __future__ import annotations

import os
import time
import hashlib
import logging
from pathlib import Path
from typing import Any, Callable, Optional

from dotenv import load_dotenv
from app.agent.flow_logger import flow_logger, BOLD, CYAN, RESET

logger = logging.getLogger("ap_agent.observability")

# Automatically load .env if present
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
for env_p in [_BACKEND_DIR / ".env", _BACKEND_DIR.parent / ".env", Path(".env")]:
    if env_p.exists():
        load_dotenv(dotenv_path=env_p, override=False)

# In-memory audit of recorded traces (for verification, debugging, and offline tests)
RECORDED_TRACES: list[dict[str, Any]] = []

SENSITIVE_KEYS = {
    "pdf_bytes",
    "raw_pdf",
    "ocr_full_text",
    "complete_ocr_text",
    "bank_account",
    "bank_account_number",
    "remit_value",
    "api_key",
    "secret",
    "credentials",
    "human_notes_raw",
}


def mask_sensitive_data(obj: Any) -> Any:
    """Recursively redact sensitive invoice fields, secrets, and raw binaries."""
    if isinstance(obj, dict):
        masked = {}
        for k, v in obj.items():
            if any(s_key in k.lower() for s_key in SENSITIVE_KEYS):
                masked[k] = "[REDACTED]"
            else:
                masked[k] = mask_sensitive_data(v)
        return masked
    elif isinstance(obj, list):
        return [mask_sensitive_data(item) for item in obj]
    elif isinstance(obj, bytes):
        return f"[BINARY_DATA_{len(obj)}_BYTES]"
    return obj


class TraceObserver:
    """Manages Langfuse trace events and nesting with resilient fallback and session propagation."""

    def __init__(
        self,
        trace_name: str,
        session_id: str,
        tags: list[str] | None = None,
        user_id: str | None = None,
    ):
        self.trace_name = trace_name
        self.session_id = session_id
        self.user_id = user_id
        self.tags = tags or []
        self.events: list[dict[str, Any]] = []
        self._langfuse_client = None
        self._root_span = None
        self._is_flushed = False
        # Deterministic 32-hex fallback trace_id (updated to real OpenTelemetry trace_id on Langfuse init)
        raw_seed = f"{session_id}"
        self.trace_id = hashlib.md5(raw_seed.encode()).hexdigest()
        self._init_langfuse()

    def set_user(self, user_id: str) -> None:
        """Update current active user for subsequent observations in this session."""
        if user_id:
            self.user_id = str(user_id)[:200]

    def _propagate_context(self):
        """Context manager propagating session_id, user_id, and tags across all spans."""
        from langfuse import propagate_attributes
        return propagate_attributes(
            session_id=str(self.session_id)[:200],
            user_id=str(self.user_id)[:200] if self.user_id else None,
            tags=self.tags,
            trace_name=self.trace_name,
        )

    def _init_langfuse(self) -> None:
        """Safely attempt to initialize Langfuse SDK if credentials exist."""
        try:
            public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = os.getenv("LANGFUSE_SECRET_KEY")
            host = os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com"
            if public_key and secret_key:
                from langfuse import Langfuse
                self._langfuse_client = Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
                logger.info("Langfuse tracing enabled for host: %s (session: %s)", host, self.session_id)
                # Create true root observation wrapped in propagate_attributes to register session
                try:
                    with self._propagate_context():
                        self._root_span = self._langfuse_client.start_observation(
                            name=self.trace_name,
                            as_type="chain",
                            input={"session_id": self.session_id, "tags": self.tags},
                            metadata={
                                "session_id": str(self.session_id)[:200],
                            },
                        )
                    # Use official OpenTelemetry 32-hex trace ID assigned to root observation
                    if hasattr(self._root_span, "trace_id") and self._root_span.trace_id:
                        self.trace_id = self._root_span.trace_id
                except Exception as ex:
                    logger.debug("Langfuse root observation initialization warning: %s", ex)
                    self._root_span = None
        except Exception as e:
            logger.warning("Langfuse initialization skipped or failed safely: %s", e)
            self._langfuse_client = None

    def log_node_execution(
        self,
        node_name: str,
        stage: str,
        input_data: Any,
        output_data: Any = None,
        duration_ms: float = 0.0,
    ) -> None:
        """Record parent graph node execution."""
        event = {
            "type": "NODE_EXECUTION",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "node_name": node_name,
            "stage": stage,
            "duration_ms": duration_ms,
            "input": mask_sensitive_data(input_data),
            "output": mask_sensitive_data(output_data),
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    obs = self._root_span.start_observation(
                        name=f"node:{node_name}",
                        as_type="span",
                        input=mask_sensitive_data(input_data),
                        output=mask_sensitive_data(output_data),
                        metadata={
                            "stage": str(stage)[:200],
                            "session_id": str(self.session_id)[:200],
                            "duration_ms": str(duration_ms)[:200],
                        },
                    )
                    obs.end()
            except Exception as e:
                logger.debug("Langfuse node span error (non-fatal): %s", e)

    def log_subagent_delegation(
        self,
        subagent_name: str,
        task_prompt: str,
        result: Any,
        skills_loaded: list[str] | None = None,
    ) -> None:
        """Record specialist subagent delegation as agent observation."""
        event = {
            "type": "SUBAGENT_DELEGATION",
            "observation_type": "agent",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "subagent_name": subagent_name,
            "task_prompt": task_prompt,
            "skills_loaded": skills_loaded or [],
            "result": mask_sensitive_data(result),
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    obs = self._root_span.start_observation(
                        name=f"subagent:{subagent_name}",
                        as_type="agent",
                        input={"task_prompt": task_prompt, "skills": skills_loaded or []},
                        output=mask_sensitive_data(result),
                        metadata={"session_id": str(self.session_id)[:200]},
                    )
                    obs.end()
            except Exception as e:
                logger.debug("Langfuse agent span error (non-fatal): %s", e)

    def log_mcp_tool_call(
        self,
        tool_name: str,
        caller: str,
        inputs: dict[str, Any],
        output: Any,
        duration_ms: float = 0.0,
        status: str = "SUCCESS",
    ) -> None:
        """Record MCP tool invocation with safe status and latency."""
        event = {
            "type": "MCP_TOOL_CALL",
            "observation_type": "tool",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "caller": caller,
            "tool_name": tool_name,
            "inputs": mask_sensitive_data(inputs),
            "output": mask_sensitive_data(output),
            "status": status,
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    obs = self._root_span.start_observation(
                        name=f"tool:{tool_name}",
                        as_type="tool",
                        input=mask_sensitive_data(inputs),
                        output=mask_sensitive_data(output),
                        metadata={
                            "caller": str(caller)[:200],
                            "duration_ms": str(duration_ms)[:200],
                            "status": str(status)[:200],
                        },
                    )
                    obs.end()
            except Exception as e:
                logger.debug("Langfuse tool span error (non-fatal): %s", e)

    def log_generation(
        self,
        name: str,
        model: str,
        prompt: Any,
        completion: Any,
        usage: dict[str, int] | None = None,
        duration_ms: float = 0.0,
    ) -> None:
        """Record LLM completion with token usage and cost metrics."""
        event = {
            "type": "GENERATION",
            "observation_type": "generation",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "name": name,
            "model": model,
            "prompt": mask_sensitive_data(prompt),
            "completion": mask_sensitive_data(completion),
            "usage": usage or {},
            "duration_ms": duration_ms,
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    obs = self._root_span.start_observation(
                        name=name,
                        as_type="generation",
                        model=model,
                        input=mask_sensitive_data(prompt),
                        output=mask_sensitive_data(completion),
                        usage_details=usage,
                    )
                    obs.end()
            except Exception as e:
                logger.debug("Langfuse generation span error (non-fatal): %s", e)

    def log_interrupt(self, interrupt_type: str, payload: dict[str, Any]) -> None:
        """Record human gate interrupt event."""
        event = {
            "type": "INTERRUPT_EVENT",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "interrupt_type": interrupt_type,
            "payload": mask_sensitive_data(payload),
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    self._root_span.create_event(
                        name=f"interrupt:{interrupt_type}",
                        input=mask_sensitive_data(payload),
                    )
            except Exception as e:
                logger.debug("Langfuse interrupt event error: %s", e)

    def log_resume(self, human_action: dict[str, Any]) -> None:
        """Record human resume event maintaining same trace correlation."""
        user_id = human_action.get("user_id")
        if user_id:
            self.set_user(user_id)

        event = {
            "type": "RESUME_EVENT",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "human_action": mask_sensitive_data(human_action),
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    self._root_span.create_event(
                        name="human_resume",
                        input=mask_sensitive_data(human_action),
                    )
            except Exception as e:
                logger.debug("Langfuse resume event error: %s", e)

    def log_final_decision(self, outcome: dict[str, Any]) -> None:
        """Record final AP decision and outcome."""
        event = {
            "type": "FINAL_DECISION",
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "outcome": mask_sensitive_data(outcome),
            "timestamp": time.time(),
        }
        self.events.append(event)
        RECORDED_TRACES.append(event)

        if self._root_span:
            try:
                with self._propagate_context():
                    self._root_span.create_event(
                        name="final_decision",
                        output=mask_sensitive_data(outcome),
                    )
            except Exception as e:
                logger.debug("Langfuse decision event error: %s", e)

    def get_session_url(self) -> str | None:
        """Return direct clickable link to this flow session in Langfuse Cloud."""
        if self._langfuse_client and self.session_id:
            try:
                trace_url = self._langfuse_client.get_trace_url(trace_id=self.trace_id)
                if trace_url and "/traces/" in trace_url:
                    base_project = trace_url.split("/traces/")[0]
                    return f"{base_project}/sessions/{self.session_id}"
            except Exception:
                pass
        return None

    def flush(self) -> str | None:
        """Flush to remote Langfuse server if available and print clickable trace & session URLs."""
        if self._langfuse_client:
            try:
                if self._root_span and not self._is_flushed:
                    self._root_span.end()
                    self._is_flushed = True
                self._langfuse_client.flush()
                trace_url = self._langfuse_client.get_trace_url(trace_id=self.trace_id)
                session_url = self.get_session_url()
                logger.info("Langfuse trace URL: %s | session URL: %s", trace_url, session_url)
                print(f"\n{BOLD}{CYAN}🔗 Langfuse Cloud Trace:{RESET} {trace_url}")
                if session_url:
                    print(f"{BOLD}{CYAN}📁 Langfuse Cloud Session:{RESET} {session_url}\n")
                else:
                    print("")
                return trace_url
            except Exception as e:
                logger.warning("Langfuse flush warning (non-fatal): %s", e)
        return None


# Cache of active trace observers to ensure multi-node LangGraph flows share one trace
_ACTIVE_TRACERS: dict[str, TraceObserver] = {}


def get_invoice_tracer(
    run_id: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> TraceObserver:
    """Factory for invoice run trace observer (maintains active session across entire flow)."""
    effective_session = session_id or run_id
    if run_id in _ACTIVE_TRACERS:
        tracer = _ACTIVE_TRACERS[run_id]
        if user_id:
            tracer.set_user(user_id)
        return tracer
    if effective_session in _ACTIVE_TRACERS:
        tracer = _ACTIVE_TRACERS[effective_session]
        if user_id:
            tracer.set_user(user_id)
        return tracer

    tracer = TraceObserver(
        trace_name="ap-invoice-run",
        session_id=effective_session,
        tags=["invoice-run", "ap-employee"],
        user_id=user_id,
    )
    _ACTIVE_TRACERS[run_id] = tracer
    _ACTIVE_TRACERS[effective_session] = tracer
    return tracer


def get_improvement_tracer(
    proposal_id: str,
    session_id: str | None = None,
    user_id: str | None = None,
) -> TraceObserver:
    """Factory for workflow improvement trace observer (maintains active session across entire flow)."""
    effective_session = session_id or proposal_id
    if proposal_id in _ACTIVE_TRACERS:
        tracer = _ACTIVE_TRACERS[proposal_id]
        if user_id:
            tracer.set_user(user_id)
        return tracer
    if effective_session in _ACTIVE_TRACERS:
        tracer = _ACTIVE_TRACERS[effective_session]
        if user_id:
            tracer.set_user(user_id)
        return tracer

    tracer = TraceObserver(
        trace_name="ap-workflow-improvement",
        session_id=effective_session,
        tags=["workflow-improvement"],
        user_id=user_id,
    )
    _ACTIVE_TRACERS[proposal_id] = tracer
    _ACTIVE_TRACERS[effective_session] = tracer
    return tracer


def flush_all_tracers() -> None:
    """Flush all active trace observers to Langfuse Cloud."""
    for tracer in list(_ACTIVE_TRACERS.values()):
        tracer.flush()


def reset_tracers() -> None:
    """Flush and clear all in-memory tracers (for test isolation)."""
    flush_all_tracers()
    RECORDED_TRACES.clear()
    _ACTIVE_TRACERS.clear()


import atexit
atexit.register(flush_all_tracers)
