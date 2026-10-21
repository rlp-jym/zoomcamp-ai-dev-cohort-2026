"""S3-compatible (R2/Filebase) client."""

import hashlib
import json
from urllib.parse import urlparse

import boto3

from backend.config import settings


def _normalized_host() -> str:
    host = urlparse(settings.r2_endpoint_url).hostname or settings.r2_endpoint_url
    # Filebase bucket-specific endpoints look like <bucket>.s3.filebase.io;
    # strip the leading bucket label so the client uses the root endpoint.
    if host.startswith(settings.r2_bucket + "."):
        host = host[len(settings.r2_bucket) + 1 :]
    return host


def get_s3_client():
    host = _normalized_host()
    scheme = urlparse(settings.r2_endpoint_url).scheme or "https"
    endpoint_url = f"{scheme}://{host}"
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=settings.r2_access_key_id,
        aws_secret_access_key=settings.r2_secret_access_key,
        region_name="us-east-1",
    )


def list_keys(prefix: str = "") -> list[str]:
    client = get_s3_client()
    bucket = settings.r2_bucket
    keys: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return keys


def list_scenario_keys(scenario: str = "baseline_run") -> list[str]:
    prefix = f"scenarios/{scenario}/"
    return list_keys(prefix=prefix)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_manifest(scenario: str, manifest: dict | None = None) -> dict:
    """Verify SHA-256 hashes in a manifest against objects in S3.

    If no manifest is supplied, attempts to load ``scenarios/<scenario>/manifest.json``.
    Returns a dict mapping object key -> bool.
    """
    client = get_s3_client()
    bucket = settings.r2_bucket
    if manifest is None:
        try:
            raw = client.get_object(Bucket=bucket, Key=f"scenarios/{scenario}/manifest.json")["Body"].read()
            manifest = json.loads(raw)
        except Exception:
            manifest = {}

    results: dict[str, bool] = {}
    tables = manifest.get("tables", {}) if isinstance(manifest, dict) else {}
    for name, info in tables.items():
        key = f"scenarios/{scenario}/{name}.parquet"
        expected = info.get("sha256") if isinstance(info, dict) else None
        if not expected:
            continue
        try:
            data = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            results[key] = (sha256_bytes(data) == expected)
        except Exception:
            results[key] = False
    return results
