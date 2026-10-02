"""OpenTelemetry setup for order lookups. Console exporters only.

Intentionally leaves the estimated_delivery bug in place so the
500 on express end-of-month orders is observable via telemetry.
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
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

ORDER_LOOKUP_ROUTE = "/api/orders/{order_id}"
SERVICE_NAME = "order-tracker"

_tracer = None
_histogram = None
_counter = None
_order_logger = None


def _is_testing() -> bool:
    return os.getenv("PYTEST_CURRENT_TEST") is not None


def setup_telemetry(app):
    """Configure traces/metrics/logs with console export. Idempotent."""
    global _tracer, _histogram, _counter, _order_logger

    if getattr(app.state, "otel_initialized", False):
        return

    resource = Resource.create({"service.name": SERVICE_NAME})
    testing = _is_testing()

    # Traces -> console (docker compose logs app)
    try:
        tracer_provider = TracerProvider(resource=resource)
        if not testing:
            tracer_provider.add_span_processor(
                BatchSpanProcessor(ConsoleSpanExporter())
            )
        trace.set_tracer_provider(tracer_provider)
    except Exception:  # provider already set (e.g. repeated lifespan in tests)
        pass
    _tracer = trace.get_tracer(SERVICE_NAME)

    # Metrics -> console every 5s so `docker compose logs` shows them fast
    try:
        readers = (
            []
            if testing
            else [
                PeriodicExportingMetricReader(
                    ConsoleMetricExporter(), export_interval_millis=5000
                )
            ]
        )
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

    # Logs -> console via OTel LoggingHandler + ConsoleLogExporter
    try:
        logger_provider = LoggerProvider(resource=resource)
        if not testing:
            logger_provider.add_log_record_processor(
                BatchLogRecordProcessor(ConsoleLogExporter())
            )
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
