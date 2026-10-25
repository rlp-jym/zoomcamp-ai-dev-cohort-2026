"""Local Parquet scenario cache tests (no real S3 calls)."""

from pathlib import Path

import pytest

from backend.storage import scenario_cache


class FakeS3:
    def __init__(self, objects, payload=b"parquet"):
        self.objects = {obj["key"]: obj for obj in objects}
        self.payload = payload
        self.downloads = []

    def download_file(self, bucket, key, filename):
        self.downloads.append((bucket, key, filename))
        size = self.objects[key]["size"]
        Path(filename).write_bytes(self.payload[:size].ljust(size, b"x"))


def _objects(*names, prefix="scenarios/baseline_run/", size=5):
    return [
        {"key": f"{prefix}{name}", "name": name, "size": size}
        for name in names
    ]


@pytest.fixture
def cache_root(monkeypatch, tmp_path):
    root = tmp_path / "scenarios"
    monkeypatch.setattr(scenario_cache, "CACHE_ROOT", root)
    monkeypatch.setattr(scenario_cache, "MAX_CACHE_BYTES", 1024 * 1024)
    return root


def test_generated_scenarios_use_their_own_folders(monkeypatch, cache_root):
    objects_101 = _objects("ar_ledger.parquet", "invoices.parquet", prefix="scenarios/seed_101/")
    objects_102 = _objects("ar_ledger.parquet", "invoices.parquet", prefix="scenarios/seed_102/")
    fake = FakeS3(objects_101 + objects_102)
    listings = []

    def fake_list(prefix):
        listings.append(prefix)
        if prefix == "scenarios/seed_101/":
            return objects_101
        if prefix == "scenarios/seed_102/":
            return objects_102
        return []

    monkeypatch.setattr(scenario_cache, "get_s3_client", lambda: fake)
    monkeypatch.setattr(scenario_cache, "_list_parquet_objects", fake_list)

    first = scenario_cache.ensure_local_scenario(
        "generated_seed101_y5", "scenarios/seed_101/"
    )
    second = scenario_cache.ensure_local_scenario(
        "generated_seed102_y5", "scenarios/seed_102/"
    )

    assert first == cache_root / "generated_seed101_y5"
    assert second == cache_root / "generated_seed102_y5"
    assert first != second
    assert (first / "ar_ledger.parquet").is_file()
    assert (second / "invoices.parquet").is_file()
    assert listings == ["scenarios/seed_101/", "scenarios/seed_102/"]
    assert len(fake.downloads) == 4


def test_missing_file_is_redownloaded(monkeypatch, cache_root):
    objects = _objects("ar_ledger.parquet")
    fake = FakeS3(objects)
    monkeypatch.setattr(scenario_cache, "get_s3_client", lambda: fake)
    monkeypatch.setattr(scenario_cache, "_list_parquet_objects", lambda prefix: objects)

    target = scenario_cache.ensure_local_scenario(
        "baseline_run", "scenarios/baseline_run/"
    )
    (target / "ar_ledger.parquet").write_bytes(b"x")

    scenario_cache.ensure_local_scenario("baseline_run", "scenarios/baseline_run/")

    assert len(fake.downloads) == 2
    assert (target / "ar_ledger.parquet").stat().st_size == 5


def test_cleanup_evicts_oldest_non_target_folder(monkeypatch, cache_root):
    import os

    old = cache_root / "old_scenario"
    older = cache_root / "older_scenario"
    old.mkdir(parents=True)
    older.mkdir(parents=True)
    (old / "data.parquet").write_bytes(b"x" * 8)
    (older / "data.parquet").write_bytes(b"x" * 8)
    os.utime(old, (200, 200))
    os.utime(older, (100, 100))

    monkeypatch.setattr(scenario_cache, "MAX_CACHE_BYTES", 18)
    objects = _objects("invoices.parquet", size=4)
    fake = FakeS3(objects)
    monkeypatch.setattr(scenario_cache, "get_s3_client", lambda: fake)
    monkeypatch.setattr(scenario_cache, "_list_parquet_objects", lambda prefix: objects)

    target = scenario_cache.ensure_local_scenario(
        "baseline_run", "scenarios/baseline_run/"
    )

    assert target.is_dir()
    assert not older.exists()
    assert old.is_dir()


def test_localize_sql_uses_dataset_cache(monkeypatch, cache_root):
    from backend.config import settings

    sql = (
        "SELECT * FROM read_parquet("
        f"'s3://{settings.r2_bucket}/scenarios/seed_101/invoices.parquet')"
    )
    localized = scenario_cache.localize_sql(
        sql, "seed_101", "generated_seed101_y5"
    )

    expected = (cache_root / "generated_seed101_y5" / "invoices.parquet").as_posix()
    assert expected in localized
    assert "s3://" not in localized


def test_validation_rule_sql_reads_local_cache(monkeypatch, cache_root):
    from backend.services import validations

    sql = validations._render_sql(
        "SELECT * FROM read_parquet("
        "'s3://{bucket}/scenarios/{scenario}/invoice_lines.parquet')",
        "seed_101",
        "generated_seed101_y5",
    )

    expected = (
        cache_root / "generated_seed101_y5" / "invoice_lines.parquet"
    ).as_posix()
    assert expected in sql
    assert "s3://" not in sql


def test_dataset_picker_lists_pre_generated_seeds():
    from backend.config import TEMPLATES_DIR

    template = (TEMPLATES_DIR / "runs_list.html").read_text(encoding="utf-8")
    assert "Load Dataset" in template
    assert 'hx-post="/api/generate-dataset"' in template
    assert 'name="seed"' in template
    for seed in ("101", "102", "103"):
        assert f'value="{seed}"' in template


def test_resolve_data_scenario_uses_dataset_s3_prefix(monkeypatch):
    from backend.db import connection
    from backend.storage import s3_client

    def fake_fetch_one(sql, params=None):
        return {"s3_prefix": "scenarios/seed_101/"} if params == ("generated_seed101_y5",) else None

    monkeypatch.setattr(connection, "fetch_one", fake_fetch_one)

    assert s3_client.dataset_s3_prefix("generated_seed101_y5") == "scenarios/seed_101/"
    assert s3_client.resolve_data_scenario("generated_seed101_y5") == "seed_101"
    # Unknown datasets use their own folder; there is no baseline fallback.
    assert s3_client.dataset_s3_prefix("no_such_dataset") == "scenarios/no_such_dataset/"
