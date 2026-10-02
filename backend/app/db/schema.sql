-- =====================================================================
-- ZAMP 2.0 Accounts Payable AI Employee - PostgreSQL Enterprise Schema
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ---------------------------------------------------------------------
-- 1. Suppliers & Banking Master
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id VARCHAR(50) PRIMARY KEY,          -- e.g. 'SUPP-001'
    name VARCHAR(255) NOT NULL,                   -- e.g. 'Acme Industrial Supplies LLC'
    legal_name VARCHAR(255),
    tax_id VARCHAR(50) UNIQUE,                    -- e.g. 'US-XX-9876543' (EIN / VAT)
    status VARCHAR(20) DEFAULT 'ACTIVE',          -- 'ACTIVE', 'INACTIVE', 'BLOCKED'
    payment_terms VARCHAR(50) DEFAULT 'NET30',
    currency VARCHAR(3) DEFAULT 'USD',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_suppliers_name ON suppliers (name);
CREATE INDEX IF NOT EXISTS idx_suppliers_tax_id ON suppliers (tax_id);

CREATE TABLE IF NOT EXISTS supplier_bank_accounts (
    bank_account_ref_id VARCHAR(50) PRIMARY KEY,  -- Safe token surfaced to agents: 'BANK-REF-SUPP-001-01'
    supplier_id VARCHAR(50) NOT NULL REFERENCES suppliers(supplier_id) ON DELETE CASCADE,
    bank_name VARCHAR(100) NOT NULL,
    routing_number VARCHAR(50),
    account_number_encrypted TEXT NOT NULL,       -- Strictly encrypted at rest; NEVER surfaced to LLM/Langfuse
    account_last4 VARCHAR(4) NOT NULL,            -- Masked last 4 digits for verification
    currency VARCHAR(3) DEFAULT 'USD',
    is_primary BOOLEAN DEFAULT TRUE,
    is_verified BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_supplier_bank_last4 ON supplier_bank_accounts (supplier_id, account_last4);

-- ---------------------------------------------------------------------
-- 2. ERP Purchase Orders & Line Schedules
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS purchase_orders (
    po_number VARCHAR(50) PRIMARY KEY,            -- e.g. 'PO-9001'
    supplier_id VARCHAR(50) NOT NULL REFERENCES suppliers(supplier_id),
    buyer_entity VARCHAR(100) NOT NULL DEFAULT 'Acme Operations Corp',
    status VARCHAR(30) DEFAULT 'APPROVED',        -- 'APPROVED', 'CLOSED', 'CANCELLED'
    currency VARCHAR(3) DEFAULT 'USD',
    total_amount NUMERIC(14, 2) NOT NULL,
    billed_amount NUMERIC(14, 2) DEFAULT 0.00,
    remaining_amount NUMERIC(14, 2) NOT NULL,
    issued_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_po_supplier_status ON purchase_orders (supplier_id, status);

CREATE TABLE IF NOT EXISTS purchase_order_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    po_number VARCHAR(50) NOT NULL REFERENCES purchase_orders(po_number) ON DELETE CASCADE,
    line_number INT NOT NULL,
    sku VARCHAR(100),
    description TEXT NOT NULL,
    quantity NUMERIC(12, 4) NOT NULL,
    unit_price NUMERIC(14, 4) NOT NULL,
    line_total NUMERIC(14, 2) NOT NULL,
    billed_quantity NUMERIC(12, 4) DEFAULT 0.00,
    remaining_quantity NUMERIC(12, 4) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_po_line UNIQUE (po_number, line_number)
);

-- ---------------------------------------------------------------------
-- 3. Invoices, Documents, & Line Items
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS invoices (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_number VARCHAR(100) NOT NULL,         -- e.g. 'INV-2026-001'
    supplier_id VARCHAR(50) REFERENCES suppliers(supplier_id),
    po_number VARCHAR(50) REFERENCES purchase_orders(po_number),
    invoice_date DATE NOT NULL,
    due_date DATE,
    subtotal NUMERIC(14, 2) NOT NULL,
    tax_amount NUMERIC(14, 2) NOT NULL,
    total_amount NUMERIC(14, 2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    lifecycle_status VARCHAR(50) NOT NULL,        -- 'READY_FOR_APPROVAL', 'APPROVED', 'BLOCKED', etc.
    decision_reason_code VARCHAR(100),
    posting_package_id VARCHAR(100),
    posted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_supplier_invoice_number UNIQUE (supplier_id, invoice_number)
);

CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_invoices_num ON invoices (invoice_number);

CREATE TABLE IF NOT EXISTS invoice_lines (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
    line_number INT NOT NULL,
    sku VARCHAR(100),
    description TEXT NOT NULL,
    quantity NUMERIC(12, 4) NOT NULL,
    unit_price NUMERIC(14, 4) NOT NULL,
    line_total NUMERIC(14, 2) NOT NULL,
    matched_po_line_id UUID REFERENCES purchase_order_lines(id),
    match_confidence NUMERIC(5, 4),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invoice_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    invoice_id UUID REFERENCES invoices(id) ON DELETE SET NULL,
    file_name VARCHAR(255) NOT NULL,
    file_path TEXT NOT NULL,
    file_hash_sha256 VARCHAR(64) UNIQUE NOT NULL, -- SHA-256 prevents duplicate file ingestion
    file_size_bytes BIGINT NOT NULL,
    mime_type VARCHAR(100) DEFAULT 'application/pdf',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_sha256 ON invoice_documents (file_hash_sha256);

-- ---------------------------------------------------------------------
-- 4. Processing Runs (1:1 with LangGraph thread_id / Langfuse session)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS processing_runs (
    run_id VARCHAR(100) PRIMARY KEY,                  -- LangGraph thread_id
    session_id VARCHAR(100),                          -- Langfuse session_id
    invoice_id UUID REFERENCES invoices(id),          -- Linked after extraction
    document_id UUID REFERENCES invoice_documents(id),-- Sourced document
    workflow_version VARCHAR(20) NOT NULL DEFAULT 'v1.0.0',
    lifecycle_status VARCHAR(50) NOT NULL DEFAULT 'START',
    current_node VARCHAR(50),
    error_details JSONB,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms NUMERIC(10, 2)
);

CREATE INDEX IF NOT EXISTS idx_runs_status ON processing_runs (lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_runs_invoice ON processing_runs (invoice_id);

-- ---------------------------------------------------------------------
-- 5. Individual Check Executions (MCP Control Latency & Results)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS check_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id VARCHAR(100) NOT NULL REFERENCES processing_runs(run_id) ON DELETE CASCADE,
    check_id VARCHAR(50) NOT NULL,                    -- e.g. 'CHK_PO_TOL'
    execution_order INT NOT NULL,
    status VARCHAR(20) NOT NULL,                      -- 'PASSED', 'FAILED', 'WARNING', 'REQUIRES_INPUT'
    message TEXT NOT NULL,
    error_code VARCHAR(50),
    policy_version VARCHAR(20) NOT NULL,
    latency_ms NUMERIC(8, 2) NOT NULL,
    evidence_ids JSONB DEFAULT '[]'::jsonb,
    raw_output JSONB NOT NULL,
    executed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_check_exec_run ON check_executions (run_id, check_id);
CREATE INDEX IF NOT EXISTS idx_check_exec_status ON check_executions (status);

-- ---------------------------------------------------------------------
-- 6. Human Actions & Revision-Safe Resumptions
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS human_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id VARCHAR(100) NOT NULL REFERENCES processing_runs(run_id) ON DELETE CASCADE,
    gate_type VARCHAR(50) NOT NULL,                   -- 'OPERATOR_INPUT', 'FINANCE_APPROVAL'
    required_role VARCHAR(50) NOT NULL,               -- 'AP Operator', 'Finance Approver'
    actor_user_id VARCHAR(100) NOT NULL,             -- e.g. 'sarah_cfo'
    actor_role VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,                      -- 'APPROVE', 'REJECT', 'SELECT_PO'
    decision_revision INT NOT NULL,                   -- Revision-safety counter
    reason TEXT,
    action_payload JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_human_actions_run ON human_actions (run_id);

-- ---------------------------------------------------------------------
-- 7. Workflow & Policy Versions (Staging & Rollback Governance)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS workflow_versions (
    version VARCHAR(20) PRIMARY KEY,                  -- e.g. 'v1.0.0'
    registry_version VARCHAR(20) NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    rollback_target_version VARCHAR(20),
    policy_payload JSONB NOT NULL,
    change_summary TEXT,
    activated_by VARCHAR(100),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    activated_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- 8. Review Feedback & Improvement Proposals
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS review_feedback (
    feedback_id VARCHAR(50) PRIMARY KEY,              -- e.g. 'FB-001'
    invoice_id UUID REFERENCES invoices(id),
    reviewer_id VARCHAR(100) NOT NULL,                -- e.g. 'alice_reviewer'
    field_corrected VARCHAR(100) NOT NULL,            -- e.g. 'po_line_mapping'
    prior_value JSONB NOT NULL,
    corrected_value JSONB NOT NULL,
    comment TEXT,
    status VARCHAR(20) DEFAULT 'OPEN',                -- 'OPEN', 'PROCESSED'
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_proposals (
    proposal_id VARCHAR(50) PRIMARY KEY,              -- e.g. 'PROP-v1.1.0'
    target_version VARCHAR(20) NOT NULL,
    feedback_ids JSONB NOT NULL,
    diff_summary JSONB NOT NULL,
    regression_passed BOOLEAN NOT NULL,
    regression_count INT DEFAULT 0,
    status VARCHAR(30) NOT NULL,                      -- 'DRAFT', 'STAGED', 'ACTIVATED', 'ROLLED_BACK'
    created_at TIMESTAMPTZ DEFAULT NOW(),
    activated_at TIMESTAMPTZ
);

-- ---------------------------------------------------------------------
-- 9. Immutable Audit Trail (Append-Only)
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    run_id VARCHAR(100) NOT NULL,
    event_type VARCHAR(100) NOT NULL,                 -- 'CONTROL_EXECUTION', 'HUMAN_INTERRUPT', 'POSTING'
    actor VARCHAR(100) NOT NULL,
    actor_role VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,                -- SHA-256 for cryptographic tamper verification
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_run_id ON audit_logs (run_id);
