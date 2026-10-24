"""Test setup: ensure a dedicated Postgres test database is configured."""

import os
from io import BytesIO

import pytest

_test_database_url = os.getenv("TEST_DATABASE_URL")
if not _test_database_url:
    raise RuntimeError(
        "Set TEST_DATABASE_URL to run tests. Tests must not use the live DATABASE_URL."
    )
os.environ["DATABASE_URL"] = _test_database_url

from backend.db import apply_schema, init_pool, seed  # noqa: E402
from backend.db.fixture import ensure_baseline_fixture  # noqa: E402


def pytest_sessionstart(session):
    # Under pytest-xdist the master performs the one-time schema/seed setup;
    # workers share the same database and must not race each other.
    if getattr(session.config, "workerinput", None) is not None:
        return
    init_pool()
    apply_schema()
    seed()
    ensure_baseline_fixture(force=True)


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
