-- Idempotent schema for Revenue Data Reliability Platform
-- Applied on boot via backend/db/connection.py

CREATE TABLE IF NOT EXISTS personas (
    persona_id   TEXT PRIMARY KEY,
    type         TEXT NOT NULL CHECK (type IN ('human', 'agent')),
    title        TEXT NOT NULL,
    role         TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS rules (
    rule_id                TEXT PRIMARY KEY,
    description            TEXT NOT NULL,
    severity               TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    sql                    TEXT NOT NULL,
    expected_detection_rule TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scenarios (
    name          TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'pending',
    seed          INTEGER,
    table_count   INTEGER NOT NULL DEFAULT 0,
    manifest      JSONB,
    file_hashes   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_scenarios (
    scenario_id          SERIAL PRIMARY KEY,
    title                TEXT NOT NULL,
    outcome              TEXT,
    assessment           TEXT,
    baseline_run         TEXT NOT NULL DEFAULT 'baseline_run',
    source_anchor_type   TEXT,
    source_anchor_id     TEXT,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS runs (
    run_id               SERIAL PRIMARY KEY,
    scenario_name        TEXT REFERENCES scenarios(name) ON DELETE SET NULL,
    status               TEXT NOT NULL DEFAULT 'pending',
    started_at           TIMESTAMPTZ,
    finished_at          TIMESTAMPTZ,
    duration             TEXT,
    triggered_by         TEXT,
    trace_id             TEXT,
    validations_total    INTEGER NOT NULL DEFAULT 0,
    validations_failed   INTEGER NOT NULL DEFAULT 0,
    exceptions_created   INTEGER NOT NULL DEFAULT 0,
    published            BOOLEAN NOT NULL DEFAULT FALSE,
    published_at         TIMESTAMPTZ,
    approved_at          TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS validations (
    validation_id    SERIAL PRIMARY KEY,
    run_id           INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    rule_id          TEXT NOT NULL REFERENCES rules(rule_id) ON DELETE CASCADE,
    status           TEXT NOT NULL,
    summary_count    INTEGER NOT NULL DEFAULT 0,
    sampled_failures  JSONB,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (run_id, rule_id)
);

CREATE TABLE IF NOT EXISTS reconciliations (
    reconciliation_id SERIAL PRIMARY KEY,
    run_id            INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    period            TEXT NOT NULL,
    account_id        TEXT NOT NULL,
    item_category     TEXT NOT NULL,
    billings          NUMERIC,
    gl                NUMERIC,
    variance_pct      NUMERIC,
    status            TEXT NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS exceptions (
    exception_id  SERIAL PRIMARY KEY,
    run_id        INTEGER REFERENCES runs(run_id) ON DELETE SET NULL,
    type          TEXT NOT NULL CHECK (type IN ('validation', 'reconciliation', 'quarantine', 'controller_finding')),
    severity      TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    period        TEXT,
    title         TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_discussion', 'remediation_proposed', 'approved', 'resolved')),
    trace_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS quarantines (
    quarantine_id  SERIAL PRIMARY KEY,
    run_id         INTEGER REFERENCES runs(run_id) ON DELETE SET NULL,
    exception_id   INTEGER REFERENCES exceptions(exception_id) ON DELETE SET NULL,
    reason_code    TEXT NOT NULL,
    record_keys    JSONB,
    created_by     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    approval_id   SERIAL PRIMARY KEY,
    target_type   TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    persona_id    TEXT REFERENCES personas(persona_id) ON DELETE SET NULL,
    decision      TEXT NOT NULL,
    comment       TEXT,
    trace_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS publications (
    publication_id  SERIAL PRIMARY KEY,
    run_id          INTEGER NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    published_by    TEXT REFERENCES personas(persona_id) ON DELETE SET NULL,
    pointer         TEXT,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS discussions (
    discussion_id  SERIAL PRIMARY KEY,
    anchor_type    TEXT NOT NULL CHECK (anchor_type IN ('run', 'exception', 'analysis')),
    anchor_id      TEXT NOT NULL,
    title          TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (anchor_type, anchor_id)
);

CREATE TABLE IF NOT EXISTS messages (
    message_id     SERIAL PRIMARY KEY,
    discussion_id  INTEGER NOT NULL REFERENCES discussions(discussion_id) ON DELETE CASCADE,
    persona_id     TEXT REFERENCES personas(persona_id) ON DELETE SET NULL,
    content        TEXT NOT NULL,
    trace_id       TEXT,
    evidence       JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alerts (
    alert_id      SERIAL PRIMARY KEY,
    alert_type    TEXT NOT NULL,
    anchor_type   TEXT,
    anchor_id     TEXT,
    severity      TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    status        TEXT NOT NULL DEFAULT 'open',
    trace_id      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS agent_actions (
    action_id    SERIAL PRIMARY KEY,
    agent_id     TEXT REFERENCES personas(persona_id) ON DELETE SET NULL,
    action       TEXT NOT NULL,
    anchor_type  TEXT,
    anchor_id    TEXT,
    trace_id     TEXT,
    payload      JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS otel_spans (
    span_id        TEXT PRIMARY KEY,
    trace_id       TEXT NOT NULL,
    parent_span_id TEXT,
    name           TEXT NOT NULL,
    start_time     TIMESTAMPTZ,
    end_time       TIMESTAMPTZ,
    duration_ms    NUMERIC,
    status         TEXT,
    attributes     JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS otel_logs (
    log_id       SERIAL PRIMARY KEY,
    trace_id     TEXT,
    span_id      TEXT,
    level        TEXT,
    message      TEXT,
    attributes   JSONB,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS otel_metrics (
    metric_id    SERIAL PRIMARY KEY,
    name         TEXT NOT NULL,
    value        NUMERIC,
    labels       JSONB,
    recorded_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_runs_scenario ON runs (scenario_name);
CREATE INDEX IF NOT EXISTS idx_validations_run ON validations (run_id);
CREATE INDEX IF NOT EXISTS idx_reconciliations_run ON reconciliations (run_id);
CREATE INDEX IF NOT EXISTS idx_exceptions_run ON exceptions (run_id);
CREATE INDEX IF NOT EXISTS idx_discussions_anchor ON discussions (anchor_type, anchor_id);
CREATE INDEX IF NOT EXISTS idx_messages_discussion ON messages (discussion_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages (created_at);
CREATE INDEX IF NOT EXISTS idx_alerts_type_anchor ON alerts (alert_type, anchor_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_trace ON agent_actions (trace_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_anchor ON agent_actions (anchor_type, anchor_id);
CREATE INDEX IF NOT EXISTS idx_otel_spans_trace ON otel_spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_otel_logs_trace ON otel_logs (trace_id);
CREATE INDEX IF NOT EXISTS idx_quarantines_run ON quarantines (run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_target ON approvals (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_publications_run ON publications (run_id);

ALTER TABLE runs ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

-- Batch 4: link validation exceptions to their rule and carry structured
-- evidence for drill-down (reconciliation grain, samples, etc.).
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS rule_id TEXT;
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS details JSONB;

-- Batch 6 / Phase 3 (§19): precomputed dashboard payload.
-- The / route never scans S3 Parquet inside a request; the scheduler job
-- (dashboard_refresh) recomputes the payload and upserts it here.
CREATE TABLE IF NOT EXISTS dashboard_cache (
    cache_key    TEXT PRIMARY KEY,
    refreshed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    data         JSONB NOT NULL
);
