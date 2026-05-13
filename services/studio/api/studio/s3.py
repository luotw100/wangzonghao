import os
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
DOWNLOAD_PRESIGN_EXPIRES = timedelta(hours=1)

_s3_client = boto3.client(
    "s3",
    endpoint_url=_endpoint,
    aws_access_key_id=_access_key,
    aws_secret_access_key=_secret_key,
    config=BotoConfig(signature_version="s3v4"),
    region_name="us-east-1",
)

_s3_public_client = boto3.client(
    "s3",
    endpoint_url=_public_url,
    aws_access_key_id=_access_key,
    aws_secret_access_key=_secret_key,
    config=BotoConfig(signature_version="s3v4"),
    region_name="us-east-1",
)


def s3_put(key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    _s3_client.put_object(Bucket=S3_BUCKET, Key=key, Body=data, ContentType=content_type)


def s3_get(key: str) -> bytes:
    resp = _s3_client.get_object(Bucket=S3_BUCKET, Key=key)
    return resp["Body"].read()


def s3_presigned_put_url(key: str, content_type: str, expires: timedelta = UPLOAD_PRESIGN_EXPIRES) -> str:
    return _s3_public_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": S3_BUCKET, "Key": key, "ContentType": content_type},
        ExpiresIn=int(expires.total_seconds()),
    )


def s3_presigned_get_url(
    key: str,
    filename: str | None = None,
    expires: timedelta = DOWNLOAD_PRESIGN_EXPIRES,
) -> str:
    params: dict = {"Bucket": S3_BUCKET, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
    return _s3_public_client.generate_presigned_url(
        "get_object",
        Params=params,
        ExpiresIn=int(expires.total_seconds()),
    )