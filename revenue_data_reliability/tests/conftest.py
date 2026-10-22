"""Test setup: ensure the Postgres schema exists before tests run."""

from io import BytesIO
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
def s3_fixture(tmp_path):
    """A local-filesystem stand-in for an S3 bucket."""
    root = tmp_path / "bucket"
    root.mkdir()
    (root / "scenarios").mkdir()

    class LocalS3:
        def __init__(self, root):
            self.root = root

        def put_object(self, Bucket=None, Key=None, Body=None):
            path = self.root / Key
            path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(Body, "read"):
                data = Body.read()
            else:
                data = Body
            path.write_bytes(data if isinstance(data, (bytes, bytearray)) else str(data).encode())
            return {}

        def get_object(self, Bucket=None, Key=None):
            path = self.root / Key
            return {"Body": BytesIO(path.read_bytes())}

    return LocalS3(root)


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