# Security Hardening — Web App & Parser

This note documents the security review of the FretWise web server / parsing
surface and the fixes applied on branch `claude/code-review-security-46q6A`.

The web app (`src/fretwise/web/app.py`) is a **local, unauthenticated** FastAPI
server. It ingests untrusted score files (uploaded `.gp` / `.xml` / `.mid`) and
serves files, SVG and PDF back. The review focused on that trust boundary.

---

## Fixes applied

### 1. Arbitrary file read via `partitions_dir` override — **HIGH** ✅ fixed
`POST /api/settings` lets a caller repoint `partitions_dir` at any existing
directory, and `GET /api/download/{filename}` served any file inside it with no
type restriction. Chained, this allowed reading arbitrary host files
(e.g. set `partitions_dir=~/.ssh`, then `GET /api/download/id_rsa`).

**Fix** — `_resolve_file()` now rejects any path whose extension is outside the
score-format allowlist (`_SUPPORTED_SCORE_EXTS`). Every file-serving / parsing
route funnels through this helper, so a mis-pointed `partitions_dir` can only
ever expose score files, never `id_rsa` / `/etc/passwd` / arbitrary content.
The basename-only sanitisation and `relative_to` containment check are retained
as defence in depth.

### 2. No Host-header validation (DNS-rebinding) — **MEDIUM** ✅ fixed
With no auth and no `Host`/`Origin` checks, a malicious web page could use DNS
rebinding to reach the loopback server and drive its state-changing endpoints.

**Fix** — added `TrustedHostMiddleware`. The allowlist is **loopback-only by
default** (`localhost`, `127.0.0.1`, `[::1]`, `testserver`) and overridable via
the `FRETWISE_ALLOWED_HOSTS` environment variable (comma-separated, `*` to
disable). The CLI adds the explicit `--host` value to the allowlist and prints a
warning when binding to `0.0.0.0` (which exposes the unauthenticated API on all
interfaces).

### 3. Unbounded in-memory uploads (DoS) — **MEDIUM** ✅ fixed
`upload_file` and `upload_soundfont` did `await file.read()`, loading the entire
body into memory — a single huge upload could exhaust process memory.

**Fix** — `_read_upload_limited()` streams the body in 1 MiB chunks and aborts
with HTTP 413 once the limit is exceeded. Limits: **50 MiB** for score files,
**512 MiB** for soundfonts (SF2 banks are large). Tune via
`_MAX_SCORE_UPLOAD_BYTES` / `_MAX_SOUNDFONT_UPLOAD_BYTES`.

### 4. XML entity-expansion DoS ("billion laughs") — **MEDIUM** ✅ fixed
`_load_gpif` parsed the untrusted GPIF XML with stdlib `ElementTree`, which
expands internal entities and is vulnerable to billion-laughs blowups. (External
-entity XXE is not possible with ElementTree — only the DoS.)

**Fix** — added `defusedxml` as a dependency and routed the untrusted parse
through `_safe_parse_xml()`, which uses `defusedxml.ElementTree` when available
and falls back to stdlib otherwise (so functionality is preserved if the extra
is missing, just without the extra hardening).

### 5. Missing traversal guard on `activate_soundfont` — **LOW** ✅ fixed
`delete_soundfont` validated `sf_name` against traversal but `activate_soundfont`
did not, so an absolute/`..` name could set `active_soundfont` to an arbitrary
path. **Fix** — added the same `resolve().relative_to(sf_dir)` guard (and a
matching one on the soundfont upload destination).

### 6. No concurrency guard on `refresh-fingerings` — **LOW** ✅ fixed
Two concurrent `POST /api/library/refresh-fingerings` calls spawned two process
pools contending for CPU and double-writing outputs. **Fix** — the route now
returns HTTP 409 if a batch is already running (`app.state._batch_running`).

### 7. Missing baseline security headers — **LOW** ✅ fixed
The response middleware now sets `X-Content-Type-Options: nosniff`,
`X-Frame-Options: DENY` and `Referrer-Policy: no-referrer` on every response.
(A strict `Content-Security-Policy` was intentionally **not** added — the
frontend relies on inline scripts/styles and inline SVG, so a strict CSP would
break it without a larger refactor. See residual items.)

---

## New / changed configuration

| Setting | Default | Purpose |
|---|---|---|
| `FRETWISE_ALLOWED_HOSTS` (env) | loopback only | Host-header allowlist; `*` disables the guard |
| `_MAX_SCORE_UPLOAD_BYTES` | 50 MiB | Score upload ceiling |
| `_MAX_SOUNDFONT_UPLOAD_BYTES` | 512 MiB | Soundfont upload ceiling |
| `defusedxml>=0.7` (dep) | required | Hardened GPIF XML parsing |

---

## Already-good properties (kept, not changed)

- `{filename}` routes reduce input to `Path(...).name` → no path traversal.
- Server output is escaped (`html.escape` server-side in `core/backends/svg.py`,
  `_esc` client-side in `static/js/main.js`) → XSS mitigated.
- GPIF read and `gp_writer` open named zip members rather than `extractall` →
  no zip-slip.
- Server binds `127.0.0.1` by default.

---

## Residual items (not addressed — recommended follow-ups)

- **No authentication / CSRF tokens.** Acceptable for a single-user localhost
  tool hardened with the Host guard above, but add a token/`Sec-Fetch-Site`
  check before exposing it to multiple users.
- **`partitions_dir` may still point anywhere on disk** (now limited to serving
  *score files only*). Consider confining it to an allowlisted base directory.
- **MusicXML parsing via `music21`** is not routed through `defusedxml`; the
  same billion-laughs class theoretically applies. Bound parse time/size if
  large untrusted MusicXML becomes a concern.
- **Error messages** still return `str(exc)` to clients in a few places, which
  can leak filesystem paths. Consider generic messages + server-side logging.
- **No `Content-Security-Policy`** (see fix #7) — needs a frontend pass to move
  inline scripts/styles to files first.

---

## Testing

The fixes are behaviour-preserving for valid inputs:
- Score routes still accept the same extensions (the allowlist matches the
  previous per-route check, now centralised).
- Direct-call unit tests in `tests/test_web_export_pdf.py` are unaffected
  (they invoke endpoints directly; the new middleware only runs in the ASGI
  request cycle).
- `ruff check` passes on the edited files with no net-new findings.

> Note: the full `pytest` suite requires the runtime deps (`fastapi`,
> `pretty_midi`, `PyGuitarPro`, …) which must be installed via
> `pip install -e ".[dev]"` in an environment with network access.
