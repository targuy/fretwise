"""S3-compatible object-storage backend (AWS S3, MinIO, R2, B2, Wasabi …).

A single backend covers every S3-compatible provider by varying
``endpoint_url``. Credentials come from :mod:`fretwise.storage.credentials`
(env / secrets file), never from the app config.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fretwise.storage.base import (
    SUPPORTED_SCORE_EXTS,
    StorageBackendUnavailable,
    StorageNotFoundError,
    StorageObject,
)
from fretwise.storage.credentials import load_s3_credentials
from fretwise.storage.remote import RemoteStorageBackend


def _build_client(endpoint_url: str | None, region: str | None) -> Any:
    """Create a boto3 S3 client, raising a clear error if boto3 is missing."""
    try:
        import boto3  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise StorageBackendUnavailable(
            "S3 storage requires boto3. Install it with: pip install 'fretwise[cloud]'"
        ) from exc
    kwargs: dict[str, Any] = dict(load_s3_credentials())
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs)


class S3StorageBackend(RemoteStorageBackend):
    """Store score files as objects under ``s3://<bucket>/<prefix>``."""

    name = "s3"

    def __init__(
        self,
        *,
        bucket: str,
        cache_dir: Path,
        prefix: str = "",
        endpoint_url: str | None = None,
        region: str | None = None,
        client: Any | None = None,
    ) -> None:
        """Create the backend.

        Args:
            bucket: Target S3 bucket.
            cache_dir: Local cache directory for downloaded objects.
            prefix: Optional key prefix (treated as a folder).
            endpoint_url: Custom endpoint for non-AWS providers (MinIO/R2/B2…).
            region: Optional region name.
            client: Pre-built boto3 client (mainly for tests). When omitted a
                client is constructed lazily from env/secrets credentials.
        """
        super().__init__(cache_dir)
        if not bucket:
            raise StorageBackendUnavailable("S3 storage requires a bucket name")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = client if client is not None else _build_client(endpoint_url, region)

    def _key(self, name: str) -> str:
        safe = self._safe(name)
        return f"{self._prefix}/{safe}" if self._prefix else safe

    def list_scores(self) -> list[StorageObject]:
        paginator = self._client.get_paginator("list_objects_v2")
        prefix = f"{self._prefix}/" if self._prefix else ""
        objects: list[StorageObject] = []
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                base = key[len(prefix):] if prefix else key
                if "/" in base or not base:
                    continue  # skip nested folders — flat namespace only
                if Path(base).suffix.lower() not in SUPPORTED_SCORE_EXTS:
                    continue
                modified = item.get("LastModified")
                objects.append(
                    StorageObject(
                        name=base,
                        size=int(item.get("Size", 0)),
                        modified=modified.timestamp() if modified else 0.0,
                    )
                )
        return sorted(objects, key=lambda o: o.name)

    def stat(self, name: str) -> StorageObject | None:
        try:
            from botocore.exceptions import ClientError  # type: ignore[import-untyped]
        except ImportError:  # pragma: no cover
            ClientError = Exception  # type: ignore[assignment,misc]
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=self._key(name))
        except ClientError:
            return None
        modified = head.get("LastModified")
        return StorageObject(
            name=self._safe(name),
            size=int(head.get("ContentLength", 0)),
            modified=modified.timestamp() if modified else 0.0,
        )

    def read_bytes(self, name: str) -> bytes:
        try:
            obj = self._client.get_object(Bucket=self._bucket, Key=self._key(name))
        except Exception as exc:  # noqa: BLE001 - normalise to storage error
            raise StorageNotFoundError(f"File not found: {self._safe(name)}") from exc
        return bytes(obj["Body"].read())

    def write_bytes(self, name: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._key(name), Body=data)

    def delete(self, name: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=self._key(name))


__all__ = ["S3StorageBackend"]
