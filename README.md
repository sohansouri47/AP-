# ZAMP AP AI Employee

An autonomous Accounts Payable processing system built with a multi-agent architecture. The system ingests invoices (PDF, image, Excel), runs 13 deterministic financial controls, and reaches a lifecycle decision — autonomously routing clean invoices to approval, flagging exceptions for human review, and blocking invalid or fraudulent ones.

---

## Architecture

```
                         ┌─────────────────────────────┐
                         │      Streamlit Frontend      │
                         │  Process · Decision · History │
                         └────────────┬────────────────┘
                                      │ HTTP / SSE
                         ┌────────────▼────────────────┐
                         │     FastAPI Backend          │
                         │  /api/invoices/upload        │
                         │  /api/invoices/{id}/resume   │
                         │  /api/invoices/{id}/status   │
                         └────────────┬────────────────┘
                                      │
                         ┌────────────▼────────────────┐
                         │       Deep Agent             │  ← Orchestrates everything
                         │  (claude-sonnet via SDK)     │
                         └──────┬─────────┬────────────┘
                                │         │
              ┌─────────────────▼─┐   ┌───▼──────────────────┐
              │ control-executor  │   │ exception-investigator │
              │ (13 AP controls)  │   │ (evidence gathering)   │
              └─────────────┬─────┘   └────────────────────────┘
                            │
                 ┌──────────▼──────────┐
                 │  FastMCP Server     │  ← 34 tools on port 8000
                 │  (port 8000)        │
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │  PostgreSQL          │  ← Durable state + checkpoints
                 └─────────────────────┘
```

**Key design decisions:**
- **Pre-extraction before agent**: Invoice is extracted via GPT-4o vision *before* the deep agent runs, seeding `extracted_invoice` so controls never operate on empty data even if the LLM skips the extract tool call.
- **Deterministic harness**: All 13 controls execute deterministically via the control-executor subagent and are validated against MCP server results. The LLM cannot fabricate check outcomes.
- **LangGraph checkpointer**: Durable PostgresSaver checkpointing enables human-in-the-loop interrupts — the graph pauses at `human_gate`, resumes via `/resume` endpoint after human action.

---

## The 13 Financial Controls

| ID | Control | What it checks |
|---|---|---|
| CHK_FILE_DUP | File Duplicate | SHA-256 hash deduplication |
| CHK_SUPPLIER_RES | Supplier Resolution | Vendor master match by name + Tax ID |
| CHK_BIZ_DUP | Business Duplicate | Same invoice number + supplier already posted |
| CHK_REMIT_CHANGE | Remittance Change | Bank account last-4 vs verified vendor record |
| CHK_ARITHMETIC | Arithmetic | Subtotal + Tax = Total within policy tolerance |
| CHK_DATES_CURR | Dates & Currency | Valid date format, currency in authorized list |
| CHK_PO_IDENT | PO Identification | Explicit PO match, or auto-resolve if supplier has exactly 1 open PO |
| CHK_PO_HEADER | PO Header | PO is APPROVED and belongs to the resolved supplier |
| CHK_PO_LINES | PO Line Match | 3-way match of invoice lines against PO schedule |
| CHK_PO_REMAIN | PO Remaining | Invoice amount ≤ remaining PO balance |
| CHK_PO_TOL | PO Tolerance | Price and quantity variance within policy thresholds |
| CHK_NO_PO_POL | No-PO Policy | Non-PO invoice threshold and cost-center rules |
| CHK_APP_ROUTE | Approval Routing | Finance Approver vs Finance Director based on amount |

---

## Lifecycle Outcomes

| Status | Meaning |
|---|---|
| `READY_FOR_APPROVAL` | All controls passed — awaiting Finance gate |
| `NEEDS_ATTENTION` | At least one control requires operator input (e.g. ambiguous PO, remittance mismatch) |
| `BLOCKED` | At least one control hard-failed (arithmetic error, duplicate, policy violation) |

---

## Supported Invoice Formats

PDF · JPEG · PNG · WEBP · GIF · BMP · TIFF · XLSX · XLS · CSV

- **PDF / images**: rasterized via PyMuPDF, then GPT-4o vision extraction
- **Excel**: parsed via openpyxl into text tables, then LLM text extraction
- **BMP / TIFF**: converted to PNG via Pillow before vision

---

## Project Structure

```
.
├── backend/
│   └── app/
│       ├── main.py              # FastAPI entrypoint — all API endpoints
│       ├── agent/
│       │   ├── deep_agent.py    # Deep agent orchestration + pre-extraction
│       │   ├── subagents.py     # control-executor & exception-investigator specs
│       │   ├── graph.py         # LangGraph invoice + improvement graphs
│       │   ├── extractor.py     # Multi-format invoice extraction pipeline
│       │   ├── mcp_tools.py     # MCP tool wrappers with role-based access control
│       │   ├── mcp_client.py    # FastMCP SSE client
│       │   ├── policy.py        # Active policy & version management
│       │   ├── prompts.py       # System prompts for all agents
│       │   └── observability.py # Langfuse trace integration
│       └── db/
│           ├── init_db.py       # Schema creation + seed data
│           ├── repository.py    # All DB read/write operations
│           └── connection.py    # psycopg3 connection pool
├── mcp/
│   └── server.py               # FastMCP server — 34 AP financial control tools
├── frontend/
│   ├── app.py                  # Streamlit app — 5 navigation tabs
│   ├── api_client.py           # HTTP + SSE client for backend
│   └── components/             # UI components per tab
├── demo-invoices/              # Pre-generated demo PDFs (10 scenarios)
├── docker-compose.yml
├── Dockerfile.backend
├── Dockerfile.frontend
└── Makefile                    # deploy / pause / resume / logs
```

---

## Running Locally

**Prerequisites:** Python 3.12+, PostgreSQL running locally, OpenAI API key

```bash
# 1. Clone and install
git clone <repo-url>
cd AP-
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
pip install -r frontend/requirements.txt

# 2. Configure environment
cp .env.example .env
# Fill in: OPENAI_API_KEY, DATABASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

# 3. Seed the database
cd backend
python -c "from app.db.init_db import initialize_database; initialize_database(drop_existing=True)"

# 4. Start MCP server (terminal 1)
cd mcp
python server.py

# 5. Start backend (terminal 2)
cd backend
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# 6. Start frontend (terminal 3)
cd frontend
streamlit run app.py --server.port 8501
```

Open: http://localhost:8501

---

## Deployment (EC2)

The app is containerized and deployed on AWS EC2 (t3.small) behind Docker Compose.

```bash
# Deploy without rebuild (restart containers, ~10s)
make deploy

# Deploy with full image rebuild (~5 min)
make deploy-build

# Pause EC2 to save cost
make pause

# Resume EC2 + get new public IP
make resume

# Tail logs
make logs-backend
```

---

## Seeding / Resetting Demo Data

Before each demo, reseed to ensure clean duplicate detection state:

```bash
cd backend
python -c "from app.db.init_db import initialize_database; initialize_database(drop_existing=True)"
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| LLM | GPT-4o (OpenAI) via LangChain |
| Agent orchestration | Deep Agents SDK + LangGraph |
| MCP server | FastMCP (SSE, port 8000) |
| Backend API | FastAPI + uvicorn |
| Frontend | Streamlit |
| Database | PostgreSQL (psycopg3) |
| Checkpointing | LangGraph PostgresSaver |
| Observability | Langfuse |
| PDF extraction | PyMuPDF + Pillow |
| Deployment | Docker Compose on AWS EC2 |
