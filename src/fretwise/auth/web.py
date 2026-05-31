"""Web wiring for multi-user OIDC auth and per-user storage.

``setup_auth`` is called from the app factory only when auth is enabled; when it
is not, none of this runs and the app behaves as the original single-user tool.

Heavy/optional dependencies (Authlib, Starlette SessionMiddleware) are imported
lazily inside :func:`setup_auth`, so importing this module never requires them.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from fretwise.auth.accounts import EmailAlreadyRegistered, LocalAccountStore, normalize_email
from fretwise.auth.config import AuthConfig
from fretwise.auth.mailer import SmtpConfig, load_smtp_config, send_activation_email
from fretwise.auth.models import User, allowed_backends
from fretwise.auth.passwords import verify_password
from fretwise.auth.secrets import UserSecretsStore
from fretwise.auth.users import UserStore

# Static auth pages live in the web package (src/fretwise/web/static).
_STATIC_DIR = Path(__file__).resolve().parents[1] / "web" / "static"

# Holds the authenticated user for the current request. Set by the pure-ASGI
# middleware below (which runs in the same task as the endpoint, so the value
# reaches both async and threadpool/sync endpoints).
_REQUEST_USER: ContextVar[User | None] = ContextVar("fretwise_request_user", default=None)

# /api paths reachable without authentication when multi-user mode is on.
_PUBLIC_API_PATHS = frozenset({
    "/api/me",
    "/api/auth/methods",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/resend",
})


def current_request_user() -> User | None:
    """Return the user authenticated for the current request, if any."""
    return _REQUEST_USER.get()


class UserContextMiddleware:
    """Pure-ASGI middleware: resolve the session user and gate /api routes.

    Pure ASGI (not BaseHTTPMiddleware) so the ContextVar set here is visible to
    downstream endpoints, including sync endpoints run in the threadpool.
    """

    def __init__(self, app: Any, user_store: UserStore) -> None:
        self.app = app
        self.user_store = user_store

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        session = scope.get("session") or {}
        uid = session.get("user_id")
        user = self.user_store.get(uid) if uid else None
        path = scope.get("path", "")
        if user is None and self._is_protected(path):
            await self._send_401(send)
            return
        token = _REQUEST_USER.set(user)
        try:
            await self.app(scope, receive, send)
        finally:
            _REQUEST_USER.reset(token)

    @staticmethod
    def _is_protected(path: str) -> bool:
        return path.startswith("/api/") and path not in _PUBLIC_API_PATHS

    @staticmethod
    async def _send_401(send: Any) -> None:
        body = json.dumps({"detail": "Authentication required"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})


def setup_auth(
    app: Any,
    config: AuthConfig,
    user_store: UserStore,
    secrets_store: UserSecretsStore,
    account_store: LocalAccountStore,
    *,
    smtp_config: SmtpConfig | None = None,
) -> None:
    """Install session auth (email/password + optional OIDC) and routes."""
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
    from starlette.middleware.sessions import SessionMiddleware

    if not config.secret_key:
        raise RuntimeError(
            "FRETWISE_SECRET_KEY must be set to enable multi-user auth "
            "(used for session signing and credential encryption)."
        )

    smtp_cfg = smtp_config if smtp_config is not None else load_smtp_config()

    # OIDC is optional — only pull in Authlib when a provider is configured, so
    # email/password-only deployments don't need it.
    oauth = None
    if config.providers:
        from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]

        oauth = OAuth()
        for p in config.providers:
            oauth.register(
                name=p.name,
                client_id=p.client_id,
                client_secret=p.client_secret,
                server_metadata_url=p.server_metadata_url,
                client_kwargs={"scope": p.scopes, "access_type": "offline", "prompt": "consent"},
            )
        app.state.oauth = oauth

    # Order matters: add the user-context middleware first so that, after the
    # SessionMiddleware is added (and becomes outer), the session is already
    # populated into the ASGI scope when UserContextMiddleware runs.
    app.add_middleware(UserContextMiddleware, user_store=user_store)
    app.add_middleware(
        SessionMiddleware,
        secret_key=config.secret_key,
        same_site="lax",
        https_only=config.base_url.startswith("https://"),
    )

    router = APIRouter()

    def _abs_url(request: Request, path: str) -> str:
        base = config.base_url or str(request.base_url).rstrip("/")
        return f"{base}{path}"

    def _serve_page(name: str) -> Any:
        html = (_STATIC_DIR / name).read_text(encoding="utf-8")
        return HTMLResponse(content=html)

    # --- Page routes (login / register) -----------------------------------

    @router.get("/login")
    async def login_page() -> Any:
        if current_request_user() is not None:
            return RedirectResponse(url="/", status_code=303)
        return _serve_page("login.html")

    @router.get("/register")
    async def register_page() -> Any:
        if current_request_user() is not None:
            return RedirectResponse(url="/", status_code=303)
        return _serve_page("register.html")

    @router.get("/api/auth/methods")
    async def auth_methods() -> JSONResponse:
        return JSONResponse({
            "password": True,
            "providers": [p.name for p in config.providers],
        })

    # --- Email + password (local accounts) --------------------------------

    @router.post("/api/auth/register")
    async def register_account(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        email = str(body.get("email", ""))
        password = str(body.get("password", ""))
        try:
            account = account_store.register(email, password)
        except EmailAlreadyRegistered:
            # Don't reveal whether the email already exists (anti-enumeration).
            return JSONResponse(
                {"status": "ok", "message": "Check your email to activate your account."}
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        send_activation_email(
            account.email,
            _abs_url(request, f"/auth/activate?token={account.activation_token}"),
            config=smtp_cfg,
        )
        return JSONResponse(
            {"status": "ok", "message": "Check your email to activate your account."}
        )

    @router.get("/auth/activate")
    async def activate_account(request: Request, token: str = "") -> Any:
        account = account_store.activate(token)
        if account is None:
            return RedirectResponse(url="/login?error=activation", status_code=303)
        user_store.get_or_create(
            account.user_id, email=account.email,
            is_admin=config.is_admin_email(account.email),
        )
        return RedirectResponse(url="/login?activated=1", status_code=303)

    @router.post("/api/auth/login")
    async def local_login(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        email = normalize_email(str(body.get("email", "")))
        password = str(body.get("password", ""))
        existing = account_store.get(email)
        if existing is not None and not existing.is_active and verify_password(
            password, existing.password_hash
        ):
            raise HTTPException(403, "Account not activated — check your email.")
        account = account_store.verify_login(email, password)
        if account is None:
            raise HTTPException(401, "Invalid email or password.")
        user = user_store.get_or_create(
            account.user_id, email=account.email,
            is_admin=config.is_admin_email(account.email),
        )
        request.session["user_id"] = user.id
        return JSONResponse({"status": "ok"})

    @router.post("/api/auth/resend")
    async def resend_activation(request: Request) -> JSONResponse:
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        account = account_store.new_activation_token(normalize_email(str(body.get("email", ""))))
        if account is not None and not account.is_active and account.activation_token:
            send_activation_email(
                account.email,
                _abs_url(request, f"/auth/activate?token={account.activation_token}"),
                config=smtp_cfg,
            )
        return JSONResponse(
            {"status": "ok", "message": "If the account exists and is inactive, a link was sent."}
        )

    # --- OIDC (optional) --------------------------------------------------

    def _redirect_uri(request: Request, provider: str) -> str:
        if config.base_url:
            return f"{config.base_url}/auth/callback/{provider}"
        return str(request.url_for("auth_callback", provider=provider))

    @router.get("/auth/login")
    @router.get("/auth/login/{provider}")
    async def login(request: Request, provider: str | None = None) -> Any:
        if oauth is None:
            raise HTTPException(404, "No OIDC provider configured")
        provider = provider or (config.providers[0].name if config.providers else "")
        client = oauth.create_client(provider)
        if client is None:
            raise HTTPException(404, f"Unknown auth provider: {provider}")
        return await client.authorize_redirect(request, _redirect_uri(request, provider))

    @router.get("/auth/callback/{provider}", name="auth_callback")
    async def auth_callback(request: Request, provider: str) -> Any:
        client = oauth.create_client(provider)
        if client is None:
            raise HTTPException(404, f"Unknown auth provider: {provider}")
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo") or await client.userinfo(token=token)
        subject = userinfo.get("sub") or userinfo.get("email")
        if not subject:
            raise HTTPException(400, "Identity provider returned no subject")
        uid = f"{provider}:{subject}"
        email = userinfo.get("email", "")
        user_store.get_or_create(
            uid, email=email, name=userinfo.get("name", ""),
            is_admin=config.is_admin_email(email),
        )
        request.session["user_id"] = uid

        # Capture the Google OAuth grant so the user can use their own Drive
        # without sharing a service account. Best-effort: skipped if no secret
        # key is configured for encryption.
        if provider == "google" and token.get("access_token"):
            try:
                existing = secrets_store.get(uid) or {}
                existing["google_oauth"] = {
                    "token": token.get("access_token"),
                    "refresh_token": token.get("refresh_token"),
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "client_id": config.provider("google").client_id,  # type: ignore[union-attr]
                    "client_secret": config.provider("google").client_secret,  # type: ignore[union-attr]
                    "scopes": ["https://www.googleapis.com/auth/drive.file"],
                }
                secrets_store.set(uid, existing)
            except Exception:  # noqa: BLE001 - never fail login on secret write
                pass
        return RedirectResponse(url="/", status_code=303)

    @router.get("/auth/logout")
    async def logout(request: Request) -> Any:
        request.session.pop("user_id", None)
        return RedirectResponse(url="/", status_code=303)

    @router.get("/api/me")
    async def me() -> JSONResponse:
        user = current_request_user()
        if user is None:
            return JSONResponse({"authenticated": False})
        return JSONResponse({
            "authenticated": True,
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "is_admin": user.is_admin,
            "storage_backend": user.storage_backend,
            "has_storage": user.has_storage,
            "available_backends": sorted(allowed_backends(user.is_admin)),
        })

    @router.post("/api/storage/connect")
    async def connect_storage(request: Request) -> JSONResponse:
        """Connect the current user's own cloud storage (per-user, isolated)."""
        user = current_request_user()
        if user is None:
            raise HTTPException(401, "Authentication required")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        backend = str(body.get("backend", "")).lower()
        permitted = allowed_backends(user.is_admin)
        if backend not in permitted:
            raise HTTPException(
                400, f"backend must be one of {sorted(permitted)}",
            )
        config_part = dict(body.get("config", {}) or {})
        credentials = dict(body.get("credentials", {}) or {})

        # Admin-only server-local library: no credentials, no config needed.
        if backend == "local":
            user_store.set_storage(user.id, "local", {})
            return JSONResponse({"status": "connected", "backend": "local"})

        # Google Drive can reuse the OAuth grant captured at login.
        if backend == "gdrive" and not credentials:
            stored = secrets_store.get(user.id) or {}
            credentials = dict(stored.get("google_oauth", {}))
            if not credentials:
                raise HTTPException(
                    400, "Sign in with Google (Drive permission) before connecting Drive.",
                )

        try:
            secrets_store.set(user.id, credentials)
        except Exception as exc:  # noqa: BLE001 - surface a clean setup error
            raise HTTPException(500, f"Could not store credentials: {exc}")
        user_store.set_storage(user.id, backend, config_part)
        return JSONResponse({"status": "connected", "backend": backend})

    @router.post("/api/storage/disconnect")
    async def disconnect_storage() -> JSONResponse:
        user = current_request_user()
        if user is None:
            raise HTTPException(401, "Authentication required")
        secrets_store.delete(user.id)
        user_store.set_storage(user.id, "", {})
        return JSONResponse({"status": "disconnected"})

    app.include_router(router)


__all__ = ["UserContextMiddleware", "current_request_user", "setup_auth"]
