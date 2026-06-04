# Multi-user mode & per-user storage

FretWise can run as a multi-user web service where **each user authenticates via
OIDC and connects their own cloud storage**. The server stores **no partition
files of its own** — users are responsible for acquiring the rights to the files
they load, and their content is never shared with other users or kept as a
server-side library.

Multi-user mode is **opt-in**: with no OIDC provider, no local admin, and
`FRETWISE_AUTH_ENABLED` unset, FretWise runs exactly as the original single-user
tool (unchanged behaviour and tests). It can also run with a single
password-protected **local admin** and no Google at all — see
[Local admin login](#local-admin-login-no-google--oidc).

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

- **Auth:** two methods, usable together —
  - **Email + password** with email confirmation: register at `/register`, get
    an activation link by email, then sign in at `/login`. Passwords are stored
    as PBKDF2 hashes; accounts are inactive until the link is opened.
  - **OpenID Connect** (Google preset or any OIDC provider) — first login
    **auto-creates** the account (self-service).
- **Identity → storage:** a pure-ASGI middleware resolves the session user and
  binds it to the request; every partition route is then served from *that
  user's* backend, resolved fresh per request (no cross-user sharing).
- **No local library for regular users:** the on-server `local` backend is
  **rejected** for ordinary users (`resolve_user_storage`). Cloud downloads land
  only in a transient, per-user cache directory used for parsing — not a
  persistent collection.
- **Admin-only server library (Option B):** users whose email is in
  `FRETWISE_ADMIN_EMAILS` may additionally select the server-hosted `local`
  partitions directory (the original `--dir`/`partitions_dir`). Use this to
  curate a vetted, freely-distributable set. Regular users never see it; only
  put content there that you have the right to host.
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
| `FRETWISE_AUTH_ENABLED` | `1` to enable email/password auth without any OIDC provider. |
| `FRETWISE_ADMIN_EMAILS` | Comma-separated emails granted admin rights (access to the server-local library). |
| `FRETWISE_ADMIN_EMAIL` | Email for a pre-seeded **local admin** account (password login, no Google needed). |
| `FRETWISE_ADMIN_PASSWORD_HASH` | PBKDF2 **hash** of the admin password (never the plaintext). Generate with `fretwise hash-password`. |
| `FRETWISE_GOOGLE_CLIENT_ID` / `_SECRET` | Google login (requests Drive scope). |
| `FRETWISE_OIDC_ISSUER` / `_CLIENT_ID` / `_CLIENT_SECRET` / `_NAME` | Generic OIDC provider. |
| `FRETWISE_SMTP_HOST` / `_PORT` / `_USER` / `_PASSWORD` / `_FROM` / `_TLS` | SMTP for activation emails. If unset, the activation link is logged (dev fallback). |

For OAuth/OIDC, always open the app with the same origin as `FRETWISE_BASE_URL`.
For example, if `FRETWISE_BASE_URL=http://localhost:8080`, start login from
`http://localhost:8080` too. Starting from `http://127.0.0.1:8080` stores the
OAuth state under a different browser cookie origin, and the callback can fail
with `mismatching_state`.

### Local admin login (no Google / OIDC)

You can run FretWise with a single password-protected admin and **no OIDC
provider at all**.

**Simplest form — username + password in your (gitignored) `.env`:**

```
FRETWISE_ADMIN=benoit
FRETWISE_ADMIN_PASSWD=<REMOVED_SECRET>
```

The username is the login identifier and the password is read **only** from the
environment — it is hashed at startup, so the on-disk account store never holds
the plaintext (and `.env` is gitignored, so it never reaches the repo). On the
`/login` page Google sign-in is shown large at the top; the username/password
fields appear below under a small **"Local accounts"** heading. Setting these two
vars turns auth on by itself, with no OIDC provider required.

**Alternative — pre-hashed (for shared/committed config):**
`FRETWISE_ADMIN_EMAIL` + `FRETWISE_ADMIN_PASSWORD_HASH` ensures a pre-activated
admin account with that email and a precomputed hash. The admin logs in at
`/login` with email + password — no activation email, no Google round-trip.

The admin is granted admin rights, so they use the **server-local partitions
library** (the `local` storage backend, served from the `fretwise web --dir`
directory) — the same behaviour as the old single-operator setup.

The password is **never** stored in plaintext anywhere. You provide only a
precomputed PBKDF2 hash, generated with the `hash-password` command:

```bash
# Prompts for the password (not echoed), prints the hash to stdout:
export FRETWISE_ADMIN_EMAIL=me@example.com
export FRETWISE_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export FRETWISE_ADMIN_PASSWORD_HASH="$(fretwise hash-password)"

fretwise web --dir ./partitions
# → open http://localhost:8080, log in with me@example.com + your password
```

`fretwise hash-password` reads the password interactively (twice, to confirm) and
prints only the hash. Use `fretwise hash-password --stdin` to read it from a pipe
in non-interactive setups. Seeding is **idempotent**: restarting with a changed
`FRETWISE_ADMIN_PASSWORD_HASH` rotates the stored hash; an unchanged hash is a
no-op.

> `FRETWISE_SECRET_KEY` is still required (session signing). If auth is configured
> but the secret key (or the `[auth]` extra) is missing, the server refuses to
> start rather than silently running unauthenticated.

### Email + password endpoints / pages

| Route | Description |
|---|---|
| `GET /login`, `GET /register` | Sign-in / sign-up pages (served only in multi-user mode). |
| `GET /api/auth/methods` | Which methods are available (`password` + OIDC `providers`). |
| `POST /api/auth/register` | `{email, password}` → creates an inactive account, emails an activation link. Generic response (no email enumeration). |
| `GET /auth/activate?token=…` | Activates the account, redirects to `/login?activated=1`. |
| `POST /api/auth/login` | `{email, password}` → sets the session (`403` if not activated, `401` if wrong). |
| `POST /api/auth/resend` | `{email}` → re-sends an activation link if the account is inactive. |

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
`/api/me`) — unauthenticated requests get `401`. Server-global operations
(`GET`/`POST /api/settings`, `/api/soundfonts/*` upload/delete/activate, and
`/api/library/refresh-fingerings`) additionally require an **admin** account
(`403` otherwise). Per-user file routes are scoped to the caller's own storage.

If an OIDC provider is configured but auth cannot be initialised (missing
`[auth]` extra or `FRETWISE_SECRET_KEY`), the server **refuses to start**
(fail-closed) rather than silently serving the local library without auth.

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
- **local:** admins only; no credentials/config — serves the server's
  `partitions_dir`. Rejected for non-admins.

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
- Global settings/soundfont routes are shared server config and are now
  admin-only in multi-user mode (not per-user).
- Batch fingering refresh remains local-only (cloud users get a clear `400`).

---

## Testing

`tests/test_auth.py` covers the user store, credential encryption (real Fernet
in CI), per-user isolation, and the resolver policy (rejects `local`, requires
config, builds per-user backends via injected constructors) — all without the
web deps. The OIDC web flow (`authlib`) is validated in environments where the
`[auth]` extra is installed.
