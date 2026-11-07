from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from .. import device_gateway as gw
from ..context import AppContext
from ..deps import admin_user, current_user, get_ctx
from ..safety import check_command
from ..schemas import CommandIn, DeviceOnlyIn, OperatingMode
from ..security import SessionUser
from ..timeutil import utc_now

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


MONITOR_ONLY = (
    "This firmware runs its own fan/LED/buzzer rules and can't receive commands. "
    "The dashboard is in monitor-only mode (DEVICE_CONTROL_ENABLED=false)."
)


def _require_control(ctx: AppContext) -> None:
    if not ctx.settings.device_control_enabled:
        raise HTTPException(status_code=409, detail=MONITOR_ONLY)


def _known(conn, device_id: str) -> bool:
    return conn.execute("SELECT 1 FROM device_status WHERE device_id = ?", (device_id,)).fetchone() is not None


@router.get("/state")
def state(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    with ctx.db.session() as conn:
        devices = gw.device_states(conn, ctx.settings, utc_now())
        mode = ctx.get_mode(conn)
    return {
        "devices": devices,
        "mode": mode.value,
        "warnings": ctx.gas.warnings(),
        "device_control_enabled": ctx.settings.device_control_enabled,
    }


@router.get("/commands")
def commands(
    device_id: Optional[str] = Query(None, pattern=r"^[a-z0-9-]{3,32}$"),
    limit: int = Query(20, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    with ctx.db.session() as conn:
        return {"items": gw.recent_events(conn, device_id, limit)}


@router.get("/commands/{command_id}")
def command(
    command_id: int = Path(ge=1, le=2**53),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    with ctx.db.session() as conn:
        event = gw.get_event(conn, command_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Unknown command")
    return event


@router.post("/commands", status_code=202)
def send_command(body: CommandIn, ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(admin_user)):
    _require_control(ctx)
    if not ctx.command_limiter.hit(user.username):
        raise HTTPException(status_code=429, detail="Too many commands, slow down")

    now = utc_now()
    with ctx.db.transaction() as conn:
        if not _known(conn, body.device_id):
            raise HTTPException(status_code=404, detail="Unknown device")
        if not gw.is_online(conn, ctx.settings, body.device_id, now):
            raise HTTPException(status_code=409, detail="Device is offline; command not queued")
        blocked = check_command(body.target, body.state, "user", ctx.gas.is_active(body.device_id),
                                body.acknowledge_gas_warning)
        if blocked:
            raise HTTPException(status_code=409, detail=blocked)
        event = gw.queue_command(conn, ctx.settings, body.device_id, body.target, body.state, "user",
                                 requested_by=user.username)
    ctx.automation.mark_manual_override(body.device_id, [body.target])
    ctx.hub.publish("command_update", event)
    log.info("user %s queued %s=%s for %s", user.username, body.target, body.state, body.device_id)
    return event


@router.post("/emergency-stop", status_code=202)
def emergency_stop(body: DeviceOnlyIn, ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(admin_user)):
    _require_control(ctx)
    with ctx.db.transaction() as conn:
        if not _known(conn, body.device_id):
            raise HTTPException(status_code=404, detail="Unknown device")
        event = gw.queue_command(conn, ctx.settings, body.device_id, "all", "off", "user",
                                 requested_by=user.username, reason="emergency stop")
        ctx.set_mode(conn, OperatingMode.MANUAL, user.username)
    ctx.hub.publish("command_update", event)
    ctx.hub.publish("mode", {"mode": OperatingMode.MANUAL.value})
    log.warning("emergency stop by %s for %s", user.username, body.device_id)
    return event


@router.post("/alarm/mute", status_code=202)
def mute_alarm(body: DeviceOnlyIn, ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(admin_user)):
    _require_control(ctx)
    with ctx.db.transaction() as conn:
        if not _known(conn, body.device_id):
            raise HTTPException(status_code=404, detail="Unknown device")
        if not gw.is_online(conn, ctx.settings, body.device_id, utc_now()):
            raise HTTPException(status_code=409, detail="Device is offline")
        event = gw.queue_command(conn, ctx.settings, body.device_id, "alarm", "mute", "user",
                                 requested_by=user.username, reason="mute local gas buzzer")
    ctx.hub.publish("command_update", event)
    return event
