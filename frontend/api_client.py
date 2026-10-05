"""API Client for ZAMP Accounts Payable AI Employee.

Communicates with the FastAPI backend over HTTP and SSE (Server-Sent Events).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Generator, Optional
import httpx

logger = logging.getLogger("ap_frontend.client")


class BackendAPIClient:
    """Client for FastAPI endpoints."""

    def __init__(self, base_url: str = "http://127.0.0.1:8080"):
        self.base_url = base_url.rstrip("/")

    def check_health(self) -> dict[str, Any]:
        """Check backend, database, and FastMCP health."""
        try:
            with httpx.Client(base_url=self.base_url, timeout=5.0) as client:
                res = client.get("/api/health")
                if res.status_code == 200:
                    return res.json()
                return {"status": "unhealthy", "status_code": res.status_code, "error": res.text}
        except Exception as e:
            return {"status": "unreachable", "error": str(e)}

    def upload_invoice_file(
        self,
        file_bytes: bytes,
        filename: str,
        workflow_version: str = "v1.0.0",
    ) -> dict[str, Any]:
        """Upload a PDF invoice file to POST /api/invoices/upload."""
        with httpx.Client(base_url=self.base_url, timeout=60.0) as client:
            files = {"file": (filename, file_bytes, "application/pdf")}
            data = {"workflow_version": workflow_version}
            res = client.post("/api/invoices/upload", files=files, data=data)
            if res.status_code not in (200, 201):
                raise RuntimeError(f"Upload failed ({res.status_code}): {res.text}")
            return res.json()

    def upload_invoice_json(
        self,
        invoice_ref: str,
        workflow_version: str = "v1.0.0",
    ) -> dict[str, Any]:
        """Upload via JSON reference to POST /api/invoices/upload-json."""
        with httpx.Client(base_url=self.base_url, timeout=60.0) as client:
            payload = {
                "invoice_reference": invoice_ref,
                "workflow_version": workflow_version,
            }
            res = client.post("/api/invoices/upload-json", json=payload)
            if res.status_code not in (200, 201):
                raise RuntimeError(f"JSON upload failed ({res.status_code}): {res.text}")
            return res.json()

    def get_status(self, thread_id: str) -> dict[str, Any]:
        """Fetch current execution snapshot from GET /api/invoices/{thread_id}/status."""
        with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
            res = client.get(f"/api/invoices/{thread_id}/status")
            if res.status_code == 404:
                raise FileNotFoundError(f"Thread '{thread_id}' not found.")
            if res.status_code != 200:
                raise RuntimeError(f"Status check failed ({res.status_code}): {res.text}")
            return res.json()

    def get_posting_package(self, thread_id: str) -> dict[str, Any]:
        """Fetch final ERP posting package from GET /api/invoices/{thread_id}/posting-package."""
        with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
            res = client.get(f"/api/invoices/{thread_id}/posting-package")
            if res.status_code == 404:
                raise FileNotFoundError(f"Posting package not ready yet for thread '{thread_id}'.")
            if res.status_code != 200:
                raise RuntimeError(f"Failed to fetch posting package ({res.status_code}): {res.text}")
            return res.json()

    def resume_run(
        self,
        thread_id: str,
        action: str,
        role: str,
        user_id: str,
        selected_po: Optional[str] = None,
        reason: Optional[str] = None,
        decision_revision: int = 1,
    ) -> dict[str, Any]:
        """Resume an interrupted run via POST /api/invoices/{thread_id}/resume."""
        with httpx.Client(base_url=self.base_url, timeout=30.0) as client:
            payload = {
                "action": action,
                "role": role,
                "user_id": user_id,
                "selected_po": selected_po,
                "reason": reason,
                "decision_revision": decision_revision,
            }
            res = client.post(f"/api/invoices/{thread_id}/resume", json=payload)
            if res.status_code != 200:
                err_detail = res.text
                try:
                    err_json = res.json()
                    err_detail = err_json.get("detail", err_detail)
                except Exception:
                    pass
                raise RuntimeError(f"Resumption failed ({res.status_code}): {err_detail}")
            return res.json()

    def list_invoices(self, limit: int = 50) -> list[dict[str, Any]]:
        """List historical processing runs from GET /api/invoices."""
        with httpx.Client(base_url=self.base_url, timeout=10.0) as client:
            res = client.get(f"/api/invoices?limit={limit}")
            if res.status_code != 200:
                return []
            return res.json().get("runs", [])

    def stream_events(self, thread_id: str) -> Generator[dict[str, Any], None, None]:
        """Synchronous generator streaming SSE events from GET /api/invoices/{thread_id}/events."""
        url = f"{self.base_url}/api/invoices/{thread_id}/events"
        with httpx.Client(timeout=httpx.Timeout(10.0, read=300.0)) as client:
            with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise RuntimeError(f"Failed to connect to event stream ({response.status_code})")
                for line in response.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data: "):
                        data_str = line[6:].strip()
                        try:
                            parsed = json.loads(data_str)
                            yield parsed
                        except json.JSONDecodeError:
                            continue

    def get_events(self, thread_id: str) -> list[dict[str, Any]]:
        """Fetch all events emitted for a thread."""
        return list(self.stream_events(thread_id))
