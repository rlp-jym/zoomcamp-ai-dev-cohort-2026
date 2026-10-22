"""Test setup: ensure the Postgres schema exists before tests run."""

from unittest.mock import MagicMock

import pytest

from backend.db import apply_schema, init_pool, seed
from backend.db.fixture import ensure_baseline_fixture


def pytest_sessionstart(session):
    init_pool()
    apply_schema()
    seed()
    ensure_baseline_fixture()


@pytest.fixture
def s3_fixture():
    """A minimal stand-in for an S3 client."""
    client = MagicMock()
    client.put_object.return_value = {}
    client.get_object.return_value = {"Body": MagicMock(read=lambda: b"")}
    return client


@pytest.fixture
def groq_fixture():
    """A fake Groq client returning a canned response."""

    class FakeGroq:
        def post(self, *a, **k):
            class Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"choices": [{"message": {"content": "canned response"}}]}

            return Resp()

    return FakeGroq()