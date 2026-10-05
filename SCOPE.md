# Project Scope & Current Limitations

What is fully working, what is partially implemented, and what is out of scope for this version.

---

## What Works (Demo-Ready)

### Invoice Ingestion
- PDF, JPEG, PNG, WEBP, GIF, BMP, TIFF, XLSX, XLS, CSV all accepted
- GPT-4o vision extraction for image/PDF formats
- Openpyxl text-table extraction for Excel formats
- Pre-extraction seeded before deep agent runs — controls never operate on empty data

### All 13 Financial Controls
- All run deterministically via FastMCP server — LLM cannot fabricate outcomes
- Results are checksummed against server-side computation before decision is accepted
- Correct SKIPPED behavior: downstream PO checks are skipped when CHK_PO_IDENT is unresolved

### PO Identification Logic
- Explicit PO reference on invoice → immediate match
- No PO, one open PO for supplier → auto-resolve (PASSED, no human needed)
- No PO, multiple open POs for supplier → REQUIRES_INPUT with candidate list
- No PO, no open POs → FAILED

### Lifecycle Decision Engine
- READY_FOR_APPROVAL, NEEDS_ATTENTION, BLOCKED correctly computed from control results
- Finance Approver vs Finance Director routing based on policy amount threshold
- Deterministic parity gate: agent outcome validated against MCP decision before state is written

### Human-in-the-Loop Gates
- NEEDS_ATTENTION → AP Operator interrupt (select PO, resolve exception, or reject)
- READY_FOR_APPROVAL → Finance Approver or Finance Director interrupt
- After human action, graph resumes and re-runs affected controls
- LangGraph PostgresSaver: interrupts are durable — survive process restarts

### Observability
- Langfuse traces for every run: LLM calls, tool calls, latency, token counts
- Flow logger with structured node/gate/interrupt events written to stdout

### Deployment
- Dockerized backend + frontend on AWS EC2 via Docker Compose
- EventBridge + SSM scheduled EC2 shutdown (set for Oct 9, 2026 11:59 PM IST)

---

## Partially Implemented

### Workflow Self-Improvement Loop (Governance tab)
- **Built:** The full graph exists — feedback ingestion → pattern detection → candidate staging → regression gate → admin sign-off → activate/rollback
- **Not exposed:** No API endpoint wires the improvement graph into the live app
- **Not connected:** The `demo.py` standalone script exercises it, but no UI action triggers it
- **What the Governance tab shows:** Static explanation of the loop and "planned improvements" — not live data
- **Gap:** Operator corrections are not automatically captured as structured feedback events today; `get_feedback_events_db` returns empty unless manually seeded

### Supplier Resolution Fallback
- When DB lookup fails (unknown supplier name/tax ID), the MCP server falls back to SUPP-001
- This means an invoice from a completely unknown vendor will be silently resolved to Acme rather than returning FAILED
- **Fix needed:** The fallback should return CHK_SUPPLIER_RES → FAILED if no DB match is found

### CHK_PO_HEADER, CHK_PO_LINES, CHK_PO_TOL
- These three checks currently always return PASSED regardless of input
- The MCP server stubs are in place but the comparison logic is not implemented
- **CHK_PO_HEADER** should verify the PO belongs to the resolved supplier and is in APPROVED status
- **CHK_PO_LINES** should do real 3-way matching (invoice line description / qty / price vs PO line schedule)
- **CHK_PO_TOL** should compute actual price and quantity variance percentages against policy thresholds

### SUPP-004 (Initech Software Systems)
- Seeded in the suppliers table but has no bank account and no purchase orders
- Cannot be used in any demo scenario today without adding seed data

### File Duplicate Check (CHK_FILE_DUP)
- Logic exists but always returns PASSED in the current implementation
- SHA-256 hash deduplication is not persisted anywhere — no file_hash column in the invoices table

---

## Known Gaps / Not Implemented

### No multi-currency FX conversion
- Invoices in EUR, GBP, CAD are accepted by policy but not converted to USD before PO comparison
- A €1,944 invoice would be compared directly against a USD PO remaining balance

### No ERP write-back
- The posting package JSON is generated and stored in the database
- Nothing actually posts it to an ERP (SAP, NetSuite, etc.) — that integration is out of scope

### No email / Slack notifications
- When an invoice reaches NEEDS_ATTENTION or READY_FOR_APPROVAL, nobody is notified
- The human gate requires the operator to poll the UI or be given the thread ID directly

### No batch upload
- The UI handles one invoice at a time
- The batch view component exists in the frontend but is UI-only (no backend batch endpoint)

### No role-based authentication
- Any user can approve as any role (Finance Approver, Finance Director, AP Operator)
- `user_id` and `role` are passed in the resume payload but not validated against an identity provider

### Operator correction feedback loop not wired
- When an AP Operator resolves an exception (e.g. selects the correct PO), that correction is not written to a feedback table for future policy improvement analysis

### No test coverage for agent behavior
- Unit tests exist for extractors and DB operations
- No automated tests for agent decision paths, LangGraph graph traversal, or MCP control outcomes under varied inputs

### Langfuse traces sometimes time out
- Langfuse network calls happen synchronously on the hot path in some places
- If Langfuse is unreachable, the trace fails silently but the main flow continues

---

## Architecture Decisions Worth Noting

**Why pre-extract before the deep agent?**  
The deep agent LLM sometimes delegates directly to the control-executor subagent without calling `extract_invoice` first — leaving `extracted_invoice = {}`. All downstream controls (PO identification, duplicate check, arithmetic) then operate on empty supplier/PO/amount data. Pre-extracting before invoking the agent ensures the deterministic harness always has real data, regardless of what the LLM chooses to do.

**Why FastMCP over direct function calls?**  
The MCP boundary enforces strict role-based access control — each subagent has an allowlist of tools it can call. The control-executor cannot call privileged tools like `authorize_approval` or `build_posting_package`. This is a security boundary, not just an architecture choice.

**Why PostgresSaver for checkpointing?**  
Human-in-the-loop workflows require durable state. MemorySaver would lose the run on any process restart. PostgresSaver persists the full LangGraph state to the database, so interrupts survive restarts, redeploys, and browser refreshes.
