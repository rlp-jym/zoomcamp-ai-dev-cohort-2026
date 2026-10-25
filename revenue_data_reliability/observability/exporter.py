"""Custom OTEL exporters persisting telemetry to Postgres (SPEC §13).

Self-hosted observability: instead of an external collector (no Grafana,
documented deviation), the OTEL SDK exports straight into the app's
Postgres tables — ``otel_spans``, ``otel_logs``, ``otel_metrics`` — which
``/observability`` then renders in-app.

Each exporter receives ready-made batches from the SDK's batch
processors, so one ``export()`` call maps to one batched insert.

Note: exporter inserts run on the SDK's background threads, outside any
active span context, so the resulting psycopg spans are standalone update
traces of depth one and do not nest inside user traces.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Sequence

from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.sdk._logs._internal import ReadableLogRecord
from opentelemetry.sdk._logs.export import (
    LogRecordExporter,
    LogRecordExportResult,
)
from opentelemetry.sdk.metrics.export import (
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

_logger = logging.getLogger("otel.exporter")
# Do not feed exporter failures back through our own log exporter, but keep
# them visible on stderr for operator diagnosis.
_logger.propagate = False
if not _logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    _logger.addHandler(_handler)


def _ns_to_dt(ns: int | None) -> datetime | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / 1e9, tz=timezone.utc)


def _json(values) -> str:
    """Serialize attribute mappings to JSON, stringifying exotic values."""
    return json.dumps(values, default=str)


class PostgresSpanExporter(SpanExporter):
    """Writes spans into ``otel_spans`` (one batched insert per export)."""

    def shutdown(self, timeout_millis: float = 30000, **kwargs) -> bool:
        return True

    def force_flush(self, timeout_millis: float = 30000) -> bool:
        return True

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not spans:
            return SpanExportResult.SUCCESS
        rows = []
        for span in spans:
            try:
                attrs = dict(span.attributes or {})
                # Volume control: ASGI emits one send span per response body
                # chunk, which dwarfs real spans in otel_spans. Keep the
                # response-start span, drop the body sends.
                if (span.name or "").endswith(" http send") and attrs.get(
                    "asgi.event.type"
                ) == "http.response.body":
                    continue
                # Scope + resource context, but never config values.
                if span.instrumentation_scope:
                    attrs["otel.scope.name"] = span.instrumentation_scope.name
                    if span.instrumentation_scope.version:
                        attrs["otel.scope.version"] = span.instrumentation_scope.version
                if span.resource is not None:
                    for key in ("service.name", "service.version"):
                        val = span.resource.attributes.get(key)
                        if val:
                            attrs[key] = val
                status_code = span.status.status_code.name if span.status else "UNSET"
                if span.status and span.status.description:
                    attrs["otel.status.description"] = span.status.description
                parent = span.parent.span_id if span.parent else None
                duration_ms = (
                    (span.end_time - span.start_time) / 1e6
                    if span.end_time and span.start_time
                    else None
                )
                rows.append(
                    (
                        format(span.context.span_id, "016x"),
                        format(span.context.trace_id, "032x"),
                        format(parent, "016x") if parent else None,
                        span.name or "",
                        _ns_to_dt(span.start_time),
                        _ns_to_dt(span.end_time),
                        duration_ms,
                        status_code,
                        _json(attrs),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                _logger.warning("Failed to serialize span %s: %s", span.name, exc)
        try:
            from backend.db.connection import execute_many

            # Exporter self-writes must not become spans/logs/metrics
            # themselves — otherwise every flush creates standalone noise
            # traces that bury real pipeline traces in /observability.
            with suppress_instrumentation():
                execute_many(
                    """
                    INSERT INTO otel_spans
                        (span_id, trace_id, parent_span_id, name, start_time, end_time,
                         duration_ms, status, attributes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (span_id) DO NOTHING
                    """,
                    rows,
                )
            return SpanExportResult.SUCCESS
        except Exception as exc:
            _logger.warning("Span export failed: %s", exc)
            return SpanExportResult.FAILURE


class PostgresLogRecordExporter(LogRecordExporter):
    """Writes log records into ``otel_logs`` (one batched insert per export)."""

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def export(self, records: Sequence[ReadableLogRecord]) -> LogRecordExportResult:
        if not records:
            return LogRecordExportResult.SUCCESS
        rows = []
        for rec in records:
            try:
                lr = rec.log_record
                span_ctx = lr.trace_id
                span_id = lr.span_id
                attrs = dict(lr.attributes or {})
                if rec.instrumentation_scope:
                    attrs["otel.scope.name"] = rec.instrumentation_scope.name
                rows.append(
                    (
                        format(span_ctx, "032x") if span_ctx else None,
                        format(span_id, "016x") if span_id else None,
                        lr.severity_text or "INFO",
                        str(lr.body) if lr.body is not None else "",
                        _ns_to_dt(lr.timestamp),
                        _json(attrs),
                    )
                )
            except Exception as exc:  # pragma: no cover - defensive
                _logger.warning("Failed to serialize log record: %s", exc)
        try:
            from backend.db.connection import execute_many

            with suppress_instrumentation():
                execute_many(
                    """
                    INSERT INTO otel_logs (trace_id, span_id, level, message, created_at, attributes)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
            return LogRecordExportResult.SUCCESS
        except Exception as exc:
            _logger.warning("Log export failed: %s", exc)
            return LogRecordExportResult.FAILURE


class PostgresMetricExporter(MetricExporter):
    """Writes metric data points into ``otel_metrics``."""

    def __init__(self, preferred_temporality=None, preferred_aggregation=None):
        super().__init__()
        self._preferred_temporality = preferred_temporality
        self._preferred_aggregation = preferred_aggregation

    def export(self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs) -> MetricExportResult:
        rows = []
        try:
            for resource in metrics_data.resource_metrics:
                for scope in resource.scope_metrics:
                    scope_name = scope.scope.name
                    for metric in scope.metrics:
                        self._flatten_metric(metric, scope_name, rows)
            if not rows:
                return MetricExportResult.SUCCESS
            from backend.db.connection import execute_many

            with suppress_instrumentation():
                execute_many(
                    """
                    INSERT INTO otel_metrics (name, value, labels, recorded_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    rows,
                )
            return MetricExportResult.SUCCESS
        except Exception as exc:
            _logger.warning("Metric export failed: %s", exc)
            return MetricExportResult.FAILURE

    def _flatten_metric(self, metric, scope_name: str, rows: list[tuple]) -> None:
        common = {"otel.scope.name": scope_name, "unit": metric.unit}
        for point in getattr(metric.data, "data_points", []):
            if hasattr(point, "value"):
                value = point.value
            elif hasattr(point, "sum"):  # Histogram point
                value = point.sum
                common = {**common, "count": getattr(point, "count", None)}
            else:
                value = None
            labels = {
                **common,
                **{str(k): str(v) for k, v in (point.attributes or {}).items()},
            }
            rows.append(
                (
                    metric.name,
                    value,
                    _json(labels),
                    _ns_to_dt(point.time_unix_nano),
                )
            )

    def shutdown(self, timeout_millis: float = 30_000, **kwargs) -> None:
        return None

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        return True
