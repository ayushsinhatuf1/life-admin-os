"""Private object storage. No document is ever served from a public URL."""
from __future__ import annotations

import hashlib
import uuid

import boto3
from botocore.config import Config

from app.config import settings

_client = boto3.client(
    "s3",
    endpoint_url=settings.s3_endpoint_url,
    region_name=settings.s3_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
    config=Config(signature_version="s3v4"),
)


def build_key(family_id: uuid.UUID, filename: str) -> str:
    return f"families/{family_id}/documents/{uuid.uuid4()}/{filename}"


def page_key(storage_key: str, page_number: int) -> str:
    """Build the storage key for a rasterised page image alongside the original."""
    prefix = storage_key.rsplit("/", 1)[0]
    return f"{prefix}/pages/{page_number}.webp"


def put(key: str, data: bytes, content_type: str) -> str:
    _client.put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )
    return hashlib.sha256(data).hexdigest()


def get(key: str) -> bytes:
    return _client.get_object(Bucket=settings.s3_bucket, Key=key)["Body"].read()


def signed_url(key: str, seconds: int = 300) -> str:
    """Short-lived read URL, handed out only after an authorization check."""
    return _client.generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.s3_bucket, "Key": key},
        ExpiresIn=seconds,
    )


def delete(key: str) -> None:
    _client.delete_object(Bucket=settings.s3_bucket, Key=key)
