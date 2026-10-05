# Demo Guide — ZAMP AP AI Employee

This guide walks an interviewer through the full invoice processing story.  
Each PDF is self-contained — upload it to the app and it runs autonomously.

---

## Setup Before the Demo

1. **Reseed the database** (critical — clears duplicate detection state)

   ```bash
   cd backend
   python -c "from app.db.init_db import initialize_database; initialize_database(drop_existing=True)"
   ```

2. **Confirm backend is healthy** — the health indicator at the top of the UI should show green.

3. All demo PDFs are in the `demo-invoices/` folder.

---

## The Story: October 2026 AP Cycle at Acme Operations Corp

A batch of 10 invoices arrives in the AP inbox over the course of October.  
The AI Employee processes each one — some sail through, some get flagged, some are blocked.

---

## Invoice 1 — Happy Path (the baseline)
**File:** `inv-happy-001.pdf`  
**Supplier:** Acme Industrial Supplies LLC  
**PO:** PO-9001 | **Amount:** $1,080

> Upload this first. It should process cleanly in ~30–60 seconds.

**What to show:**
- Watch the 7-step business stepper animate through extraction → controls → decision
- All 13 checks turn green
- Status: **READY_FOR_APPROVAL** — Finance Approver gate appears
- Click **Approve** to complete the run and view the posting package JSON

**Talking points:** The system extracted supplier, PO, line items, and totals directly from the PDF using GPT-4o vision. All 13 financial controls ran deterministically via the MCP server — the LLM has no ability to fabricate check outcomes.

---

## Invoice 2 — Auto-Resolved PO (no PO on the invoice)
**File:** `inv-happy-004.pdf`  
**Supplier:** Acme Industrial Supplies LLC  
**PO on invoice:** N/A | **Amount:** $918

> The invoice literally says "N/A" in the PO field.

**What to show:**
- CHK_PO_IDENT: "Single open PO PO-9001 auto-resolved for supplier SUPP-001"
- Status: **READY_FOR_APPROVAL** — all 13 passed despite no PO reference

**Talking points:** The agent checked the supplier's open PO list. Since Acme only has one open PO, it auto-resolved. No human intervention needed.

---

## Invoice 3 — Senior Approver Routing (large invoice)
**File:** `inv-story-senior-approver.pdf`  
**Supplier:** Globex Corp  
**PO:** PO-2002 | **Amount:** $12,960

**What to show:**
- All 13 checks pass
- Status: **READY_FOR_APPROVAL** — but CHK_APP_ROUTE says **Finance Director** (not Finance Approver)
- Policy threshold: invoices > $10,000 require a senior sign-off

**Talking points:** The approval routing is policy-driven. The AI didn't decide — the rule in the active policy version (v1.0.0) determined the role. If the threshold changes in a future policy version, it takes effect without any code change.

---

## Invoice 4 — Ambiguous PO (human must choose)
**File:** `inv-ambiguous-po.pdf`  
**Supplier:** Globex Corp  
**PO on invoice:** None | **Amount:** $2,592

> Globex has two open POs: PO-2001 (Deployment) and PO-2002 (Enterprise Consulting).

**What to show:**
- CHK_PO_IDENT → REQUIRES_INPUT
- Downstream PO checks (header, lines, remaining, tolerance) are automatically **SKIPPED** — no point running them without a resolved PO
- Status: **NEEDS_ATTENTION** — AP Operator interrupt appears with the question and both candidates
- Select a PO and click Resume — the run re-executes the remaining checks and reaches READY_FOR_APPROVAL

**Talking points:** The agent surfaced exactly the right question rather than guessing. The interrupt is durable — even if you close the browser and come back, the run resumes from the same state via LangGraph's PostgresSaver checkpointer.

---

## Invoice 5 — Remittance Change Alert (fraud flag)
**File:** `inv-story-remit-alert.pdf`  
**Supplier:** Acme Industrial Supplies LLC  
**PO:** PO-9001 | **Bank account ending:** 0072 (correct: 4321)

> Everything about this invoice is valid — except the bank account has changed.

**What to show:**
- CHK_REMIT_CHANGE → REQUIRES_INPUT: "Bank account ending in 0072 does not match verified vendor banking records"
- Status: **NEEDS_ATTENTION** — AP Operator must call the supplier to verify before payment is released
- All other 12 checks passed

**Talking points:** Payment diversion fraud (BEC — Business Email Compromise) is one of the most common AP attack vectors. The system catches this before any payment instruction is issued.

---

## Invoice 6 — PO Budget Exceeded
**File:** `inv-story-po-overrun.pdf`  
**Supplier:** Vandelay Industries  
**PO:** PO-8888 (remaining balance: $2,000) | **Amount:** $2,700

**What to show:**
- CHK_PO_REMAIN → FAILED: "Invoice amount (2700.0) exceeds remaining PO balance (2000.0) on PO-8888"
- Status: **BLOCKED** — cannot proceed without a PO amendment
- Show the History tab — the run is recorded with BLOCKED status and the exact failure reason

**Talking points:** The system checks against the live PO database, not a cached snapshot. The remaining balance reflects any prior invoices already billed against this PO.

---

## Invoice 7 — Unsupported Currency
**File:** `inv-story-currency.pdf`  
**Supplier:** Globex Corp (APAC division)  
**Currency:** JPY | **Amount:** ¥198,000

**What to show:**
- CHK_DATES_CURR → FAILED: "Currency JPY not authorized for automatic processing"
- CHK_PO_REMAIN → FAILED: ¥198,000 treated as nominal USD vastly exceeds PO balance
- Status: **BLOCKED** — two independent failures

**Talking points:** Active policy v1.0.0 authorizes USD, EUR, GBP, CAD. JPY invoices must go through a manual FX conversion workflow before submission. This is a policy rule — changing the authorized currencies requires a formal policy version change with regression testing.

---

## Invoice 8 — Arithmetic Error
**File:** `inv-tax-mismatch.pdf`  
**Supplier:** Acme Industrial Supplies LLC  
**Math:** Subtotal $1,000 + Tax $80 ≠ Total $1,200

**What to show:**
- CHK_ARITHMETIC → FAILED: "Subtotal (1000.0) + Tax (80.0) != Total (1200.0)"
- Status: **BLOCKED**

**Talking points:** Even a small discrepancy is caught. The tolerance threshold is configurable in the policy — currently set to $0.01.

---

## Invoice 9 — Duplicate Invoice
**File:** `inv-duplicate-001.pdf`  
**Invoice number:** INV-DUP-999  
**Supplier:** Vandelay Industries

> This invoice number was already posted to the ERP in a prior payment run.

**What to show:**
- CHK_BIZ_DUP → FAILED: "Duplicate invoice INV-DUP-999 already posted for supplier SUPP-003"
- Status: **BLOCKED**

**Talking points:** Both file-hash deduplication (CHK_FILE_DUP) and business-logic deduplication (same invoice number + supplier) run independently. This catches resubmissions even if the file is slightly modified.

---

## Invoice 10 — Globex with Explicit PO (avoids ambiguity)
**File:** `inv-happy-005.pdf`  
**Supplier:** Globex Corp  
**PO:** PO-2001 (explicit on invoice) | **Amount:** $1,944

> Use this after Invoice 4 to show the contrast — same supplier, but this time the PO is on the invoice.

**What to show:**
- CHK_PO_IDENT: PASSED immediately — no ambiguity because the PO is stated
- Status: **READY_FOR_APPROVAL** — 13/13

**Talking points:** Suppliers who include the PO number get processed instantly. Those who omit it either get auto-resolved (single open PO) or flagged for human selection (multiple open POs).

---

## UI Tabs to Highlight

| Tab | What to show |
|---|---|
| **Process Invoice** | Upload dropzone, live 7-step stepper, real-time control check cards |
| **Decision** | Full audit record — invoice data, PO match, all 13 controls with pass/fail, human action card |
| **History** | All processed runs searchable by status, date, supplier |
| **Master Data** | Live supplier, PO, and bank account records from PostgreSQL |
| **Governance** | Policy version, the 5-step self-improvement loop (staged, regression-gated, admin-approved) |

---

## Reseed Between Demos

If you run the duplicate invoice (Invoice 9) first, subsequent runs of the same invoice will also be blocked.  
**Always reseed before a fresh demo run:**

```bash
python -c "from app.db.init_db import initialize_database; initialize_database(drop_existing=True)"
```
