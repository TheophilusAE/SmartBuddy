from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from .context import AppContext
from .security import CSRF_HEADER, SESSION_COOKIE, SessionUser, csrf_ok, load_session


def get_ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def current_user(request: Request, ctx: AppContext = Depends(get_ctx)) -> SessionUser:
    token = request.cookies.get(SESSION_COOKIE)
    with ctx.db.session() as conn:
        user = load_session(conn, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Not signed in")
    return user


def _check_origin(request: Request, ctx: AppContext) -> None:
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in ctx.settings.cors_origins:
        raise HTTPException(status_code=403, detail="Origin not allowed")


def csrf_user(request: Request, ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(current_user)) -> SessionUser:
    _check_origin(request, ctx)
    if not csrf_ok(user, request.headers.get(CSRF_HEADER)):
        raise HTTPException(status_code=403, detail="CSRF token missing or invalid")
    return user


def admin_user(user: SessionUser = Depends(csrf_user)) -> SessionUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user


def admin_reader(user: SessionUser = Depends(current_user)) -> SessionUser:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
