"""WebDAV / Nextcloud / ownCloud storage backend.

Talks plain WebDAV over HTTP via httpx, so it works against Nextcloud,
ownCloud, Apache mod_dav and any other compliant server. Credentials come from
the env / secrets file (``WEBDAV_USERNAME`` / ``WEBDAV_PASSWORD``).
"""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

from fretwise.storage.base import (
    SUPPORTED_SCORE_EXTS,
    StorageBackendUnavailable,
    StorageNotFoundError,
    StorageObject,
)
from fretwise.storage.credentials import load_webdav_credentials
from fretwise.storage.remote import RemoteStorageBackend

_DAV = "{DAV:}"

_PROPFIND_BODY = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<d:propfind xmlns:d="DAV:"><d:prop>'
    "<d:getcontentlength/><d:getlastmodified/><d:resourcetype/>"
    "</d:prop></d:propfind>"
)


def _build_client(base_url: str, auth: tuple[str, str] | None) -> Any:
    """Create an httpx client, raising a clear error if httpx is missing."""
    try:
        import httpx  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise StorageBackendUnavailable(
            "WebDAV storage requires httpx. Install it with: pip install 'fretwise[cloud]'"
        ) from exc
    return httpx.Client(base_url=base_url, auth=auth, timeout=30.0, follow_redirects=True)


class WebDavStorageBackend(RemoteStorageBackend):
    """Store score files in a single WebDAV collection (folder)."""

    name = "webdav"

    def __init__(
        self,
        *,
        base_url: str,
        cache_dir: Path,
        client: Any | None = None,
    ) -> None:
        """Create the backend.

        Args:
            base_url: URL of the collection holding the score files. A trailing
                slash is added if missing.
            cache_dir: Local cache directory for downloaded objects.
            client: Pre-built httpx-style client (mainly for tests).
        """
        super().__init__(cache_dir)
        if not base_url:
            raise StorageBackendUnavailable("WebDAV storage requires a base_url")
        self._base_url = base_url if base_url.endswith("/") else base_url + "/"
        if client is not None:
            self._client = client
        else:
            creds = load_webdav_credentials()
            auth = (
                (creds["username"], creds["password"])
                if "username" in creds and "password" in creds
                else None
            )
            self._client = _build_client(self._base_url, auth)

    def _url(self, name: str) -> str:
        return self._base_url + quote(self._safe(name))

    @staticmethod
    def _parse_multistatus(xml_text: str) -> list[StorageObject]:
        from defusedxml.ElementTree import fromstring  # type: ignore[import-untyped]

        root = fromstring(xml_text)
        objects: list[StorageObject] = []
        for resp in root.findall(f"{_DAV}response"):
            href = resp.findtext(f"{_DAV}href") or ""
            prop = resp.find(f"{_DAV}propstat/{_DAV}prop")
            if prop is None:
                continue
            # Skip collections (folders) — we only list files.
            if prop.find(f"{_DAV}resourcetype/{_DAV}collection") is not None:
                continue
            base = unquote(urlsplit(href).path.rstrip("/").rsplit("/", 1)[-1])
            if not base or Path(base).suffix.lower() not in SUPPORTED_SCORE_EXTS:
                continue
            size_text = prop.findtext(f"{_DAV}getcontentlength") or "0"
            mod_text = prop.findtext(f"{_DAV}getlastmodified") or ""
            modified = 0.0
            if mod_text:
                try:
                    modified = parsedate_to_datetime(mod_text).timestamp()
                except (TypeError, ValueError):
                    modified = 0.0
            try:
                size = int(size_text)
            except ValueError:
                size = 0
            objects.append(StorageObject(name=base, size=size, modified=modified))
        return objects

    def list_scores(self) -> list[StorageObject]:
        resp = self._client.request(
            "PROPFIND", self._base_url,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            content=_PROPFIND_BODY,
        )
        if resp.status_code not in (207, 200):
            raise StorageBackendUnavailable(
                f"WebDAV PROPFIND failed: HTTP {resp.status_code}"
            )
        return sorted(self._parse_multistatus(resp.text), key=lambda o: o.name)

    def stat(self, name: str) -> StorageObject | None:
        safe = self._safe(name)
        resp = self._client.request(
            "PROPFIND", self._url(safe),
            headers={"Depth": "0", "Content-Type": "application/xml"},
            content=_PROPFIND_BODY,
        )
        if resp.status_code == 404:
            return None
        if resp.status_code not in (207, 200):
            return None
        items = self._parse_multistatus(resp.text)
        for obj in items:
            if obj.name == safe:
                return obj
        # Single-resource PROPFIND: fall back to the first file entry.
        return items[0] if items else None

    def read_bytes(self, name: str) -> bytes:
        resp = self._client.get(self._url(name))
        if resp.status_code == 404:
            raise StorageNotFoundError(f"File not found: {self._safe(name)}")
        resp.raise_for_status()
        return bytes(resp.content)

    def write_bytes(self, name: str, data: bytes) -> None:
        resp = self._client.put(self._url(name), content=data)
        if resp.status_code not in (200, 201, 204):
            raise StorageBackendUnavailable(
                f"WebDAV PUT failed: HTTP {resp.status_code}"
            )

    def delete(self, name: str) -> None:
        resp = self._client.delete(self._url(name))
        if resp.status_code == 404:
            raise StorageNotFoundError(f"File not found: {self._safe(name)}")
        if resp.status_code not in (200, 204):
            raise StorageBackendUnavailable(
                f"WebDAV DELETE failed: HTTP {resp.status_code}"
            )


__all__ = ["WebDavStorageBackend"]
