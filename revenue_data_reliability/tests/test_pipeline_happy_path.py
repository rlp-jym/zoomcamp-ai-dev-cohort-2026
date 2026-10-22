"""Pipeline happy path (requires R2 fixture; skipped in local CI)."""

import pytest


@pytest.mark.skip(reason="requires R2/Parquet fixture not available in CI")
def test_pipeline_happy_path():
    pass