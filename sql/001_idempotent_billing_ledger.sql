-- Idempotent revenue ledger, immutable approval rule snapshots, and collections outbox

CREATE TABLE IF NOT EXISTS approval_rule_versions (
    rule_id TEXT NOT NULL,
    version_hash CHAR(64) NOT NULL,
    natural_language_spec TEXT NOT NULL,
    compiled_ast JSONB NOT NULL,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (rule_id, version_hash)
);

CREATE TABLE IF NOT EXISTS deal_approval_runs (
    run_id UUID PRIMARY KEY,
    deal_id TEXT NOT NULL,
    rule_id TEXT NOT NULL,
    rule_version_hash CHAR(64) NOT NULL,
    acv_cents BIGINT NOT NULL CHECK (acv_cents >= 0),
    discount_bps INT NOT NULL CHECK (discount_bps BETWEEN 0 AND 10000),
    billing_term TEXT NOT NULL,
    required_approvers TEXT[] NOT NULL,
    audit_trace JSONB NOT NULL,
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    FOREIGN KEY (rule_id, rule_version_hash) REFERENCES approval_rule_versions (rule_id, version_hash)
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    entry_id UUID PRIMARY KEY,
    account_id TEXT NOT NULL,
    invoice_id TEXT NOT NULL,
    direction SMALLINT NOT NULL CHECK (direction IN (-1, 1)),
    amount_cents BIGINT NOT NULL CHECK (amount_cents > 0),
    currency CHAR(3) NOT NULL DEFAULT 'USD',
    idempotency_key TEXT NOT NULL UNIQUE,
    posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS collection_dispatch_outbox (
    outbox_id UUID PRIMARY KEY,
    invoice_id TEXT NOT NULL,
    customer_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('REMINDER_7D', 'ESCALATE_14D', 'FINAL_NOTICE_30D')),
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'claimed', 'sent', 'suppressed')),
    suppression_reason TEXT,
    scheduled_for TIMESTAMPTZ NOT NULL,
    dispatched_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_outbox_status_sched ON collection_dispatch_outbox (status, scheduled_for);
