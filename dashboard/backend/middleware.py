from __future__ import annotations

import json
from typing import Callable, Optional

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; "
    "frame-ancestors 'none'"
)

SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"no-referrer"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=()"),
    (b"cross-origin-opener-policy", b"same-origin"),
    (b"content-security-policy", CSP.encode()),
]


async def _send_json(send, status: int, body: dict) -> None:
    payload = json.dumps(body).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(payload)).encode()),
                    *SECURITY_HEADERS],
    })
    await send({"type": "http.response.body", "body": payload})


class BodyLimitMiddleware:
    def __init__(self, app, default_limit: int, device_limit: int, on_too_large: Optional[Callable[[str], None]] = None):
        self.app = app
        self.default_limit = default_limit
        self.device_limit = device_limit
        self.on_too_large = on_too_large

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        limit = self.device_limit if path.startswith("/api/v1/device/") else self.default_limit

        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    if int(value) > limit:
                        return await self._reject(path, send)
                except ValueError:
                    return await _send_json(send, 400, {"detail": "Bad Content-Length"})

        if scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)

        body = b""
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body += message.get("body", b"")
            if len(body) > limit:
                return await self._reject(path, send)
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay, send)

    async def _reject(self, path: str, send) -> None:
        if self.on_too_large:
            self.on_too_large(path)
        await _send_json(send, 413, {"detail": "Payload too large"})


LOOPBACK = {"127.0.0.1", "::1", "localhost"}
LAN_ALLOWED_PREFIXES = ("/api/v1/device/", "/api/v1/health")


class LanGuardMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        client = scope.get("client")
        host = client[0] if client else ""
        device_call = scope["type"] == "http" and scope.get("path", "").startswith(LAN_ALLOWED_PREFIXES)
        if host in LOOPBACK or device_call:
            return await self.app(scope, receive, send)
        if scope["type"] == "websocket":
            return await send({"type": "websocket.close", "code": 4403})
        await _send_json(send, 403, {"detail": "Forbidden"})


HSTS = (b"strict-transport-security", b"max-age=31536000")


class SecurityHeadersMiddleware:
    def __init__(self, app, hsts: bool = False):
        self.app = app
        self.extra = [HSTS] if hsts else []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        is_api = scope.get("path", "").startswith("/api/")

        async def wrapped(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                for k, v in [*SECURITY_HEADERS, *self.extra]:
                    if k not in existing:
                        headers.append((k, v))
                if is_api and b"cache-control" not in existing:
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, wrapped)
