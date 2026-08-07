"""S3 FileStorage adapter for production user uploads.

Uses IAM role credentials via the default boto3 session. Bucket name and region
come from runtime configuration — never hard-coded account IDs or keys.
"""

from __future__ import annotations

import logging
from typing import Any

from .ports import StoredObject

logger = logging.getLogger(__name__)

_MISSING_CODES = frozenset({"NoSuchKey", "NotFound", "404", "NoSuchBucket"})


def is_missing_object_error(error: BaseException) -> bool:
    """Return True only when *error* indicates a missing S3 object."""
    error_name = type(error).__name__
    if error_name in {"NoSuchKey", "NotFound"}:
        return True
    response = getattr(error, "response", None)
    if isinstance(response, dict):
        err = response.get("Error") or {}
        code = str(err.get("Code") or "")
        if code in _MISSING_CODES:
            return True
        meta = response.get("ResponseMetadata") or {}
        status = meta.get("HTTPStatusCode")
        if status == 404:
            return True
    text = str(error)
    if "NoSuchKey" in text or "Not Found" == text:
        # Narrow string match for simple test doubles named NoSuchKey.
        if error_name == "NoSuchKey" or "NoSuchKey" in text.split():
            return True
        if error_name == "ClientError" and "NoSuchKey" in text:
            return True
    return False


class S3FileStorage:
    """Persist upload bytes in an S3 bucket using IAM-based credentials."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        client: Any | None = None,
    ):
        """Create S3 storage for *bucket* in *region*.

        Args:
            bucket: Runtime-configured uploads bucket name.
            region: AWS region (production: ``us-west-2``).
            client: Optional injected boto3 S3 client (tests inject fakes).
        """
        if not bucket.strip():
            raise ValueError("USER_UPLOADS_BUCKET is required for S3 file storage")
        if not region.strip():
            raise ValueError("AWS_REGION is required for S3 file storage")
        self.bucket = bucket.strip()
        self.region = region.strip()
        self._client = client

    def _s3(self) -> Any:
        """Return the boto3 S3 client, importing lazily so local tests stay free of AWS."""
        if self._client is not None:
            return self._client
        try:
            import boto3
        except ImportError as error:  # pragma: no cover - production dependency
            raise RuntimeError(
                "boto3 is required when FILE_STORAGE_PROVIDER=s3"
            ) from error
        self._client = boto3.client("s3", region_name=self.region)
        return self._client

    def put_bytes(
        self,
        *,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObject:
        """Upload *data* to S3 under *key*."""
        self._s3().put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return StoredObject(
            key=key,
            original_filename=key.rsplit("/", 1)[-1],
            content_type=content_type,
            size=len(data),
        )

    def get_bytes(self, key: str) -> bytes:
        """Download object bytes from S3.

        Raises:
            FileNotFoundError: only for missing-object conditions.
            Exception: AccessDenied, throttling, credentials, KMS, and other
                AWS failures propagate unchanged.
        """
        try:
            response = self._s3().get_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if is_missing_object_error(error):
                raise FileNotFoundError(key) from error
            raise
        body = response["Body"].read()
        return body if isinstance(body, (bytes, bytearray)) else bytes(body)

    def delete(self, key: str) -> None:
        """Delete one S3 object; missing keys are ignored."""
        try:
            self._s3().delete_object(Bucket=self.bucket, Key=key)
        except Exception as error:
            if is_missing_object_error(error):
                return
            raise

    def exists(self, key: str) -> bool:
        """Return whether *key* exists.

        Returns False only for a confirmed missing object. AccessDenied and
        other AWS failures propagate.
        """
        try:
            self._s3().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as error:
            if is_missing_object_error(error):
                return False
            raise

    def delete_prefix(self, prefix: str) -> int:
        """Delete every object under *prefix* using list+delete batches."""
        client = self._s3()
        paginator = client.get_paginator("list_objects_v2")
        removed = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            contents = page.get("Contents") or []
            if not contents:
                continue
            objects = [{"Key": item["Key"]} for item in contents if item.get("Key")]
            if not objects:
                continue
            client.delete_objects(
                Bucket=self.bucket,
                Delete={"Objects": objects, "Quiet": True},
            )
            removed += len(objects)
        return removed
