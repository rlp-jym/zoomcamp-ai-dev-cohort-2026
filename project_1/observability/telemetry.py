"""OTEL SDK setup: auto-instrumentation + Postgres exporters + retention.

Wired once at app construction (``setup_telemetry(app)``) so that:

* psycopg is instrumented before the connection pool opens, so every
  SQL statement is traced.
* FastAPI (ASGI) is instrumented before the first request.
* botocore/boto3 S3 calls are instrumented.
* DuckDB has no auto-instrumentor; ``backend.storage.duckdb_client``
  creates manual spans for each query.

 Logs raised via Python logging are exported through a ``LoggingHandler``
 so in-app messages appear as linked OTEL logs.
"""

import logging

from opentelemetry import metrics, trace
from opentelemetry.instrumentation.botocore import BotocoreInstrumentor
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.psycopg import PsycopgInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import OTELResourceDetector, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from backend.config import settings
from observability.exporter import (
    PostgresLogRecordExporter,
    PostgresMetricExporter,
    PostgresSpanExporter,
)

tracer_provider: TracerProvider | None = None
meter_provider: MeterProvider | None = None
logger_provider: LoggerProvider | None = None


def _build_resource() -> Resource:
    base = {
        "service.name": settings.otel_service_name,
        "service.version": "0.1.0",
    }
    return Resource.create(base).merge(OTELResourceDetector().detect())


def setup_telemetry(app) -> None:
    """Install OTEL providers, exporters, and instrumentation. Idempotent."""
    global tracer_provider, meter_provider, logger_provider
    if tracer_provider is not None:
        return

    resource = _build_resource()

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(BatchSpanProcessor(PostgresSpanExporter()))

    metric_reader = PeriodicExportingMetricReader(
        PostgresMetricExporter(),
        export_interval_millis=settings.otel_metric_interval_seconds * 1000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(PostgresLogRecordExporter())
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    # Library noise (boto3, opentelemetry internals) stays off the tables.
    for noisy in ("boto3", "botocore", "opentelemetry"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
        logging.getLogger(noisy).addHandler(logging.NullHandler())

    trace.set_tracer_provider(tracer_provider)
    metrics.set_meter_provider(meter_provider)

    # FastAPI ASGI request spans.
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=tracer_provider,
        meter_provider=meter_provider,
        excluded_urls="health",
    )
    # psycopg3 SQL spans (pool opens after this in the app lifespan).
    PsycopgInstrumentor().instrument(tracer_provider=tracer_provider)
    # boto3/botocore S3 spans (manifest verification, uploads).
    BotocoreInstrumentor().instrument(tracer_provider=tracer_provider)


def shutdown_telemetry(timeout_millis: float = 5000) -> None:
    """Flush and shut down providers cleanly with the app lifespan."""
    global tracer_provider, meter_provider, logger_provider
    if logger_provider is not None:
        try:
            logger_provider.shutdown()
        except Exception:  # pragma: no cover - best-effort flush
            pass
    if meter_provider is not None:
        try:
            meter_provider.shutdown()
        except Exception:  # pragma: no cover - best-effort flush
            pass
    if tracer_provider is not None:
        try:
            tracer_provider.force_flush(timeout_millis)
            tracer_provider.shutdown()
        except Exception:  # pragma: no cover - best-effort flush
            pass
    tracer_provider = None
    meter_provider = None
    logger_provider = None


def run_retention() -> dict:
    """Delete spans/logs/metrics older than the retention window (30 days)."""
    from backend.db.connection import execute

    days = settings.otel_retention_days
    for table in ("otel_spans", "otel_logs", "otel_metrics"):
        execute(
            f"DELETE FROM {table} WHERE created_at < now() - (%s * interval '1 day')",
            (days,),
        )
    logger = logging.getLogger("observability.retention")
    logger.info("OTEL retention applied: deleted rows older than %s days", days)
    return {"retention_days": days}
