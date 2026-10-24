-- Idempotent schema for Revenue Data Reliability Platform
-- Applied on boot via backend/db/connection.py

-- Rename the generated dataset table/columns. Analysis scenarios are separate.
DO $$
BEGIN
    IF to_regclass('scenarios') IS NOT NULL AND to_regclass('datasets') IS NULL THEN
        ALTER TABLE scenarios RENAME TO datasets;
    END IF;
    IF to_regclass('datasets') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = current_schema()
             AND table_name = 'datasets' AND column_name = 'source_scenario'
       )
       AND NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = current_schema()
             AND table_name = 'datasets' AND column_name = 'source_dataset'
       ) THEN
        ALTER TABLE datasets RENAME COLUMN source_scenario TO source_dataset;
    END IF;
    IF to_regclass('runs') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = current_schema()
             AND table_name = 'runs' AND column_name = 'scenario_name'
       ) THEN
        ALTER TABLE runs RENAME COLUMN scenario_name TO dataset_name;
    END IF;
    IF to_regclass('dashboard_cache') IS NOT NULL
       AND EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = current_schema()
             AND table_name = 'dashboard_cache' AND column_name = 'scenario_name'
       ) THEN
        ALTER TABLE dashboard_cache RENAME COLUMN scenario_name TO dataset_name;
    END IF;
END $$;

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
    impact                 VARCHAR,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS datasets (
    name          TEXT PRIMARY KEY,
    status        TEXT NOT NULL DEFAULT 'pending',
    seed          INTEGER,
    table_count   INTEGER NOT NULL DEFAULT 0,
    manifest      JSONB,
    file_hashes   JSONB,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS status VARCHAR DEFAULT 'ready';
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS source_dataset TEXT;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS years_to_backtrack INTEGER;
ALTER TABLE datasets ADD COLUMN IF NOT EXISTS s3_prefix TEXT;
UPDATE datasets SET source_dataset = COALESCE(source_dataset, name)
WHERE source_dataset IS NULL;
UPDATE datasets
SET years_to_backtrack = substring(name from '_y([0-9]+)$')::int
WHERE years_to_backtrack IS NULL AND name ~ '_y[0-9]+$';
-- Every dataset owns a concrete S3 folder. There is no baseline fallback.
UPDATE datasets
SET s3_prefix = 'scenarios/' || name || '/'
WHERE s3_prefix IS NULL;

CREATE TABLE IF NOT EXISTS analysis_scenarios (
    scenario_id          SERIAL PRIMARY KEY,
    title                TEXT NOT NULL,
    outcome              TEXT,
    assessment           TEXT,
    baseline_run         TEXT NOT NULL DEFAULT 'baseline_run',
    open_issues          INTEGER,
    source_anchor_type   TEXT,
    source_anchor_id     TEXT,
    baseline_snapshot    JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE analysis_scenarios ADD COLUMN IF NOT EXISTS baseline_snapshot JSONB;

CREATE TABLE IF NOT EXISTS runs (
    run_id               SERIAL PRIMARY KEY,
    dataset_name         TEXT REFERENCES datasets(name) ON DELETE RESTRICT,
    status               TEXT NOT NULL DEFAULT 'pending',
    current_stage        TEXT,
    progress_percent     INTEGER DEFAULT 0,
    error_message        TEXT,
    duration_seconds     INTEGER,
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
ALTER TABLE runs ADD COLUMN IF NOT EXISTS current_stage TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS progress_percent INTEGER DEFAULT 0;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS error_message TEXT;
ALTER TABLE runs ADD COLUMN IF NOT EXISTS duration_seconds INTEGER;

-- Attach legacy orphaned runs to a real dataset when one exists. No dataset
-- is created at boot: the reviewer loads a pre-generated dataset first.
UPDATE runs
SET dataset_name = (SELECT name FROM datasets ORDER BY created_at, name LIMIT 1)
WHERE dataset_name IS NULL;

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
    status        TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_discussion', 'awaiting_approval', 'remediation_rejected', 'approved', 'resolved', 'escalated', 'dismissed', 'rejected')),
    impact        VARCHAR,
    remediation_attempts INTEGER NOT NULL DEFAULT 0,
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

-- Discussions are polymorphic (anchor_type/anchor_id), so runs and datasets
-- cannot own them through a FK. Application deletes remove discussions
-- explicitly; messages cascade from discussions via the FK below.
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
CREATE INDEX IF NOT EXISTS idx_runs_dataset ON runs (dataset_name);
CREATE INDEX IF NOT EXISTS idx_runs_dataset_status ON runs (dataset_name, status);
DROP INDEX IF EXISTS idx_runs_scenario;
DROP INDEX IF EXISTS idx_runs_scenario_status;
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
CREATE INDEX IF NOT EXISTS idx_otel_spans_trace_id ON otel_spans (trace_id);
CREATE INDEX IF NOT EXISTS idx_otel_logs_trace ON otel_logs (trace_id);
CREATE INDEX IF NOT EXISTS idx_agent_actions_trace_id ON agent_actions (trace_id);
CREATE INDEX IF NOT EXISTS idx_quarantines_run ON quarantines (run_id);
CREATE INDEX IF NOT EXISTS idx_approvals_target ON approvals (target_type, target_id);
CREATE INDEX IF NOT EXISTS idx_publications_run ON publications (run_id);

ALTER TABLE runs ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

-- Batch 4: link validation exceptions to their rule and carry structured
-- evidence for drill-down (reconciliation grain, samples, etc.).
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS rule_id TEXT;
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS details JSONB;

-- Impact column: rule-level default plus exception-level specific narrative.
ALTER TABLE rules ADD COLUMN IF NOT EXISTS impact VARCHAR;
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS impact VARCHAR;
ALTER TABLE exceptions ADD COLUMN IF NOT EXISTS remediation_attempts INTEGER NOT NULL DEFAULT 0;
-- Clear legacy raw-prompt fallback text so the list falls back to rule impact.
UPDATE exceptions SET impact = NULL WHERE impact LIKE '[LLM unavailable%';

-- Rejection loop statuses (idempotent constraint refresh). The old
-- remediation_proposed value is migrated to awaiting_approval.
ALTER TABLE exceptions DROP CONSTRAINT IF EXISTS exceptions_status_check;
UPDATE exceptions SET status = 'awaiting_approval' WHERE status = 'remediation_proposed';
ALTER TABLE exceptions ADD CONSTRAINT exceptions_status_check
    CHECK (status IN ('open', 'in_discussion', 'awaiting_approval', 'remediation_rejected', 'approved', 'resolved', 'escalated', 'dismissed', 'rejected'));

-- Batch 6 / Phase 3 (§19): precomputed dashboard payload.
-- The / route never scans S3 Parquet inside a request; the scheduler job
-- (dashboard_refresh) recomputes the payload and upserts it here.
CREATE TABLE IF NOT EXISTS dashboard_cache (
    cache_key      TEXT PRIMARY KEY,
    dataset_name   TEXT,
    refreshed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    data           JSONB NOT NULL
);
ALTER TABLE dashboard_cache ADD COLUMN IF NOT EXISTS dataset_name TEXT;
UPDATE dashboard_cache SET dataset_name = 'baseline_run' WHERE dataset_name IS NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_dashboard_cache_dataset ON dashboard_cache (dataset_name);
DROP INDEX IF EXISTS uq_dashboard_cache_scenario;

-- Runs must always belong to a dataset. RESTRICT prevents accidental
-- dataset deletion while runs still reference it.
DO $$
DECLARE con record;
BEGIN
    FOR con IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'runs'::regclass
          AND contype = 'f'
          AND confrelid = 'datasets'::regclass
    LOOP
        EXECUTE format('ALTER TABLE runs DROP CONSTRAINT %I', con.conname);
    END LOOP;
    ALTER TABLE runs ADD CONSTRAINT runs_dataset_name_fkey
        FOREIGN KEY (dataset_name) REFERENCES datasets(name) ON DELETE RESTRICT;
END $$;
