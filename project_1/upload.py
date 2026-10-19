import os
import boto3
from dotenv import load_dotenv
from pathlib import Path

load_dotenv()

s3 = boto3.client(
    's3',
    endpoint_url=os.getenv("R2_ENDPOINT_URL"),
    aws_access_key_id=os.getenv("R2_ACCESS_KEY_ID"),
    aws_secret_access_key=os.getenv("R2_SECRET_ACCESS_KEY"),
    region_name='us-east-1'
)

bucket = os.getenv("R2_BUCKET")
local_dir = Path("data/runs/demo_run")
s3_prefix = "scenarios/demo_run/"

if not local_dir.exists():
    raise SystemExit(f"Local directory not found: {local_dir}")

print(f"Uploading {local_dir} to s3://{bucket}/{s3_prefix}")

for file_path in sorted(local_dir.glob("*.parquet")):
    s3_key = f"{s3_prefix}{file_path.name}"
    print(f"Uploading {file_path.name}...")
    s3.upload_file(str(file_path), bucket, s3_key)

print("Upload complete!")