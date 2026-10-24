"""Local Parquet cache for scenario data.

Validation used to read Parquet files straight from S3, which made DuckDB pay
an HTTP round-trip for every scan.  This module downloads a scenario's Parquet
files once and lets DuckDB read them from local disk.

Two guardrails keep the ephemeral container disk bounded:

* every dataset owns its own cache folder and S3 prefix;
* before a download, the oldest cache folders are evicted while the cache would
  exceed ``SCENARIO_CACHE_MAX_BYTES`` (800 MB by default).

The cache root defaults to ``/tmp/scenarios`` on POSIX.  On Windows it falls
back to the user's temp directory because ``/tmp`` is not writable there.  Set
``SCENARIO_CACHE_DIR`` to override either default.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from backend.config import settings
from backend.storage.s3_client import get_s3_client

logger = logging.getLogger(__name__)

MANIFEST_NAME = ".cache_manifest.json"
CACHE_VERSION = 1


def _default_cache_root() -> Path:
    configured = os.getenv("SCENARIO_CACHE_DIR")
    if configured:
        return Path(configured)
    if os.name == "nt":  # pragma: no cover - exercised on developer Windows hosts
        return Path(tempfile.gettempdir()) / "scenarios"
    return Path("/tmp/scenarios")


CACHE_ROOT = _default_cache_root()
MAX_CACHE_BYTES = int(os.getenv("SCENARIO_CACHE_MAX_BYTES", str(800 * 1024 * 1024)))

_cache_lock = threading.RLock()


def cache_scenario_name(scenario_name) -> str:
    """Return the cache folder name for a dataset."""
    return str(scenario_name)


def scenario_cache_dir(scenario_name) -> Path:
    return CACHE_ROOT / cache_scenario_name(scenario_name)


def scenario_parquet_glob(scenario_name) -> str:
    return (scenario_cache_dir(scenario_name) / "*.parquet").as_posix()


def scenario_s3_prefix(scenario_name) -> str:
    return f"scenarios/{scenario_name}/"


def _normalize_prefix(prefix) -> str:
    value = str(prefix or "").strip()
    if value.startswith("s3://"):
        rest = value[5:]
        slash = rest.find("/")
        value = rest[slash + 1 :] if slash >= 0 else ""
    value = value.lstrip("/")
    if value and not value.endswith("/"):
        value += "/"
    return value


def _candidate_prefixes(scenario_name, s3_prefix) -> list[str]:
    name = str(scenario_name)
    candidates: list[str] = []

    def add(prefix) -> None:
        normalized = _normalize_prefix(prefix)
        if normalized and normalized not in candidates:
            candidates.append(normalized)

    # Only the dataset's own prefix and its conventional folder. Generated
    # datasets are no longer aliases of the baseline Parquet bundle.
    add(s3_prefix)
    add(scenario_s3_prefix(name))
    return candidates


def _list_parquet_objects(prefix: str) -> list[dict]:
    """List Parquet objects under an S3 prefix, including their sizes."""
    client = get_s3_client()
    bucket = settings.r2_bucket
    objects: list[dict] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not key.lower().endswith(".parquet"):
                continue
            objects.append(
                {
                    "key": key,
                    "name": Path(key).name,
                    "size": int(obj.get("Size") or 0),
                }
            )
    return objects


def _file_matches(path: Path, size: int) -> bool:
    try:
        return path.is_file() and path.stat().st_size == size
    except OSError:
        return False


def _load_manifest(target: Path) -> dict | None:
    try:
        data = json.loads((target / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != CACHE_VERSION:
        return None
    return data


def _cache_is_valid(target: Path) -> bool:
    manifest = _load_manifest(target)
    if not manifest:
        return False
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        return False
    for name, meta in files.items():
        if not isinstance(meta, dict):
            return False
        if not _file_matches(target / name, int(meta.get("size") or 0)):
            return False
    return True


def _directory_size(path: Path) -> int:
    total = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                total += item.stat().st_size
    except OSError:
        pass
    return total


def cache_usage_bytes() -> int:
    """Total size of all cached scenario folders."""
    if not CACHE_ROOT.exists():
        return 0
    total = 0
    for folder in CACHE_ROOT.iterdir():
        if folder.is_dir():
            total += _directory_size(folder)
    return total


def _folder_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _remove_folder(path: Path) -> None:
    try:
        shutil.rmtree(path)
        logger.info("Evicted scenario cache folder %s", path)
    except OSError as exc:  # pragma: no cover - defensive
        logger.warning("Could not evict cache folder %s: %s", path, exc)


def _cache_folders() -> list[Path]:
    if not CACHE_ROOT.exists():
        return []
    return [p for p in CACHE_ROOT.iterdir() if p.is_dir()]


def _make_space(target: Path, objects: list[dict]) -> list[dict]:
    """Evict old folders and return the objects still needing download."""
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    total = cache_usage_bytes()

    # Guardrail 2a: if the cache is already over the limit, delete oldest
    # folders until it is back under the limit.
    if total > MAX_CACHE_BYTES:
        for folder in sorted(_cache_folders(), key=_folder_mtime):
            size = _directory_size(folder)
            _remove_folder(folder)
            total -= size
            if total <= MAX_CACHE_BYTES:
                break

    missing = [
        obj for obj in objects if not _file_matches(target / obj["name"], obj["size"])
    ]
    incoming = sum(int(obj["size"]) for obj in missing)

    # Guardrail 2b: reserve room for the files about to be downloaded by
    # evicting the oldest folders that are not the target itself.
    if total + incoming > MAX_CACHE_BYTES:
        for folder in sorted(_cache_folders(), key=_folder_mtime):
            if folder.resolve() == target.resolve():
                continue
            size = _directory_size(folder)
            _remove_folder(folder)
            total -= size
            if total + incoming <= MAX_CACHE_BYTES:
                break

    if total + incoming > MAX_CACHE_BYTES:
        raise RuntimeError(
            f"Scenario cache limit exceeded: {total + incoming} bytes would be "
            f"cached (limit {MAX_CACHE_BYTES}); refusing to fill the disk"
        )
    return missing


def _write_manifest(target: Path, source: str, objects: list[dict]) -> None:
    payload = {
        "version": CACHE_VERSION,
        "source": source,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "files": {
            obj["name"]: {"key": obj["key"], "size": int(obj["size"])}
            for obj in objects
        },
    }
    tmp = target / (MANIFEST_NAME + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(target / MANIFEST_NAME)


def _resolve_objects(scenario_name, s3_prefix) -> tuple[str, list[dict]]:
    candidates = _candidate_prefixes(scenario_name, s3_prefix)
    for prefix in candidates:
        try:
            objects = _list_parquet_objects(prefix)
        except Exception as exc:
            logger.warning("Could not list scenario cache source %s: %s", prefix, exc)
            continue
        if objects:
            return prefix, objects
    raise FileNotFoundError(
        f"No Parquet files found for scenario {scenario_name!r} "
        f"(tried: {', '.join(candidates) or 'no prefixes'})"
    )


def ensure_local_scenario(scenario_name, s3_prefix) -> Path:
    """Download a scenario's Parquet files once and return its cache folder.

    Subsequent calls are cheap: the manifest plus file sizes are checked
    locally, so no S3 listing or transfer happens.
    """
    target = scenario_cache_dir(scenario_name)
    with _cache_lock:
        if _cache_is_valid(target):
            return target

        source, objects = _resolve_objects(scenario_name, s3_prefix)
        missing = _make_space(target, objects)
        target.mkdir(parents=True, exist_ok=True)

        if missing:
            client = get_s3_client()
            bucket = settings.r2_bucket
            logger.info(
                "Caching %s parquet file(s) from %s into %s",
                len(missing),
                source,
                target,
            )
            for obj in missing:
                destination = target / obj["name"]
                temp = destination.with_name(destination.name + ".part")
                try:
                    client.download_file(bucket, obj["key"], str(temp))
                    temp.replace(destination)
                finally:
                    if temp.exists():
                        temp.unlink(missing_ok=True)

        # Drop local files that are no longer part of the source snapshot.
        expected = {obj["name"] for obj in objects}
        for stale in target.glob("*.parquet"):
            if stale.name not in expected:
                stale.unlink(missing_ok=True)

        _write_manifest(target, source, objects)
        return target


def localize_sql(sql: str, source_scenario: str, cache_scenario=None) -> str:
    """Rewrite an S3 Parquet URI to the local cache folder.

    ``source_scenario`` is the concrete S3 folder name (already resolved from
    the dataset's ``s3_prefix`` by pipeline callers).
    """
    cache = scenario_cache_dir(cache_scenario or source_scenario).as_posix().rstrip("/")
    source = str(source_scenario).strip("/")
    s3_base = f"s3://{settings.r2_bucket}/scenarios/{source}/"
    return sql.replace(s3_base, cache + "/")
