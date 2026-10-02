import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from opentelemetry.trace import Status, StatusCode
from pydantic import BaseModel, Field

from app.telemetry import (
    ORDER_LOOKUP_ROUTE,
    get_order_logger,
    get_request_instruments,
    get_tracer,
    setup_telemetry,
)


DB_PATH = Path(os.getenv("ORDER_DB_PATH", "data/orders.db"))
STATUSES = {"received", "preparing", "shipped", "delivered"}


def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    return db


def init_db():
    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                customer TEXT NOT NULL,
                item TEXT NOT NULL,
                priority TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )
        if db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 0:
            now = datetime.now(timezone.utc)
            previous_month_end = now.replace(day=1) - timedelta(days=1)
            for order in (
                ("standard-1001", "Avery", "Notebook", "standard", "received", now),
                ("express-1002", "Sam", "Headphones", "express", "preparing", previous_month_end),
                ("standard-1003", "Riley", "Water bottle", "standard", "shipped", now),
            ):
                db.execute(
                    "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
                    (*order[:5], order[5].isoformat()),
                )


def as_dict(row):
    return dict(row) if row else None


def order_detail(row):
    order = as_dict(row)
    if order["priority"] == "express":
        placed_at = datetime.fromisoformat(order["created_at"])
        estimated_at = placed_at + timedelta(days=2)
        order["estimated_delivery"] = estimated_at.date().isoformat()
    return order


class NewOrder(BaseModel):
    customer: str = Field(min_length=1, max_length=80)
    item: str = Field(min_length=1, max_length=120)
    priority: str = "standard"


class StatusUpdate(BaseModel):
    status: str


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_telemetry(_app)
    init_db()
    yield


app = FastAPI(title="Order Tracker", lifespan=lifespan)


@app.middleware("http")
async def order_lookup_metrics(request: Request, call_next):
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        path = request.url.path
        is_lookup = (
            request.method == "GET"
            and path.startswith("/api/orders/")
            and len(path) > len("/api/orders/")
        )
        if is_lookup:
            duration_ms = (time.perf_counter() - start) * 1000
            attrs = {
                "http.route": ORDER_LOOKUP_ROUTE,
                "http.response.status_code": status_code,
                "http.method": "GET",
            }
            histogram, counter = get_request_instruments()
            histogram.record(duration_ms, attrs)
            counter.add(1, attrs)


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent.parent / "static" / "index.html")


@app.get("/healthz")
def health():
    with connect() as db:
        db.execute("SELECT 1")
    return {"status": "ok"}


@app.get("/api/orders")
def list_orders():
    with connect() as db:
        rows = db.execute("SELECT * FROM orders ORDER BY created_at DESC").fetchall()
    return [as_dict(row) for row in rows]


@app.get("/api/orders/{order_id}")
def get_order(order_id: str):
    tracer = get_tracer()
    logger = get_order_logger()
    with tracer.start_as_current_span(
        "order.lookup",
        attributes={"order.id": order_id, "http.route": ORDER_LOOKUP_ROUTE},
    ) as span:
        with connect() as db:
            row = db.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            span.set_attribute("order.found", False)
            span.set_attribute("http.response.status_code", 404)
            span.set_status(Status(StatusCode.ERROR, "Order not found"))
            logger.info(
                "order lookup not_found id=%s route=%s status_code=%s",
                order_id,
                ORDER_LOOKUP_ROUTE,
                404,
            )
            raise HTTPException(404, "Order not found")
        try:
            result = order_detail(row)
        except Exception as exc:
            span.set_attribute("order.found", True)
            span.set_attribute("http.response.status_code", 500)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.exception(
                "order lookup error id=%s route=%s status_code=%s",
                order_id,
                ORDER_LOOKUP_ROUTE,
                500,
            )
            raise
        span.set_attribute("order.found", True)
        span.set_attribute("http.response.status_code", 200)
        span.set_attribute("order.priority", result.get("priority", ""))
        span.set_attribute("order.status", result.get("status", ""))
        logger.info(
            "order lookup found id=%s route=%s status_code=%s",
            order_id,
            ORDER_LOOKUP_ROUTE,
            200,
        )
        return result


@app.post("/api/orders", status_code=201)
def create_order(order: NewOrder):
    if order.priority not in {"standard", "express"}:
        raise HTTPException(422, "Priority must be standard or express")
    order_id = str(uuid4())
    with connect() as db:
        db.execute(
            "INSERT INTO orders VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, order.customer, order.item, order.priority, "received",
             datetime.now(timezone.utc).isoformat()),
        )
    return get_order(order_id)


@app.patch("/api/orders/{order_id}")
def update_status(order_id: str, update: StatusUpdate):
    if update.status not in STATUSES:
        raise HTTPException(422, "Invalid status")
    with connect() as db:
        cursor = db.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (update.status, order_id),
        )
    if cursor.rowcount == 0:
        raise HTTPException(404, "Order not found")
    return get_order(order_id)
