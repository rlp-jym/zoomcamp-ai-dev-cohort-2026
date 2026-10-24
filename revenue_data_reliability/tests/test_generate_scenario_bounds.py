"""Dataset-generation endpoint: pre-generated seed registry."""

import pytest
from fastapi.testclient import TestClient

from backend.db import execute, fetch_one
from backend.main import app

client = TestClient(app)


@pytest.mark.parametrize("seed", ["999", "9900", "abc"])
def test_generate_rejects_unknown_seeds(seed):
    response = client.post(
        "/api/generate-scenario",
        data={"seed": seed, "years_to_backtrack": "5"},
    )

    assert response.status_code == 400
    assert "Available seeds: 101, 102, 103" in response.text


@pytest.mark.parametrize(
    ("seed", "expected_name", "expected_prefix"),
    [
        (101, "generated_seed101_y5", "scenarios/seed_101/"),
        (103, "generated_seed103_y5", "scenarios/seed_103/"),
    ],
)
def test_generate_registers_pre_generated_folder(seed, expected_name, expected_prefix):
    try:
        response = client.post(
            "/api/generate-scenario",
            data={"seed": str(seed), "years_to_backtrack": "2"},
        )
        assert response.status_code == 200

        row = fetch_one(
            "SELECT name, seed, s3_prefix, years_to_backtrack FROM datasets WHERE name = %s",
            (expected_name,),
        )
        assert row["seed"] == seed
        assert row["s3_prefix"] == expected_prefix
        assert row["years_to_backtrack"] == 5
    finally:
        execute("DELETE FROM datasets WHERE name = %s", (expected_name,))
