"""Dataset-generation endpoint year bounds."""

import pytest
from fastapi.testclient import TestClient

from backend.db import execute, fetch_one
from backend.main import app

client = TestClient(app)


@pytest.mark.parametrize("years", ["0", "6", "-1", "abc"])
def test_generate_rejects_years_outside_1_to_5(years):
    response = client.post(
        "/api/generate-scenario",
        data={"seed": "9900", "years_to_backtrack": years},
    )

    assert response.status_code == 400
    assert "between 1 and 5" in response.text or "whole number" in response.text


@pytest.mark.parametrize("years", [1, 5])
def test_generate_accepts_year_bounds_and_persists_window(years):
    seed = 9900 + years
    scenario_name = f"generated_seed{seed}_y{years}"
    try:
        response = client.post(
            "/api/generate-scenario",
            data={"seed": str(seed), "years_to_backtrack": str(years)},
        )
        assert response.status_code == 200

        row = fetch_one(
            "SELECT years_to_backtrack FROM datasets WHERE name = %s",
            (scenario_name,),
        )
        assert row["years_to_backtrack"] == years
    finally:
        execute("DELETE FROM datasets WHERE name = %s", (scenario_name,))

