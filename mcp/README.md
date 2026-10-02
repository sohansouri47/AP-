# Accounts Payable FastMCP Server (`/mcp`)

Standalone **FastMCP Server** providing all 34 financial controls, specialist subagent investigation tools, and workflow improvement mechanisms for the Accounts Payable AI Employee.

## Transport Specification
- **Transport**: `sse` (Server-Sent Events over HTTP).
- **Strict Constraint**: **No stdio**. Stdio is completely bypassed in favor of HTTP/SSE networking.
- **Default Endpoint**: `http://127.0.0.1:8000/sse`

---

## Directory Layout
- `server.py`: Complete FastMCP server definition containing all 34 tools and resources.
- `client.py`: Thread-safe FastMCP client bridge (`FastMCPClientManager`) connecting agents over SSE with local fallback.
- `tools.py`: Tool delegators, permission boundaries, and dynamic check registry.
- `run_server.py`: Standalone CLI executable to start the FastMCP server on any host/port.

---

## Running the FastMCP Server Standalone

```bash
# Start on default port 8000
python mcp/run_server.py

# Or customize host and port
python mcp/run_server.py --host 0.0.0.0 --port 8080
```

---

## FastMCP Resources Exposed
- `ap://config`: Runtime configuration, framework metadata, and active transport.
- `ap://policy`: Active AP financial policy, tolerances, and thresholds in JSON.
- `ap://health`: Server health check, uptime, and tool registry count.

---

## Registered FastMCP Tools (34 Total)

### 1. Main Agent Tools
- `extract_invoice`: Multimodal vision and reference extraction.
- `get_run_context`: Correlation metadata and active registry version.

### 2. Mandatory Financial Controls (13 Tools)
- `check_file_duplicate`: SHA-256 duplicate detection.
- `resolve_supplier`: Vendor master resolution with fuzzy matching.
- `check_business_duplicate`: Semantic duplicate invoice detection.
- `check_remit_change`: Bank remittance verification against vendor master.
- `check_arithmetic`: Line item and tax arithmetic consistency.
- `check_dates_currency`: Date validity and authorized currencies.
- `identify_purchase_order`: PO reference resolution.
- `validate_po_header`: Header matching (supplier, buyer entity, status).
- `match_po_lines`: 1:1 line matching against PO schedule.
- `calculate_po_remaining`: Remaining PO fund verification.
- `evaluate_po_tolerances`: Price (1%) and quantity (5%) tolerance gates.
- `evaluate_no_po_policy`: Non-PO authorized spend limits ($2,500).
- `select_approval_route`: Role assignment (Finance Approver vs AP Director).

### 3. Specialist Subagent Tools
- `get_invoice_evidence`: Deep document evidence extraction.
- `get_supplier_candidates`: Vendor candidate disambiguation.
- `get_po_candidates`: PO candidate matching for ambiguous vendors.
- `calculate_line_confidence`: Line-item matching confidence scores.
- `create_candidate_version`: Staging policy and check candidate versions.
- `run_regression_suite`: Automated regression verification.
- `diff_proposal`: Semantic policy candidate diffing.

### 4. Deterministic Application & Gate Tools
- `validate_check_completeness`: 100% mandatory control execution gate.
- `select_final_decision`: Deterministic lifecycle status selection.
- `format_operator_question`: Structured human interrupt question builder.
- `apply_operator_input`: Re-evaluating controls after human intervention.
- `generate_posting_package`: Audit-sealed ERP posting bundle builder.
- `record_audit_log`: Append-only immutable audit trail logger.
