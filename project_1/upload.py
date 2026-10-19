import argparse
import sys
from pathlib import Path

from backend.storage.s3_client import get_s3_client
from backend.config import settings


def main():
    parser = argparse.ArgumentParser(description="Upload scenario parquet files to R2")
    parser.add_argument("--scenario", default="demo_run", help="Scenario name (e.g. baseline_run)")
    parser.add_argument("--dir", default=None, help="Local directory containing *.parquet (e.g. data/runs/baseline_run)")
    parser.add_argument("--prefix", default=None, help="S3 key prefix (default scenarios/<scenario>/)")
    args = parser.parse_args()

    s3 = get_s3_client()
    bucket = settings.r2_bucket

    local_dir = Path(args.dir) if args.dir else Path("data/runs") / args.scenario
    s3_prefix = args.prefix if args.prefix else f"scenarios/{args.scenario}/"

    if not bucket:
        sys.exit("R2_BUCKET not set")
    if not local_dir.exists():
        sys.exit(f"Local directory not found: {local_dir}")

    print(f"Uploading {local_dir} to s3://{bucket}/{s3_prefix}")
    for file_path in sorted(local_dir.glob("*.parquet")):
        s3_key = f"{s3_prefix}{file_path.name}"
        with open(file_path, "rb") as f:
            body = f.read()
        print(f"Uploading {file_path.name} as {s3_key}...")
        s3.put_object(Bucket=bucket, Key=s3_key, Body=body)

    print("Upload complete!")


if __name__ == "__main__":
    main()