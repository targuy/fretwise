"""Google Drive storage backend.

Stores score files inside a single Drive folder (``folder_id``). Authenticates
with a service account whose JSON key path is given by
``GOOGLE_APPLICATION_CREDENTIALS`` (env / secrets file). Share the target folder
with the service-account email so it can read/write.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from fretwise.storage.base import (
    SUPPORTED_SCORE_EXTS,
    StorageBackendUnavailable,
    StorageNotFoundError,
    StorageObject,
)
from fretwise.storage.credentials import load_gdrive_service_account
from fretwise.storage.remote import RemoteStorageBackend

_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _parse_rfc3339(value: str | None) -> float:
    if not value:
        return 0.0
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _build_service() -> Any:
    """Build a Drive v3 service, raising a clear error if deps/creds missing."""
    try:
        from google.oauth2 import service_account  # type: ignore[import-untyped]
        from googleapiclient.discovery import build  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise StorageBackendUnavailable(
            "Google Drive storage requires google-api-python-client and "
            "google-auth. Install with: pip install 'fretwise[cloud]'"
        ) from exc
    key_path = load_gdrive_service_account()
    if not key_path:
        raise StorageBackendUnavailable(
            "Google Drive storage requires GOOGLE_APPLICATION_CREDENTIALS "
            "(path to a service-account JSON key)."
        )
    creds = service_account.Credentials.from_service_account_file(key_path, scopes=_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def service_from_oauth(token: dict[str, Any]) -> Any:
    """Build a Drive v3 service from a per-user OAuth token grant.

    Used in multi-user mode: each user authorises FretWise to access *their own*
    Drive (no server-side service account). ``token`` carries the fields stored
    after the OAuth consent: ``token``, ``refresh_token``, ``token_uri``,
    ``client_id``, ``client_secret`` and optionally ``scopes``.
    """
    try:
        from google.oauth2.credentials import Credentials  # type: ignore[import-untyped]
        from googleapiclient.discovery import build  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise StorageBackendUnavailable(
            "Google Drive storage requires google-api-python-client and "
            "google-auth. Install with: pip install 'fretwise[cloud]'"
        ) from exc
    creds = Credentials(
        token=token.get("token"),
        refresh_token=token.get("refresh_token"),
        token_uri=token.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=token.get("client_id"),
        client_secret=token.get("client_secret"),
        scopes=token.get("scopes", _SCOPES),
    )
    return build("drive", "v3", credentials=creds, cache_discovery=False)


class GoogleDriveStorageBackend(RemoteStorageBackend):
    """Store score files in a single Google Drive folder."""

    name = "gdrive"

    def __init__(
        self,
        *,
        folder_id: str,
        cache_dir: Path,
        service: Any | None = None,
    ) -> None:
        """Create the backend.

        Args:
            folder_id: ID of the Drive folder holding the score files.
            cache_dir: Local cache directory for downloaded objects.
            service: Pre-built Drive service (mainly for tests).
        """
        super().__init__(cache_dir)
        if not folder_id:
            raise StorageBackendUnavailable("Google Drive storage requires a folder_id")
        self._folder_id = folder_id
        self._service = service if service is not None else _build_service()

    def _find_id(self, name: str) -> str | None:
        safe = self._safe(name)
        # Escape single quotes for the Drive query language.
        escaped = safe.replace("'", "\\'")
        resp = (
            self._service.files()
            .list(
                q=f"name = '{escaped}' and '{self._folder_id}' in parents and trashed = false",
                fields="files(id, name)",
                pageSize=1,
            )
            .execute()
        )
        files = resp.get("files", [])
        return files[0]["id"] if files else None

    def list_scores(self) -> list[StorageObject]:
        objects: list[StorageObject] = []
        page_token: str | None = None
        while True:
            resp = (
                self._service.files()
                .list(
                    q=f"'{self._folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, size, modifiedTime)",
                    pageSize=1000,
                    pageToken=page_token,
                )
                .execute()
            )
            for item in resp.get("files", []):
                name = item.get("name", "")
                if Path(name).suffix.lower() not in SUPPORTED_SCORE_EXTS:
                    continue
                objects.append(
                    StorageObject(
                        name=name,
                        size=int(item.get("size", 0) or 0),
                        modified=_parse_rfc3339(item.get("modifiedTime")),
                    )
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return sorted(objects, key=lambda o: o.name)

    def stat(self, name: str) -> StorageObject | None:
        file_id = self._find_id(name)
        if not file_id:
            return None
        item = (
            self._service.files()
            .get(fileId=file_id, fields="id, name, size, modifiedTime")
            .execute()
        )
        return StorageObject(
            name=item.get("name", self._safe(name)),
            size=int(item.get("size", 0) or 0),
            modified=_parse_rfc3339(item.get("modifiedTime")),
        )

    def read_bytes(self, name: str) -> bytes:
        file_id = self._find_id(name)
        if not file_id:
            raise StorageNotFoundError(f"File not found: {self._safe(name)}")
        return bytes(self._service.files().get_media(fileId=file_id).execute())

    def write_bytes(self, name: str, data: bytes) -> None:
        from googleapiclient.http import MediaInMemoryUpload  # type: ignore[import-untyped]

        safe = self._safe(name)
        media = MediaInMemoryUpload(data, resumable=False)
        file_id = self._find_id(safe)
        if file_id:
            self._service.files().update(fileId=file_id, media_body=media).execute()
        else:
            self._service.files().create(
                body={"name": safe, "parents": [self._folder_id]},
                media_body=media,
                fields="id",
            ).execute()

    def delete(self, name: str) -> None:
        file_id = self._find_id(name)
        if not file_id:
            raise StorageNotFoundError(f"File not found: {self._safe(name)}")
        self._service.files().delete(fileId=file_id).execute()


__all__ = ["GoogleDriveStorageBackend"]
