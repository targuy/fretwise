"""Web wiring for multi-user OIDC auth and per-user storage.

``setup_auth`` is called from the app factory only when auth is enabled; when it
is not, none of this runs and the app behaves as the original single-user tool.

Heavy/optional dependencies (Authlib, Starlette SessionMiddleware) are imported
lazily inside :func:`setup_auth`, so importing this module never requires them.
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Any

from fretwise.auth.config import AuthConfig
from fretwise.auth.models import USER_STORAGE_BACKENDS, User
from fretwise.auth.secrets import UserSecretsStore
from fretwise.auth.users import UserStore

# Holds the authenticated user for the current request. Set by the pure-ASGI
# middleware below (which runs in the same task as the endpoint, so the value
# reaches both async and threadpool/sync endpoints).
_REQUEST_USER: ContextVar[User | None] = ContextVar("fretwise_request_user", default=None)

# /api paths reachable without authentication when multi-user mode is on.
_PUBLIC_API_PATHS = frozenset({"/api/me"})


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
) -> None:
    """Install session + OIDC auth and per-user storage routes onto *app*."""
    from authlib.integrations.starlette_client import OAuth  # type: ignore[import-untyped]
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import JSONResponse, RedirectResponse
    from starlette.middleware.sessions import SessionMiddleware

    if not config.secret_key:
        raise RuntimeError(
            "FRETWISE_SECRET_KEY must be set to enable multi-user auth "
            "(used for session signing and credential encryption)."
        )

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

    def _redirect_uri(request: Request, provider: str) -> str:
        if config.base_url:
            return f"{config.base_url}/auth/callback/{provider}"
        return str(request.url_for("auth_callback", provider=provider))

    @router.get("/auth/login")
    @router.get("/auth/login/{provider}")
    async def login(request: Request, provider: str | None = None) -> Any:
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
        user_store.get_or_create(
            uid, email=userinfo.get("email", ""), name=userinfo.get("name", ""),
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
            "storage_backend": user.storage_backend,
            "has_storage": user.has_storage,
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
        if backend not in USER_STORAGE_BACKENDS:
            raise HTTPException(
                400, f"backend must be one of {sorted(USER_STORAGE_BACKENDS)}",
            )
        config_part = dict(body.get("config", {}) or {})
        credentials = dict(body.get("credentials", {}) or {})

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
