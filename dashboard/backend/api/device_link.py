from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .. import device_gateway as gw
from ..context import AppContext
from ..deps import client_ip, get_ctx
from ..schemas import AckIn, ReadingIn
from ..services.pipeline import ingest_reading
from ..services.readings_service import record_rejection
from ..timeutil import to_epoch_ms, utc_now

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/device", tags=["device"])


def _reject(ctx: AppContext, reason: str, device_id: str | None) -> None:
    try:
        with ctx.db.transaction() as conn:
            record_rejection(conn, reason, device_id, utc_now())
    except Exception:
        log.exception("could not record ingest rejection")


async def _identify(request: Request, ctx: AppContext) -> gw.DeviceIdentity:
    identity = gw.authenticate_device(ctx.settings, request.headers.get("authorization"))
    if identity is None:
        ip = client_ip(request)
        if ctx.unauth_device_limiter.hit(ip):
            await run_in_threadpool(_reject, ctx, "unauthorized", None)
            raise HTTPException(status_code=401, detail="Unauthorized")
        raise HTTPException(status_code=429, detail="Too many requests")
    if not ctx.device_limiter.hit(identity.device_id):
        await run_in_threadpool(_reject, ctx, "rate_limited", identity.device_id)
        raise HTTPException(status_code=429, detail="Too many requests")
    return identity


def _summarise(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}:{e['type']}" for e in exc.errors()[:5])


@router.post("/readings")
async def post_reading(request: Request, ctx: AppContext = Depends(get_ctx)):
    received = utc_now()
    identity = await _identify(request, ctx)
    raw = await request.body()
    try:
        reading = ReadingIn.model_validate_json(raw)
    except ValidationError as exc:
        log.info("rejected reading from %s: %s", identity.device_id, _summarise(exc))
        await run_in_threadpool(_reject, ctx, "invalid", identity.device_id)
        raise HTTPException(status_code=422, detail="Invalid payload")

    expected_source = "simulator" if identity.simulated else "device"
    if reading.device_id != identity.device_id or reading.source != expected_source:
        await run_in_threadpool(_reject, ctx, "unauthorized", identity.device_id)
        raise HTTPException(status_code=403, detail="Forbidden")

    result = await run_in_threadpool(ingest_reading, ctx, reading, identity, received)
    server_time = to_epoch_ms(utc_now())
    if result.status == "duplicate":
        return JSONResponse({"status": "duplicate", "server_time_ms": server_time}, status_code=200)
    return JSONResponse(
        {"status": "stored", "reading_id": result.reading_id, "valid": result.valid, "server_time_ms": server_time},
        status_code=201,
    )


def _poll(ctx: AppContext, identity: gw.DeviceIdentity):
    now = utc_now()
    with ctx.db.transaction() as conn:
        was_online = gw.is_online(conn, ctx.settings, identity.device_id, now)
        gw.touch_device(conn, identity, now)
        commands = gw.take_pending(conn, identity.device_id, now)
        events = [gw.get_event(conn, c["id"]) for c in commands]
        states = gw.device_states(conn, ctx.settings, now) if not was_online or commands else []
    for state in states:
        if state["device_id"] == identity.device_id:
            ctx.hub.publish("device_state", state)
    for event in events:
        if event:
            ctx.hub.publish("command_update", event)
    return commands


@router.get("/commands")
async def get_commands(request: Request, ctx: AppContext = Depends(get_ctx)):
    identity = await _identify(request, ctx)
    commands = await run_in_threadpool(_poll, ctx, identity)
    return {"server_time_ms": to_epoch_ms(utc_now()), "commands": commands}


def _ack(ctx: AppContext, identity: gw.DeviceIdentity, ack: AckIn):
    now = utc_now()
    with ctx.db.transaction() as conn:
        gw.touch_device(conn, identity, now)
        event = gw.record_ack(conn, identity.device_id, ack.command_id, ack.result, ack.reason,
                              ack.observed.model_dump(), now)
        states = gw.device_states(conn, ctx.settings, now) if event else []
    if event:
        ctx.hub.publish("command_update", event)
        for state in states:
            if state["device_id"] == identity.device_id:
                ctx.hub.publish("device_state", state)
    return event


@router.post("/acks")
async def post_ack(request: Request, ctx: AppContext = Depends(get_ctx)):
    identity = await _identify(request, ctx)
    raw = await request.body()
    try:
        ack = AckIn.model_validate_json(raw)
    except ValidationError as exc:
        log.info("rejected ack from %s: %s", identity.device_id, _summarise(exc))
        await run_in_threadpool(_reject, ctx, "invalid", identity.device_id)
        raise HTTPException(status_code=422, detail="Invalid payload")
    if ack.device_id != identity.device_id:
        raise HTTPException(status_code=403, detail="Forbidden")

    event = await run_in_threadpool(_ack, ctx, identity, ack)
    if event is None:
        raise HTTPException(status_code=404, detail="Unknown command")
    return {"status": "ok", "server_time_ms": to_epoch_ms(utc_now())}
