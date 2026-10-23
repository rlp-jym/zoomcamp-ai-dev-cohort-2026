"""Hardcoded stub data for Batch 1 UI skeleton (no DB, no agents)."""


PERSONAS = [
    {"id": "analyst", "type": "human", "title": "FP&A Analyst"},
    {"id": "manager", "type": "human", "title": "FP&A Manager"},
    {"id": "director", "type": "human", "title": "Director of FP&A"},
    {"id": "orchestrator", "type": "agent", "title": "Pipeline Orchestrator"},
    {"id": "de", "type": "agent", "title": "Data Engineer"},
    {"id": "dq", "type": "agent", "title": "Data Quality"},
    {"id": "fa", "type": "agent", "title": "Financial Impact Agent"},
    {"id": "controller", "type": "agent", "title": "Controller"},
]


def get_persona(persona_id):
    for p in PERSONAS:
        if p["id"] == persona_id:
            return p
    return PERSONAS[0]


def is_agent(persona_id):
    p = get_persona(persona_id)
    return p["type"] == "agent"


# ---------- Dashboard KPIs ----------
KPIS = [
    {
        "id": "revenue",
        "title": "Revenue (MTD)",
        "value": "$4.2M",
        "delta": "+3.1%",
        "trend": "up",
        "thread_id": "kpi-revenue",
    },
    {
        "id": "billings",
        "title": "Billings (MTD)",
        "value": "$4.0M",
        "delta": "+1.8%",
        "trend": "up",
        "thread_id": "kpi-billings",
    },
    {
        "id": "gl_variance",
        "title": "General Ledger Variance %",
        "value": "1.4%",
        "delta": "-0.3pp",
        "trend": "down",
        "thread_id": "kpi-gl-variance",
    },
    {
        "id": "exceptions_open",
        "title": "Open Exceptions",
        "value": "7",
        "delta": "+2",
        "trend": "up",
        "thread_id": "kpi-exceptions",
    },
    {
        "id": "dq_pass_rate",
        "title": "DQ Pass Rate",
        "value": "94.6%",
        "delta": "+0.4pp",
        "trend": "up",
        "thread_id": "kpi-dq-pass",
    },
    {
        "id": "published_runs",
        "title": "Published Runs",
        "value": "3",
        "delta": "0",
        "trend": "flat",
        "thread_id": "kpi-published",
    },
]


# ---------- Exceptions ----------
EXCEPTIONS = [
    {
        "id": 1,
        "type": "validation",
        "severity": "critical",
        "period": "2025-03",
        "title": "Orphaned item ids in invoice_lines",
        "status": "open",
        "trace_id": "tr-1001",
    },
    {
        "id": 2,
        "type": "reconciliation",
        "severity": "high",
        "period": "2025-03",
        "title": "Billings vs General Ledger variance 4.2%",
        "status": "in_discussion",
        "trace_id": "tr-1002",
    },
    {
        "id": 3,
        "type": "validation",
        "severity": "medium",
        "period": "2025-02",
        "title": "Duplicate invoice line detected",
        "status": "awaiting_approval",
        "trace_id": "tr-1003",
    },
    {
        "id": 4,
        "type": "validation",
        "severity": "high",
        "period": "2025-03",
        "title": "Missing customer mapping",
        "status": "open",
        "trace_id": "tr-1004",
    },
    {
        "id": 5,
        "type": "reconciliation",
        "severity": "low",
        "period": "2025-01",
        "title": "Minor recon drift within tolerance",
        "status": "resolved",
        "trace_id": "tr-1005",
    },
    {
        "id": 6,
        "type": "quarantine",
        "severity": "high",
        "period": "2025-03",
        "title": "Quarantined 12 stale FX rows",
        "status": "approved",
        "trace_id": "tr-1006",
    },
    {
        "id": 7,
        "type": "controller_finding",
        "severity": "critical",
        "period": "2025-03",
        "title": "Stale published run older than SLA",
        "status": "open",
        "trace_id": "tr-1007",
    },
    {
        "id": 8,
        "type": "validation",
        "severity": "medium",
        "period": "2025-02",
        "title": "FX rate missing for EUR",
        "status": "in_discussion",
        "trace_id": "tr-1008",
    },
]


# ---------- Runs ----------
RUNS = [
    {
        "id": 1,
        "scenario": "baseline_run",
        "status": "published",
        "started_at": "2025-03-01 09:12",
        "duration": "4m 12s",
        "published": True,
    },
    {
        "id": 2,
        "scenario": "baseline_run",
        "status": "completed",
        "started_at": "2025-03-15 11:03",
        "duration": "3m 58s",
        "published": False,
    },
    {
        "id": 3,
        "scenario": "q1_restate",
        "status": "failed",
        "started_at": "2025-03-20 14:22",
        "duration": "1m 04s",
        "published": False,
    },
    {
        "id": 4,
        "scenario": "baseline_run",
        "status": "completed",
        "started_at": "2025-02-28 08:45",
        "duration": "4m 01s",
        "published": False,
    },
    {
        "id": 5,
        "scenario": "fx_gap_scenario",
        "status": "completed",
        "started_at": "2025-02-10 10:30",
        "duration": "3m 40s",
        "published": False,
    },
    {
        "id": 6,
        "scenario": "baseline_run",
        "status": "running",
        "started_at": "2025-03-22 16:00",
        "duration": "-",
        "published": False,
    },
]

RUN_DETAIL = {
    "id": 1,
    "scenario": "baseline_run",
    "status": "published",
    "started_at": "2025-03-01 09:12:00",
    "finished_at": "2025-03-01 09:16:12",
    "duration": "4m 12s",
    "triggered_by": "analyst",
    "trace_id": "tr-run-1",
    "validations_total": 47,
    "validations_failed": 3,
    "exceptions_created": 2,
    "published": True,
    "published_at": "2025-03-01 09:20:00",
}


# ---------- Scenarios ----------
SCENARIOS = [
    {"name": "baseline_run", "status": "registered", "tables": 16, "seed": 9, "created_at": "2025-02-20"},
    {"name": "q1_restate", "status": "registered", "tables": 16, "seed": 11, "created_at": "2025-03-18"},
    {"name": "fx_gap_scenario", "status": "registered", "tables": 16, "seed": 21, "created_at": "2025-02-05"},
    {"name": "duplicate_invoice", "status": "pending", "tables": 0, "seed": 33, "created_at": "2025-03-21"},
    {"name": "stale_load", "status": "registered", "tables": 16, "seed": 44, "created_at": "2025-01-30"},
]


# ---------- Audit ----------
AUDIT_ROWS = [
    {"id": 1, "agent": "orchestrator", "action": "run_started", "anchor": "run:1", "trace_id": "tr-run-1", "created_at": "2025-03-01 09:12"},
    {"id": 2, "agent": "dq", "action": "validation_summary", "anchor": "run:1", "trace_id": "tr-run-1", "created_at": "2025-03-01 09:14"},
    {"id": 3, "agent": "de", "action": "remediation_proposal", "anchor": "exception:1", "trace_id": "tr-1001", "created_at": "2025-03-01 09:30"},
    {"id": 4, "agent": "fa", "action": "impact_narrative", "anchor": "exception:1", "trace_id": "tr-1001", "created_at": "2025-03-01 09:32"},
    {"id": 5, "agent": "manager", "action": "approval_go_live", "anchor": "run:1", "trace_id": "tr-run-1", "created_at": "2025-03-01 09:20"},
    {"id": 6, "agent": "controller", "action": "verification_finding", "anchor": "run:1", "trace_id": "tr-1007", "created_at": "2025-03-22 12:00"},
    {"id": 7, "agent": "de", "action": "quarantine_records", "anchor": "exception:6", "trace_id": "tr-1006", "created_at": "2025-03-05 15:10"},
    {"id": 8, "agent": "fa", "action": "analysis_thread_opened", "anchor": "analysis:kpi-revenue", "trace_id": "tr-2001", "created_at": "2025-03-10 10:00"},
]


# ---------- Observability ----------
TRACES = [
    {"trace_id": "tr-run-1", "name": "POST /runs/1/pipeline", "duration": "4.2s", "status": "ok", "spans": 12},
    {"trace_id": "tr-1001", "name": "GET /exceptions/1", "duration": "120ms", "status": "ok", "spans": 5},
    {"trace_id": "tr-1002", "name": "GET /exceptions/2", "duration": "98ms", "status": "ok", "spans": 4},
    {"trace_id": "tr-1007", "name": "controller verification", "duration": "310ms", "status": "error", "spans": 7},
    {"trace_id": "tr-2001", "name": "analysis thread post", "duration": "55ms", "status": "ok", "spans": 3},
    {"trace_id": "tr-obs-1", "name": "GET /observability", "duration": "80ms", "status": "ok", "spans": 4},
]

EXPANDED_TRACE = "tr-run-1"
EXPANDED_SPANS = [
    {"id": "s1", "parent": None, "name": "POST /runs/1/pipeline", "duration": "4.2s", "status": "ok", "depth": 0},
    {"id": "s2", "parent": "s1", "name": "orchestrator.run_pipeline", "duration": "4.1s", "status": "ok", "depth": 1},
    {"id": "s3", "parent": "s2", "name": "dq.run_validations", "duration": "1.8s", "status": "ok", "depth": 2},
    {"id": "s4", "parent": "s3", "name": "duckdb.execute_rule", "duration": "0.9s", "status": "ok", "depth": 3},
    {"id": "s5", "parent": "s3", "name": "duckdb.execute_rule", "duration": "0.7s", "status": "ok", "depth": 3},
    {"id": "s6", "parent": "s2", "name": "reconciliation.run", "duration": "1.2s", "status": "ok", "depth": 2},
    {"id": "s7", "parent": "s2", "name": "agent.post (de)", "duration": "0.4s", "status": "ok", "depth": 2},
    {"id": "s8", "parent": "s2", "name": "agent.post (fa)", "duration": "0.3s", "status": "ok", "depth": 2},
]


# ---------- Threads (seeded messages) ----------
def _msg(persona_id, content, when="2025-03-01 09:13"):
    return {
        "persona_id": persona_id,
        "persona_title": get_persona(persona_id)["title"],
        "is_agent": is_agent(persona_id),
        "content": content,
        "created_at": when,
        "evidence": None,
    }


THREADS = {}
# KPI analysis threads: 2 stub messages each
for k in KPIS:
    tid = k["thread_id"]
    THREADS[("analysis", tid)] = [
        _msg("analyst", f"Noticed {k['title']} moved {k['delta']} this period; investigating drivers.", "2025-03-10 09:00"),
        _msg("fa", f"Impact narrative: {k['title']} change is within expected range given seasonality.", "2025-03-10 09:15"),
    ]

# Run 1 thread: 3 messages (orchestrator, dq, manager)
THREADS[("run", "1")] = [
    _msg("orchestrator", "Run started for scenario baseline_run (seed=9).", "2025-03-01 09:12"),
    _msg("dq", "Validation complete: 47 rules executed, 3 failed. Summary posted.", "2025-03-01 09:14"),
    _msg("manager", "Approved go-live for this run.", "2025-03-01 09:20"),
]

# Exception detail threads
for e in EXCEPTIONS:
    THREADS[("exception", str(e["id"]))] = [
        _msg("dq", f"Detected {e['title']} during validation run.", "2025-03-01 09:15"),
        _msg("de", "Remediation proposal posted: re-run pipeline for affected month.", "2025-03-01 09:30"),
    ]

# Exception 1 gets an extra Financial Impact Agent message for richness
THREADS[("exception", "1")].append(
    _msg("fa", "Financial impact: ~$18k revenue at risk in period 2025-03.", "2025-03-01 09:32")
)