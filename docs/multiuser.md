# Multi-user mode & per-user storage

FretWise can run as a multi-user web service where **each user authenticates via
OIDC and connects their own cloud storage**. The server stores **no partition
files of its own** — users are responsible for acquiring the rights to the files
they load, and their content is never shared with other users or kept as a
server-side library.

Multi-user mode is **opt-in**: with no OIDC provider configured, FretWise runs
exactly as the original single-user tool (unchanged behaviour and tests).

---

## How it works

```
Browser ──login──▶ OIDC provider (Google / generic)
   │  session cookie (signed)
   ▼
FretWise  ── per request ──▶ resolve the logged-in user's OWN cloud storage
   │                          (S3 / WebDAV / Google Drive) using their
   │                          encrypted credentials
   ▼
User's cloud  ◀── partitions live here, never on the FretWise server
```

- **Auth:** OpenID Connect. Google is a preset; any compliant OIDC provider can
  be added. First successful login **auto-creates** the account (self-service).
- **Identity → storage:** a pure-ASGI middleware resolves the session user and
  binds it to the request; every partition route is then served from *that
  user's* backend, resolved fresh per request (no cross-user sharing).
- **No local library:** the on-server `local` backend is **rejected** for users
  (`resolve_user_storage`). Cloud downloads land only in a transient, per-user
  cache directory used for parsing — not a persistent collection.
- **Credentials:** stored per user, **encrypted at rest** (Fernet) with a
  server key; never written to plain config, never logged, never shared.

### Packages

```
fretwise/auth/
├── config.py    # AuthConfig from env (providers, keys, dirs)
├── models.py    # User (+ allowed user backends: s3/webdav/gdrive, NOT local)
├── users.py     # UserStore — one JSON file per user
├── crypto.py    # Fernet cipher from FRETWISE_SECRET_KEY
├── secrets.py   # UserSecretsStore — per-user encrypted credentials
├── resolver.py  # resolve_user_storage() — per-user backend, rejects local
└── web.py       # OIDC login/callback, session, /api/me, storage connect
```

---

## Configuration (environment)

| Variable | Purpose |
|---|---|
| `FRETWISE_SECRET_KEY` | **Required.** Session signing + credential encryption. |
| `FRETWISE_BASE_URL` | Public URL, for the OAuth `redirect_uri` (e.g. `https://tabs.example.com`). |
| `FRETWISE_AUTH_ENABLED` | Force-enable (otherwise auto-on when a provider is set). |
| `FRETWISE_DATA_DIR` | Where users + encrypted secrets are stored. |
| `FRETWISE_STORAGE_CACHE_ROOT` | Transient per-user download cache root. |
| `FRETWISE_GOOGLE_CLIENT_ID` / `_SECRET` | Google login (requests Drive scope). |
| `FRETWISE_OIDC_ISSUER` / `_CLIENT_ID` / `_CLIENT_SECRET` / `_NAME` | Generic OIDC provider. |

Install the auth extra:

```bash
pip install -e ".[auth]"      # authlib, itsdangerous, cryptography
pip install -e ".[cloud]"     # the cloud SDKs users will use (boto3, httpx, google-*)
```

---

## Endpoints

| Route | Description |
|---|---|
| `GET /auth/login[/{provider}]` | Start OIDC login (defaults to first provider). |
| `GET /auth/callback/{provider}` | OIDC redirect target; creates the session. |
| `GET /auth/logout` | Clear the session. |
| `GET /api/me` | Current user + storage status (public; reports `authenticated:false`). |
| `POST /api/storage/connect` | Connect the user's own cloud (`{backend, config, credentials}`). |
| `POST /api/storage/disconnect` | Remove the user's storage + credentials. |

When auth is enabled, **all `/api/*` routes require a session** (except
`/api/me`) — unauthenticated requests get `401`.

### Connecting storage

```http
POST /api/storage/connect
{ "backend": "s3",
  "config": { "bucket": "my-tabs", "prefix": "scores", "endpoint_url": "", "region": "eu-west-3" },
  "credentials": { "access_key_id": "AKIA…", "secret_access_key": "…" } }
```

Per-backend credential keys:

- **s3:** `access_key_id`, `secret_access_key`, `session_token` (optional)
- **webdav:** `username`, `password` (config: `base_url`)
- **gdrive:** none needed — reuses the **Google login OAuth grant** captured at
  sign-in (config: `folder_id`). Sign in with Google (Drive permission) first.

`config` is stored on the user record (non-secret); `credentials` go only into
the encrypted per-user secrets store.

---

## Security properties

- Credentials encrypted at rest (Fernet) with a server-held key; secrets files
  are written `0600` and excluded from the user record and logs.
- Per-user isolation: separate user files, separate encrypted secret files, and
  a per-user (hashed-id) cache directory — nothing is shared across users.
- The server never persists a partition library; cloud downloads are a transient
  parsing cache, and the `local` backend is not user-selectable.
- Builds on the earlier hardening (Host-header guard, security headers, upload
  limits) — those still apply.

### Residual / follow-ups

- The transient per-user cache is not yet auto-evicted on logout; add a TTL or
  logout-time purge for stricter "no content on server" guarantees.
- Global settings/soundfont routes are shared server config; in multi-user mode
  they require login but are not yet per-user.
- Batch fingering refresh remains local-only (cloud users get a clear `400`).

---

## Testing

`tests/test_auth.py` covers the user store, credential encryption (real Fernet
in CI), per-user isolation, and the resolver policy (rejects `local`, requires
config, builds per-user backends via injected constructors) — all without the
web deps. The OIDC web flow (`authlib`) is validated in environments where the
`[auth]` extra is installed.
