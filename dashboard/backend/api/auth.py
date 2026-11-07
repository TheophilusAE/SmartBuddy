from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool

from ..context import AppContext
from ..deps import client_ip, csrf_user, current_user, get_ctx
from ..schemas import LoginIn
from ..security import (
    SESSION_COOKIE, SessionUser, create_session, revoke_session, verify_password_or_dummy,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _set_cookie(response: Response, ctx: AppContext, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(ctx.settings.session_hours * 3600),
        httponly=True,
        secure=ctx.settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def _check_credentials(ctx: AppContext, username: str, password: str):
    with ctx.db.session() as conn:
        row = conn.execute(
            "SELECT id, username, role, password_hash FROM users WHERE username = ?", (username,)
        ).fetchone()
    ok = verify_password_or_dummy(password, row["password_hash"] if row else None)
    return row if ok else None


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, ctx: AppContext = Depends(get_ctx)):
    ip = client_ip(request)
    user_key = f"{ip}|{body.username.lower()}"
    if ctx.login_user_limiter.blocked(user_key) or not ctx.login_ip_limiter.hit(ip):
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again in a few minutes.")

    row = await run_in_threadpool(_check_credentials, ctx, body.username, body.password)
    if row is None:
        ctx.login_user_limiter.hit(user_key)
        log.info("failed login for a user from %s", ip)
        raise HTTPException(status_code=401, detail="Invalid username or password")

    ctx.login_user_limiter.reset(user_key)
    with ctx.db.transaction() as conn:
        token, csrf = create_session(conn, row["id"], ctx.settings.session_hours)
    _set_cookie(response, ctx, token)
    log.info("user %s signed in", row["username"])
    return {"user": {"username": row["username"], "role": row["role"]}, "csrf_token": csrf}


@router.post("/logout")
def logout(response: Response, user: SessionUser = Depends(csrf_user), ctx: AppContext = Depends(get_ctx)):
    with ctx.db.transaction() as conn:
        revoke_session(conn, user.session_id)
    response.delete_cookie(SESSION_COOKIE, path="/", samesite="strict", httponly=True,
                           secure=ctx.settings.cookie_secure)
    return {"status": "signed_out"}


@router.get("/me")
def me(user: SessionUser = Depends(current_user)):
    return {"user": {"username": user.username, "role": user.role}, "csrf_token": user.csrf_token}
