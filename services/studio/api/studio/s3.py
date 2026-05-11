import os

import boto3
from botocore.config import Config as BotoConfig

_endpoint = os.environ.get("S3_ENDPOINT")
_access_key = os.environ.get("S3_ACCESS_KEY")
_secret_key = os.environ.get("S3_SECRET_KEY")
_bucket = os.environ.get("S3_BUCKET")

if not all([_endpoint, _access_key, _secret_key, _bucket]):
    raise RuntimeError("S3_ENDPOINT, S3_ACCESS_KEY, S3_SECRET_KEY, and S3_BUCKET are required")

S3_BUCKET = _bucket

_s3_client = boto3.client(
    "s3",
    endpoint_url=_endpoint,
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


def s3_key_exists(key: str) -> bool:
    try:
        _s3_client.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except _s3_client.exceptions.ClientError:
        return False