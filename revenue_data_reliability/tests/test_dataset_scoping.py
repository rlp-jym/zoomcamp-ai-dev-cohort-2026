"""Dataset scoping (selector) tests."""
import json
import uuid

from fastapi.testclient import TestClient

from backend.db.connection import execute, fetch_one, init_pool
from backend.main import app

client = TestClient(app)


def _cleanup(scenarios):
    for name in scenarios:
        execute("DELETE FROM dashboard_cache WHERE dataset_name = %s", (name,))
        execute("DELETE FROM publications WHERE run_id IN (SELECT run_id FROM runs WHERE dataset_name = %s)", (name,))
        execute("DELETE FROM runs WHERE dataset_name = %s", (name,))
        execute("DELETE FROM datasets WHERE name = %s", (name,))


def test_empty_state_for_unvalidated_dataset():
    init_pool()
    name = f"scope_empty_{uuid.uuid4().hex[:8]}"
    try:
        execute(
            "INSERT INTO datasets (name, status, seed, table_count) VALUES (%s, 'ready', 9, 16)",
            (name,),
        )
        c = TestClient(app)
        for path in ["/", "/exceptions", "/runs"]:
            r = c.get(f"{path}?scenario={name}")
            assert r.status_code == 200, (path, r.status_code)
            assert "This dataset has not been validated yet. Run validation to populate." in r.text
    finally:
        _cleanup([name])


def test_cookie_persistence_across_pages():
    init_pool()
    name = f"scope_cookie_{uuid.uuid4().hex[:8]}"
    try:
        execute(
            "INSERT INTO datasets (name, status, seed, table_count) VALUES (%s, 'ready', 9, 16)",
            (name,),
        )
        c = TestClient(app)
        r = c.get(f"/?scenario={name}")
        assert r.status_code == 200
        r2 = c.get("/exceptions")
        assert r2.status_code == 200
        assert f'<option value="{name}" selected' in r2.text
    finally:
        _cleanup([name])


def test_dashboard_differs_between_datasets():
    init_pool()
    a = f"scope_a_{uuid.uuid4().hex[:8]}"
    b = f"scope_b_{uuid.uuid4().hex[:8]}"
    try:
        for name in (a, b):
            execute(
                "INSERT INTO datasets (name, status, seed, table_count) VALUES (%s, 'ready', 9, 16)",
                (name,),
            )
            run_row = fetch_one(
                """
                INSERT INTO runs (dataset_name, status, triggered_by, trace_id,
                                  started_at, finished_at, duration,
                                  validations_total, validations_failed, exceptions_created,
                                  published, published_at)
                VALUES (%s, 'completed', 'test', %s, now(), now(), '0s', 0, 0, 0, TRUE, now())
                RETURNING run_id
                """,
                (name, f"trace-{name}"),
            )
            run_id = run_row["run_id"]
            execute(
                "INSERT INTO publications (run_id, published_by, pointer) VALUES (%s, 'manager', %s)",
                (run_id, f"scenarios/{name}"),
            )
            execute(
                """
                INSERT INTO dashboard_cache (cache_key, dataset_name, data, refreshed_at)
                VALUES (%s, %s, %s::jsonb, now())
                ON CONFLICT (dataset_name) DO UPDATE SET data = EXCLUDED.data, refreshed_at = now()
                """,
                (
                    f"dashboard:{name}",
                    name,
                    json.dumps(
                        {
                            "available": True,
                            "scenario": name,
                            "published_run": run_id,
                            "charts": {"segment_mix": []},
                            "open_exceptions": 0,
                        }
                    ),
                ),
            )

        c = TestClient(app)
        ra = c.get(f"/?scenario={a}")
        rb = c.get(f"/?scenario={b}")
        assert ra.status_code == 200 and rb.status_code == 200
        assert f"run id {fetch_one('SELECT run_id FROM runs WHERE dataset_name = %s', (a,))['run_id']}" in ra.text
        assert f"run id {fetch_one('SELECT run_id FROM runs WHERE dataset_name = %s', (b,))['run_id']}" in rb.text
        assert ra.text != rb.text
    finally:
        _cleanup([a, b])
