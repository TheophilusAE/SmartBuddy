from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
if str(DASHBOARD_DIR) not in sys.path:
    sys.path.insert(0, str(DASHBOARD_DIR))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.exceptions import HTTPException as StarletteHTTPException  # noqa: E402

from . import device_gateway as gw  # noqa: E402
from .api import auth, device_link, devices, feedback, ml, readings, system  # noqa: E402
from .config import Settings, load_settings  # noqa: E402
from .context import AppContext  # noqa: E402
from .middleware import BodyLimitMiddleware, LanGuardMiddleware, SecurityHeadersMiddleware  # noqa: E402
from .security import SESSION_COOKIE, load_session, purge_sessions  # noqa: E402
from .services.readings_service import record_rejection  # noqa: E402
from .timeutil import to_iso, utc_now  # noqa: E402

log = logging.getLogger("smartbuddy")


def _bootstrap_users(ctx: AppContext) -> None:
    s = ctx.settings
    accounts = [(s.admin_username, s.admin_password_hash, "admin")]
    if s.viewer_username and s.viewer_password_hash:
        accounts.append((s.viewer_username, s.viewer_password_hash, "viewer"))
    with ctx.db.transaction() as conn:
        for username, pw_hash, role in accounts:
            if not pw_hash:
                log.warning("%s account has no password hash configured - it cannot sign in. "
                            "Run scripts/hash_password.py and set it in dashboard/.env", role)
                continue
            if not pw_hash.startswith("scrypt$"):
                log.error("%s password hash is not in the expected format - ignoring it", role)
                continue
            conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(username) DO UPDATE SET password_hash = excluded.password_hash, role = excluded.role",
                (username, pw_hash, role, to_iso(utc_now())),
            )


def _housekeeping_tick(ctx: AppContext, purge: bool):
    now = utc_now()
    with ctx.db.transaction() as conn:
        expired = gw.expire_overdue(conn, now)
        states = gw.device_states(conn, ctx.settings, now)
        if purge:
            purge_sessions(conn)
    return expired, states


async def _housekeeping(ctx: AppContext) -> None:
    online: dict[str, bool] = {}
    ticks = 0
    while True:
        await asyncio.sleep(2)
        ticks += 1
        try:
            # in a thread so a slow cloud database doesn't freeze the event loop
            expired, states = await asyncio.to_thread(_housekeeping_tick, ctx, ticks % 1800 == 0)
            for event in expired:
                ctx.hub.publish("command_update", event)
            for st in states:
                if online.get(st["device_id"]) != st["online"]:
                    online[st["device_id"]] = st["online"]
                    ctx.hub.publish("device_state", st)
                    if not st["online"]:
                        log.info("device %s is offline", st["device_id"])
        except Exception:
            log.exception("housekeeping failed")


def _ws_user(ctx: AppContext, token: str | None):
    with ctx.db.session() as conn:
        return load_session(conn, token)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    ctx = AppContext.build(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        version = await asyncio.to_thread(ctx.db.init)
        log.info("database ready (%s, schema v%d)", ctx.db.dialect, version)
        await asyncio.to_thread(_bootstrap_users, ctx)
        if not settings.device_keys:
            log.warning("DEVICE_KEYS is empty - no device can send readings")
        if settings.allow_simulator:
            log.warning("simulator keys are enabled; simulated readings are labelled and excluded from real counts")
        ctx.hub.bind_loop(asyncio.get_running_loop())
        task = asyncio.create_task(_housekeeping(ctx))
        try:
            yield
        finally:
            task.cancel()
            ctx.db.close()

    dev = settings.is_development
    app = FastAPI(
        title="SmartBuddy API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/api/docs" if dev else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if dev else None,
    )
    app.state.ctx = ctx

    def on_too_large(path: str) -> None:
        if path.startswith("/api/v1/device/"):
            try:
                with ctx.db.transaction() as conn:
                    record_rejection(conn, "too_large", None, utc_now())
            except Exception:
                log.exception("could not record oversize request")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        max_age=600,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)
    app.add_middleware(BodyLimitMiddleware, default_limit=16 * 1024, device_limit=2048, on_too_large=on_too_large)
    if not settings.is_loopback_only and settings.lan_device_only:
        app.add_middleware(LanGuardMiddleware)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"loc": [str(p) for p in e.get("loc", [])], "msg": e.get("msg", "invalid")} for e in exc.errors()[:10]]
        return JSONResponse({"detail": "Invalid request", "errors": errors}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    for module in (system, auth, readings, devices, feedback, ml, device_link):
        app.include_router(module.router)

    @app.websocket("/ws/live")
    async def live(ws: WebSocket):
        origin = (ws.headers.get("origin") or "").rstrip("/")
        if origin not in settings.cors_origins:
            await ws.close(code=4403)
            return
        user = await asyncio.to_thread(_ws_user, ctx, ws.cookies.get(SESSION_COOKIE))
        if user is None:
            await ws.close(code=4401)
            return
        if not ctx.hub.can_accept():
            await ws.close(code=4429)
            return

        await ws.accept()
        ctx.hub.add(ws)
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_text("pong")
        except WebSocketDisconnect:
            pass
        except Exception:
            log.debug("websocket closed with error", exc_info=True)
        finally:
            ctx.hub.remove(ws)

    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    dist = settings.frontend_dist
    index = dist / "index.html"
    if not index.is_file():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        if path.startswith(("api/", "ws/")):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = dist / path
        if path and "/" not in path and "\\" not in path and candidate.is_file() and candidate.resolve().parent == dist.resolve():
            return FileResponse(candidate)
        return FileResponse(index)


def _configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


try:
    app = create_app()
except Exception as exc:
    _configure_logging()
    log.error("could not start: %s", exc)
    raise


if __name__ == "__main__":
    import uvicorn

    _configure_logging()
    s = app.state.ctx.settings
    if s.on_render:
        log.info("running on Render, public HTTPS site: %s", ", ".join(o for o in s.cors_origins if o.startswith("https")))
    elif not s.is_loopback_only:
        scope = "device endpoints only" if s.lan_device_only else "ALL endpoints (LAN_DEVICE_ONLY=false)"
        log.warning("listening on %s - other machines on your network can reach the %s. "
                    "Allow the port in the firewall for private networks only.", s.host, scope)
    uvicorn.run(app, host=s.host, port=s.port, log_level="info", proxy_headers=False, server_header=False)
