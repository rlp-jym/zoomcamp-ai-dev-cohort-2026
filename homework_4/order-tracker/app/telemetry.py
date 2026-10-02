"""OpenTelemetry setup for order lookups. Console + OTLP dual export.

The estimated_delivery month-end bug in app/main.py was owned and fixed by the
incident-responder agent (see AGENTS.md sections 3 and 8): humans and
builder-agents do not hand-fix production incidents. Its 5xx on express
end-of-month orders is what the 5xx alert fired on.
"""

import logging
import os

from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    PeriodicExportingMetricReader,
)
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

ORDER_LOOKUP_ROUTE = "/api/orders/{order_id}"
SERVICE_NAME = "order-tracker"


def _otlp_endpoint() -> str:
    return os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318").rstrip("/")

_tracer = None
_histogram = None
_counter = None
_order_logger = None


def _is_testing() -> bool:
    return os.getenv("PYTEST_CURRENT_TEST") is not None


def setup_telemetry(app):
    """Configure traces/metrics/logs with console + OTLP export. Idempotent."""
    global _tracer, _histogram, _counter, _order_logger

    if getattr(app.state, "otel_initialized", False):
        return

    resource = Resource.create({"service.name": SERVICE_NAME})
    testing = _is_testing()
    otlp_endpoint = _otlp_endpoint()

    # Traces -> console (docker compose logs app) + OTLP collector
    try:
        tracer_provider = TracerProvider(resource=resource)
        if not testing:
            tracer_provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )
            try:
                tracer_provider.add_span_processor(
                    BatchSpanProcessor(
                        OTLPSpanExporter(endpoint=f"{otlp_endpoint}/v1/traces")
                    )
                )
            except Exception:
                pass
        trace.set_tracer_provider(tracer_provider)
    except Exception:  # provider already set (e.g. repeated lifespan in tests)
        pass
    _tracer = trace.get_tracer(SERVICE_NAME)

    # Metrics -> console every 5s so `docker compose logs` shows them fast,
    # plus OTLP to collector every 15s for Prometheus.
    try:
        readers = []
        if not testing:
            readers = [
                PeriodicExportingMetricReader(
                    ConsoleMetricExporter(), export_interval_millis=5000
                ),
                PeriodicExportingMetricReader(
                    OTLPMetricExporter(endpoint=f"{otlp_endpoint}/v1/metrics"),
                    export_interval_millis=15000,
                ),
            ]
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=readers))
    except Exception:
        pass
    meter = metrics.get_meter(SERVICE_NAME)
    _histogram = meter.create_histogram(
        "http.server.request.duration",
        unit="ms",
        description="Order lookup request duration",
    )
    _counter = meter.create_counter(
        "http.server.request.count",
        unit="1",
        description="Order lookup request count",
    )

    # Logs -> console via OTel LoggingHandler + ConsoleLogExporter,
    # plus OTLP to collector (Loki via collector).
    try:
        logger_provider = LoggerProvider(resource=resource)
        if not testing:
            logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(ConsoleLogExporter())
            )
            try:
                logger_provider.add_log_record_processor(
                    BatchLogRecordProcessor(
                        OTLPLogExporter(endpoint=f"{otlp_endpoint}/v1/logs")
                    )
                )
            except Exception:
                pass
        set_logger_provider(logger_provider)
    except Exception:
        pass
    _order_logger = logging.getLogger("order.lookup")
    _order_logger.setLevel(logging.INFO)
    if not any(isinstance(h, LoggingHandler) for h in _order_logger.handlers):
        _order_logger.addHandler(LoggingHandler(level=logging.INFO))

    # Auto server spans for FastAPI (gives http.route semantics too)
    try:
        FastAPIInstrumentor().instrument_app(app)
    except Exception:
        pass

    app.state.otel_initialized = True


def get_tracer():
    return _tracer or trace.get_tracer(SERVICE_NAME)


def get_request_instruments():
    """Returns (histogram, counter), creating them lazily for tests."""
    global _histogram, _counter
    if _histogram is None or _counter is None:
        meter = metrics.get_meter(SERVICE_NAME)
        _histogram = meter.create_histogram(
            "http.server.request.duration",
            unit="ms",
            description="Order lookup request duration",
        )
        _counter = meter.create_counter(
            "http.server.request.count",
            unit="1",
            description="Order lookup request count",
        )
    return _histogram, _counter


def get_order_logger():
    global _order_logger
    if _order_logger is None:
        _order_logger = logging.getLogger("order.lookup")
    return _order_logger
