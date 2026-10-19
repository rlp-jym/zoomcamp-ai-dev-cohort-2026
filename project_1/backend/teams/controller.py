"""Controller agent (SPEC §12, §18, §3 continuously verifies published data
reliability on a schedule and opens alerts, posts triage notes, escalates
critical findings to the Director.

The six alert types (SPEC §12):

- ``STALE_PUBLISHED``
- ``SOURCE_HASH_MISMATCH``
- ``AUDIT_ROW_MISSING``
- ``THREAD_ANCHOR_ORPHANED``
- ``PUBLISHED_RECORD_FAILS_REVALIDATION``
- ``RECON_DRIFT``
"""

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from opentelemetry import trace

from backend.config import settings
from backend.db.connection import fetch_all, fetch_one
from backend.services import alerts as alerts_svc
from backend.services import llm_client, stub_data
from backend.services import messages as msg_svc
from backend.services import publications as pub_svc
from backend.skills import load_skill
from backend.teams.base import BaseAgent

logger = logging.getLogger(__name__)

# Cache of the last verified scenario manifest (avoids re-downloading every
# S3 object on each controller cycle when the manifest has not changed).
_verified_manifest_key: str | None = None


class ControllerAgent(BaseAgent):
    """Controller agent — verification findings and alert triage."""

    def __init__(self):
        super().__init__("controller")

    # ------------------------------------------------------------------ §12
    def _raise(
        self,
        alert_type: str,
        anchor_type: str,
        anchor_id: str,
        detail: str,
        trace_id: str | None,
        escalate: bool = False,
    ) -> dict:
        """Raise one alert (deduplicated) with its destinations.

        Fresh alert: logged to ``agent_actions``, Controller triage note on
        the anchor thread, and — for critical alerts — an escalation note
        posted by the Director persona on the same thread.
        """
        res = alerts_svc.raise_alert(
            alert_type, anchor_type, anchor_id, detail, trace_id
        )
        self.log_action(
            "alert_raised",
            anchor_type,
            str(anchor_id),
            trace_id,
            {
                "alert_type": alert_type,
                "alert_id": res["alert_id"],
                "deduplicated": not res["created"],
            },
        )
        if res["created"]:
            self.post_alert_triage(
                alert_type, anchor_type, str(anchor_id),
                res["severity"], detail, trace_id,
            )
            if escalate and res["severity"] == "critical":
                self._escalate_to_director(
                    alert_type, anchor_type, str(anchor_id),
                    res["severity"], detail, trace_id,
                )
        return res

    def _escalate_to_director(
        self,
        alert_type: str,
        anchor_type: str,
        anchor_id: str,
        severity: str,
        detail: str,
        trace_id: str | None,
    ) -> None:
        """Critical alerts escalate to the Director on the anchor thread."""
        content = (
            f"ESCALATION [{severity.upper()}]: {alert_type} requires "
            f"Director review. {detail}"
        )
        msg_svc.post_message(
            anchor_type,
            str(anchor_id),
            stub_data.get_persona("director"),
            content,
            trace_id=trace_id,
            evidence={"escalation": True, "alert_type": alert_type},
        )
        self.log_action(
            "critical_escalation", anchor_type, str(anchor_id), trace_id,
            {"alert_type": alert_type, "severity": severity},
        )
        logger.warning("Controller: escalated %s to Director.", alert_type)

    def verify_stale_published(self, trace_id: str | None = None) -> dict | None:
        """Check whether the active publication is older than its SLA.

        Reads the latest ``publications`` row (SPEC §12: the anchor for
        ``STALE_PUBLISHED`` is the published run). If ``published_at`` is
        older than ``CONTROLLER_STALE_HOURS`` (default 24h), raises the
        alert (deduplicated) with its destinations.
        """
        pub = fetch_one(
            """
            SELECT p.publication_id, p.run_id, p.published_at,
                   r.scenario_name
            FROM publications p
            LEFT JOIN runs r ON r.run_id = p.run_id
            ORDER BY p.publication_id DESC
            LIMIT 1
            """
        )
        if not pub:
            logger.info("Controller: no publication yet; nothing to verify.")
            return None

        published_at = pub["published_at"]
        if published_at is None:
            logger.info(
                "Controller: publication #%s has no published_at; skipping.",
                pub["publication_id"],
            )
            return None

        now = datetime.now(timezone.utc)
        threshold = timedelta(hours=settings.controller_stale_hours)
        age = now - published_at
        payload = {
            "publication_id": pub["publication_id"],
            "run_id": pub["run_id"],
            "scenario": pub["scenario_name"],
            "published_at": published_at.isoformat(),
            "age_hours": round(age.total_seconds() / 3600, 2),
            "stale_threshold_hours": settings.controller_stale_hours,
        }

        if age < threshold:
            logger.info(
                "Controller: publication #%s for scenario %s is fresh "
                "(age %.1fh < %.0fh threshold).",
                pub["publication_id"], pub["scenario_name"],
                age.total_seconds() / 3600, threshold.total_seconds() / 3600,
            )
            return None

        finding = (
            f"STALE_PUBLISHED: publication #{pub['publication_id']} for scenario "
            f"{pub['scenario_name']} ran {age.total_seconds() / 3600:.1f}h ago "
            f"(threshold {threshold.total_seconds() / 3600:.0f}h)."
        )
        alert = self._raise("STALE_PUBLISHED", "run", str(pub["run_id"]),
                            finding, trace_id)
        logger.warning("Controller: %s", finding)
        return {"finding": finding, "alert": alert, **payload}

    def check_source_hash_mismatch(self, trace_id: str | None = None) -> dict | None:
        """Critical: S3 Parquet hash differs from the registered manifest.

        The manifest JSONB on ``scenarios`` is the registered source of
        truth. Results are cached per manifest so unchanged bundles are not
        re-downloaded on every cycle (Filebase throttling).
        """
        global _verified_manifest_key
        row = fetch_one(
            """
            SELECT name, manifest FROM scenarios
            WHERE manifest IS NOT NULL
            ORDER BY updated_at DESC, name
            LIMIT 1
            """
        )
        if not row:
            return None
        key = json.dumps(row["manifest"], sort_keys=True, default=str)
        if key == _verified_manifest_key:
            return None  # unchanged manifest, already verified
        _verified_manifest_key = key

        from backend.storage import verify_manifest

        results = verify_manifest(row["name"], row["manifest"])
        bad = [k for k, ok in results.items() if not ok]
        if not bad:
            logger.info(
                "Controller: manifest for %s verified (%d files).",
                row["name"], len(results),
            )
            return None
        finding = (
            f"SOURCE_HASH_MISMATCH: {len(bad)} parquet file(s) under "
            f"scenarios/{row['name']} no longer match the registered "
            f"manifest: {', '.join(bad)}."
        )
        alert = self._raise("SOURCE_HASH_MISMATCH", "scenario", row["name"],
                            finding, trace_id, escalate=True)
        return {"finding": finding, "alert": alert, "mismatched": bad}

    def check_audit_row_missing(self, trace_id: str | None = None) -> dict | None:
        """High: the published action lacks an ``agent_actions`` row.

        A publication whose run has no agent audit trail at all cannot be
        traced back to any verified agent step (SPEC §12).
        """
        pub = fetch_one(
            """
            SELECT p.publication_id, p.run_id
            FROM publications p
            ORDER BY p.publication_id DESC
            LIMIT 1
            """
        )
        if not pub:
            return None
        hit = fetch_one(
            """
            SELECT 1 AS ok FROM agent_actions
            WHERE anchor_type = 'run' AND anchor_id = %s
            LIMIT 1
            """,
            (str(pub["run_id"]),),
        )
        if hit:
            return None
        finding = (
            f"AUDIT_ROW_MISSING: publication #{pub['publication_id']} "
            f"(run {pub['run_id']}) has no agent_actions audit trail."
        )
        alert = self._raise("AUDIT_ROW_MISSING", "publication",
                            str(pub["publication_id"]), finding, trace_id)
        # The finding row this writes is itself the missing audit entry, so
        # subsequent cycles see the trail and stay quiet.
        self.log_action(
            "published_audit_entry", "run", str(pub["run_id"]), trace_id,
            {"publication_id": pub["publication_id"], "backfilled": True},
        )
        return {"finding": finding, "alert": alert}

    def check_thread_anchor_orphaned(self, trace_id: str | None = None) -> list[dict]:
        """Medium: a discussion anchor references a deleted run/exception."""
        rows = fetch_all(
            """
            SELECT d.discussion_id, d.anchor_type, d.anchor_id
            FROM discussions d
            WHERE (d.anchor_type = 'run'
                   AND NOT EXISTS (SELECT 1 FROM runs r
                                   WHERE r.run_id::text = d.anchor_id))
               OR (d.anchor_type = 'exception'
                   AND NOT EXISTS (SELECT 1 FROM exceptions e
                                   WHERE e.exception_id::text = d.anchor_id))
            LIMIT 5
            """
        )
        out = []
        for r in rows:
            finding = (
                f"THREAD_ANCHOR_ORPHANED: thread #{r['discussion_id']} is "
                f"anchored to {r['anchor_type']}:{r['anchor_id']} which no "
                "longer exists."
            )
            alert = self._raise("THREAD_ANCHOR_ORPHANED", "analysis",
                                str(r["discussion_id"]), finding, trace_id)
            out.append({"finding": finding, "alert": alert})
        return out

    def check_published_revalidation(self, trace_id: str | None = None) -> dict | None:
        """Critical: published records fail re-validation.

        Fans the published invoice lines (quarantine overlay applied) out
        against the ``items`` and ``invoices`` parquet files — the grain of
        ``VAL_FK_ITEM_EXISTS`` / ``VAL_INV_LN_REF`` — and alerts on any
        orphaned foreign key.
        """
        pub = fetch_one(
            """
            SELECT p.publication_id, p.run_id, r.scenario_name
            FROM publications p
            LEFT JOIN runs r ON r.run_id = p.run_id
            ORDER BY p.publication_id DESC
            LIMIT 1
            """
        )
        if not pub or not pub["scenario_name"]:
            return None
        q = pub_svc.get_published_data_query(pub["scenario_name"])
        if not q:
            return None
        from backend.storage.duckdb_client import query_rows

        scenario = pub["scenario_name"]
        base = f"s3://{settings.r2_bucket}/scenarios/{scenario}"
        sql = f"""
            SELECT
                COUNT(*) FILTER (WHERE i.item_id IS NULL)
                    AS item_orphans,
                COUNT(*) FILTER (WHERE v.invoice_id IS NULL)
                    AS invoice_orphans
            FROM ({q["sql"]}) bil
            LEFT JOIN read_parquet('{base}/items.parquet') i
                ON bil.item_id = i.item_id
            LEFT JOIN read_parquet('{base}/invoices.parquet') v
                ON bil.invoice_id = v.invoice_id
        """
        res = query_rows(sql)[0]
        failed = (res["item_orphans"] or 0) + (res["invoice_orphans"] or 0)
        if failed == 0:
            logger.info(
                "Controller: re-validation of published run %s passed.",
                pub["run_id"],
            )
            return None
        finding = (
            f"PUBLISHED_RECORD_FAILS_REVALIDATION: published run "
            f"{pub['run_id']} has {failed} record(s) failing re-validation "
            f"({res['item_orphans']} orphaned item_id, "
            f"{res['invoice_orphans']} orphaned invoice_id)."
        )
        alert = self._raise("PUBLISHED_RECORD_FAILS_REVALIDATION", "publication",
                            str(pub["publication_id"]), finding, trace_id,
                            escalate=True)
        return {"finding": finding, "alert": alert,
                "item_orphans": res["item_orphans"],
                "invoice_orphans": res["invoice_orphans"]}

    def check_recon_drift(self, trace_id: str | None = None) -> dict | None:
        """Critical: post-publication billings vs GL above tolerance."""
        pub = fetch_one(
            """
            SELECT p.publication_id, p.run_id
            FROM publications p
            ORDER BY p.publication_id DESC
            LIMIT 1
            """
        )
        if not pub:
            return None
        worst = fetch_all(
            """
            SELECT period, item_category, variance_pct
            FROM reconciliations
            WHERE run_id = %s AND status = 'fail'
            ORDER BY ABS(variance_pct) DESC
            LIMIT 3
            """,
            (pub["run_id"],),
        )
        if not worst:
            return None
        sample = "; ".join(
            f"{w['period']} {w['item_category']} {float(w['variance_pct']):.1f}%"
            for w in worst
        )
        finding = (
            f"RECON_DRIFT: published run {pub['run_id']} has "
            f"{len(worst)} reconciliation row(s) above tolerance "
            f"(worst: {sample})."
        )
        alert = self._raise("RECON_DRIFT", "publication",
                            str(pub["publication_id"]), finding, trace_id,
                            escalate=True)
        return {"finding": finding, "alert": alert, "drifted": len(worst)}

    # ------------------------------------------------------------- messaging
    def post_verification_finding(
        self,
        anchor_type: str,
        anchor_id: str,
        finding: str,
        severity: str = "medium",
        trace_id: str | None = None,
    ) -> dict:
        """Post a verification finding to the given anchor thread.

        Args:
            anchor_type: 'run', 'exception', or 'analysis'.
            anchor_id: The anchor row identifier.
            finding: Human-readable description of what was found.
            severity: One of 'critical', 'high', 'medium', 'low'.
            trace_id: Distributed trace identifier.

        Returns:
            The posted message dict.
        """
        msg = msg_svc.post_message(
            anchor_type,
            str(anchor_id),
            self.persona,
            finding,
            trace_id=trace_id,
            evidence={"severity": severity, "finding": True},
        )

        self.log_action(
            "verification_finding",
            anchor_type,
            str(anchor_id),
            trace_id,
            {"severity": severity, "finding": finding},
        )

        return msg

    def post_alert_triage(
        self,
        alert_type: str,
        anchor_type: str,
        anchor_id: str,
        severity: str,
        detail: str,
        trace_id: str | None = None,
    ) -> dict:
        """Post an alert triage note using the controller_triage_note skill."""
        try:
            skill_text = load_skill("controller_triage_note")
        except (ValueError, FileNotFoundError):
            skill_text = ""

        user_prompt = (
            f"Alert type: {alert_type}\n"
            f"Severity: {severity}\n"
            f"Detail: {detail}"
        )

        if skill_text:
            content = llm_client.call_llm(skill_text, user_prompt)
        else:
            content = llm_client._template_fallback(user_prompt)

        msg = msg_svc.post_message(
            anchor_type,
            str(anchor_id),
            self.persona,
            content,
            trace_id=trace_id,
            evidence={"alert_type": alert_type, "severity": severity, "triage": True},
        )

        self.log_action(
            "alert_triage",
            anchor_type,
            str(anchor_id),
            trace_id,
            {"alert_type": alert_type, "severity": severity},
        )

        return msg


def run_controller_verification() -> dict:
    """Scheduler job: run every Controller check inside its own trace.

    Share a ``trace_id`` between the OTEL span tree, agent actions, and the
    alerts opened from these findings. Each check is isolated so one
    failure (e.g. S3 throttling) does not kill the whole cycle.
    """
    with trace.get_tracer("scheduler.controller").start_as_current_span(
        "controller.verification_job"
    ) as span:
        ctx = span.get_span_context()
        trace_id = (
            format(ctx.trace_id, "032x")
            if ctx and ctx.trace_id
            else uuid.uuid4().hex
        )
        agent = ControllerAgent()
        results: dict = {"trace_id": trace_id}
        for name, fn in (
            ("stale_published", agent.verify_stale_published),
            ("source_hash_mismatch", agent.check_source_hash_mismatch),
            ("audit_row_missing", agent.check_audit_row_missing),
            ("thread_anchor_orphaned", agent.check_thread_anchor_orphaned),
            ("published_revalidation", agent.check_published_revalidation),
            ("recon_drift", agent.check_recon_drift),
        ):
            try:
                results[name] = fn(trace_id)
            except Exception as exc:  # keep the cycle running
                logger.exception("Controller check %s failed.", name)
                results[name] = {"error": str(exc)}
        return results
