# ZAMP Accounts Payable AI Employee — Frontend Microservice

A dedicated Streamlit microservice that interfaces with the ZAMP AP AI Employee FastAPI backend, providing live observability, real-time Server-Sent Events (SSE) streaming, and Human-in-the-Loop review workflows.

---

## Architecture Overview

```
                      Streamlit Frontend (Port 8501)
                     ┌──────────────────────────────┐
                     │ 1. Process Invoice (SSE live)│
                     │ 2. Decision Details (HITL)   │
                     │ 3. Run History (Postgres)    │
                     │ 4. Governance (Regression)   │
                     └──────────────┬───────────────┘
                                    │ HTTP / SSE
                                    ▼
                       FastAPI Backend (Port 8080)
                     ┌──────────────────────────────┐
                     │ POST /api/invoices/upload    │
                     │ POST /api/invoices/resume    │
                     │ GET  /api/invoices/.../events│
                     │ GET  /api/invoices/.../status│
                     │ GET  /api/invoices           │
                     └──────┬────────────────┬──────┘
                            │                │
            LangGraph + PostgresSaver   FastMCP Tools (SSE 8000)
```

---

## Features

### 1. Process Invoice (Live Stepper)
- Upload real PDF invoices (or select instant demo fixtures).
- Connects directly to `GET /api/invoices/{thread_id}/events` via Server-Sent Events (SSE).
- Renders an interactive vertical live stepper displaying the 8 canonical backend events:
  1. `uploaded`: Document fingerprint hashed & stored in PostgreSQL.
  2. `extraction_started`: Multimodal LLM Vision (GPT-4o-mini) optical parser activated.
  3. `supplier_resolved`: Master vendor profile & Tax ID resolved.
  4. `control_completed`: Financial controls executed (13 MCP checks).
  5. `exception_raised`: Variances or ambiguous matches flagged.
  6. `decision_ready`: Control decision synthesized (`PROCEED_TO_FINANCE`, `REQUIRES_AP_REVIEW`).
  7. `human_action_received`: Reviewer / Approver decision recorded.
  8. `posting_package_ready`: Immutable ERP ledger posting package generated!

### 2. Decision Details & Contextual Actions
- Reads snapshot from `GET /api/invoices/{thread_id}/status`.
- Shows extracted invoice fields (amounts, dates, supplier, masked `account_last4`).
- Matched PO & line items schedule.
- 13 MCP Financial Control chips with execution latencies.
- **Contextual Action Cards**:
  - **AP Review Gate**: PO choice buttons (`SELECT_PO_2001`, `SELECT_PO_2002`, `REJECT`).
  - **Finance Approval Gate**: Digital sign-off buttons (`APPROVE`, `REJECT`) with strict role authorization checking.
  - **Final Outcome**: When in `POSTING_PACKAGE_READY`, directly queries `GET /api/invoices/{thread_id}/posting-package` to inspect and copy the final ERP JSON payload.

### 3. Run History
- Calls `GET /api/invoices` to retrieve processing runs from PostgreSQL.
- Filterable by status and searchable by Invoice #, Supplier, or Thread ID.
- Quick inspection jump to Decision Details.

### 4. Governance
- Displays active policy version (`v1.0.0`), golden regression test status (50/50 passing), operator feedback patterns, and staged candidate diffs.

---

## Running Locally

### Step 1: Ensure Backend & FastMCP are Running
```bash
# Terminal 1: FastMCP Server (Port 8000)
PYTHONPATH=backend:mcp .venv/bin/python mcp/run_server.py

# Terminal 2: FastAPI Backend (Port 8080)
PYTHONPATH=backend .venv/bin/uvicorn app.main:app --port 8080
```

### Step 2: Launch Streamlit Frontend (Port 8501)
```bash
# Terminal 3: Streamlit Frontend
PYTHONPATH=frontend .venv/bin/streamlit run frontend/app.py --server.port 8501
```

Or via runner:
```bash
PYTHONPATH=frontend .venv/bin/python frontend/run_frontend.py
```
