import os
import uuid
from datetime import timedelta

import boto3
from botocore.config import Config as BotoConfig

_endpoint = os.environ.get("S3_ENDPOINT")
_access_key = os.environ.get("S3_ACCESS_KEY")
_secret_key = os.environ.get("S3_SECRET_KEY")
_bucket = os.environ.get("S3_BUCKET")
_public_url = os.environ.get("S3_PUBLIC_URL")

if not all([_endpoint, _access_key, _secret_key, _bucket]):
    raise RuntimeError("S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, and S3_BUCKET are required")

if not _public_url:
    raise RuntimeError("S3_PUBLIC_URL is required (the public-facing URL for presigned URLs)")

S3_BUCKET = _bucket

UPLOAD_PRESIGN_EXPIRES = timedelta(minutes=15)
DOWNLOAD_PRESIGN_EXPIRES = timedelta(minutes=5)

_boto_config = BotoConfig(signature_version="s3v4")

_s3_client = boto3.client(
    "s3",
    endpoint_url=_endpoint,
    aws_access_key_id=_access_key,
    aws_secret_access_key=_secret_key,
    config=_boto_config,
    region_name="us-east-1",
)

_s3_public_client = boto3.client(
    "s3",
    endpoint_url=_public_url,
    aws_access_key_id=_access_key,
    aws_secret_access_key=_secret_key,
    config=_boto_config,
    region_name="us-east-1",
)


def s3_generate_storage_key(account_id: str) -> str:
    return f"media/{account_id}/{uuid.uuid4().hex}"


def s3_presigned_post(
    key: str,
    content_type: str,
    max_bytes: int,
    expires: timedelta = UPLOAD_PRESIGN_EXPIRES,
) -> dict:
    """Presigned POST that binds Content-Type and caps object size server-side."""
    return _s3_public_client.generate_presigned_post(
        Bucket=S3_BUCKET,
        Key=key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, max_bytes],
        ],
        ExpiresIn=int(expires.total_seconds()),
    )


def s3_presigned_get_url(
    key: str,
    force_attachment: bool = False,
    expires: timedelta = DOWNLOAD_PRESIGN_EXPIRES,
) -> str:
    params: dict = {"Bucket": S3_BUCKET, "Key": key}
    if force_attachment:
        params["ResponseContentDisposition"] = "attachment"
    return _s3_public_client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=int(expires.total_seconds()),
    )