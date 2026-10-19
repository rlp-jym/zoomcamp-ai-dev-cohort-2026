"""Temporary debug routes (not part of main navigation)."""

from fastapi import APIRouter

from backend.config import settings
from backend.db import fetch_one
from backend.storage import list_scenario_keys, query_rows

router = APIRouter()


@router.get("/debug/db")
async def debug_db():
    persona_row = fetch_one("SELECT COUNT(*) AS c FROM personas")
    rule_row = fetch_one("SELECT COUNT(*) AS c FROM rules")
    return {"personas": persona_row["c"], "rules": rule_row["c"]}


@router.get("/debug/storage")
async def debug_storage():
    keys = list_scenario_keys("baseline_run")
    return keys


@router.get("/debug/query")
async def debug_query():
    bucket = settings.r2_bucket
    sql = f"SELECT * FROM read_parquet('s3://{bucket}/scenarios/baseline_run/invoices.parquet') LIMIT 5"
    return query_rows(sql)
