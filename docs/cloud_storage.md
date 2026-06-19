# Cloud Storage for Partitions

FretWise stores score files (partitions) through a pluggable **storage backend**
abstraction (`fretwise.storage`). The default is the local filesystem, but the
web app can also read/write partitions from cloud services addressed by API:

| Backend  | `storage_backend` | Covers                                   | SDK (extra `cloud`)        |
|----------|-------------------|------------------------------------------|----------------------------|
| Local    | `local` (default) | A directory on the server                | — (built in)               |
| S3        | `s3`              | AWS S3, MinIO, Cloudflare R2, B2, Wasabi | `boto3`                    |
| WebDAV    | `webdav`          | Nextcloud, ownCloud, Apache mod_dav      | `httpx`                    |
| Google Drive | `gdrive`       | A Google Drive folder                    | `google-api-python-client`, `google-auth` |

Install the cloud SDKs you need:

```bash
pip install -e ".[cloud]"   # all three; each backend imports its SDK lazily
```

---

## Architecture

```
fretwise/storage/
├── base.py         # StorageBackend ABC, StorageObject, safe_score_name(), errors
├── local.py        # LocalStorageBackend (default)
├── remote.py       # RemoteStorageBackend — shared download-cache logic
├── s3.py           # S3StorageBackend (boto3)
├── webdav.py       # WebDavStorageBackend (httpx + defusedxml PROPFIND)
├── gdrive.py       # GoogleDriveStorageBackend (Drive v3)
├── credentials.py  # env / secrets-file credential loading
└── factory.py      # build_backend(cfg, local_root=…)
```

Every backend implements: `list_scores`, `exists`, `stat`, `read_bytes`,
`write_bytes`, `delete`, and `ensure_local`.

Parsers (PyGuitarPro / music21 / pretty_midi) need a **real local file path**.
`ensure_local(name)` provides one: a no-op for the local backend, and a cached
download for cloud backends (the cache is refreshed when the remote copy is
newer). This means the rest of the pipeline is unchanged regardless of backend.

`safe_score_name()` sanitises every object name to a basename with a supported
score extension — so the storage layer can never read/write arbitrary paths or
file types, on any backend.

---

## Configuration

Backend selection and **non-secret** settings live in the normal config
(`~/.fretwise/config.json`, editable via `POST /api/settings`). Example:

```json
{
  "storage_backend": "s3",
  "storage_cache_dir": "",
  "storage_s3": {
    "bucket": "my-tabs",
    "prefix": "partitions",
    "endpoint_url": "https://s3.eu-west-3.amazonaws.com",
    "region": "eu-west-3"
  },
  "storage_webdav": { "base_url": "https://cloud.example.com/remote.php/dav/files/me/Partitions/" },
  "storage_gdrive": { "folder_id": "1AbCdEf…" }
}
```

Switching backends at runtime via `POST /api/settings` rebuilds the active
backend in place. A misconfigured cloud backend never takes the server down —
it falls back to local and reports the error via `GET /api/storage`.

### Credentials — never in config.json

Secrets are read from the **environment** first, then an optional secrets file
(`~/.fretwise/secrets.json`, override with `FRETWISE_SECRETS_FILE`). They are
deliberately kept out of `config.json` so synced/committed settings never carry
access keys. Both `secrets.json` and the download cache are git-ignored.

| Backend | Variables |
|---------|-----------|
| S3      | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` (optional). Omit to use boto3's own chain (instance role, shared config). |
| WebDAV  | `WEBDAV_USERNAME`, `WEBDAV_PASSWORD` |
| Google Drive | `GOOGLE_APPLICATION_CREDENTIALS` → path to a service-account JSON key. Share the target Drive folder with the service-account email. |

Example secrets file:

```json
{
  "AWS_ACCESS_KEY_ID": "AKIA…",
  "AWS_SECRET_ACCESS_KEY": "…",
  "WEBDAV_PASSWORD": "…",
  "GOOGLE_APPLICATION_CREDENTIALS": "/etc/fretwise/gdrive-sa.json"
}
```

---

## API endpoints

The existing file routes are backend-agnostic:

- `GET  /api/files` — list partitions
- `GET  /api/download/{name}` — download original
- `POST /api/upload` — upload (size-capped, streamed)
- `GET  /api/tracks|notes|solve|export/...` — parse via `ensure_local`
- `GET  /api/storage` — **new**: report active backend + health
  ```json
  { "backend": "s3", "supports_batch_refresh": false,
    "local_root": null, "error": null }
  ```

### Known limitation

`POST /api/library/refresh-fingerings` (the in-place multiprocessing batch)
only runs on **local** storage — worker processes glob/read/write files by path.
On a cloud backend it returns HTTP 400 with a clear message rather than silently
doing nothing. Round-tripping the batch through cloud storage (download → finger
→ upload) is a planned follow-up.

---

## Security notes

- Object names are sanitised by `safe_score_name()` on every backend → no path
  traversal, no arbitrary file types.
- Credentials live only in env / secrets file, never in `config.json`.
- The WebDAV PROPFIND XML response is parsed with `defusedxml` (entity-expansion
  hardened), consistent with the GPIF parser.
- Cloud backends validate their config at construction and raise
  `StorageBackendUnavailable` (with an install/config hint) instead of failing
  obscurely later.

## Testing

`tests/test_storage.py` covers name-safety, the local backend, the factory, the
provider-agnostic download-cache (`RemoteStorageBackend`), the S3 mapping (via an
injected fake boto3 client) and WebDAV PROPFIND parsing — all **without network
or cloud SDKs**. Live cloud credentials are only needed for end-to-end runs.
