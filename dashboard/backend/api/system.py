from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from ..automation import mode_allowed
from ..context import AppContext
from ..deps import admin_user, current_user, get_ctx
from ..schemas import ModeIn, OperatingMode
from ..security import SessionUser
from ..timeutil import to_epoch_ms, utc_now

router = APIRouter(prefix="/api/v1", tags=["system"])

GAS_DISCLAIMER = (
    "Gas/smoke indication comes from an uncalibrated MQ-2 module (raw ADC counts, not ppm). "
    "It is not a certified smoke or gas detector and must not be relied on for safety."
)


@router.get("/health")
def health():
    return {"status": "ok", "server_time_ms": to_epoch_ms(utc_now())}


@router.get("/ready")
def ready(ctx: AppContext = Depends(get_ctx)):
    if ctx.db.ping():
        return {"status": "ready"}
    return JSONResponse({"status": "not_ready"}, status_code=503)


@router.get("/mode")
def get_mode(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    with ctx.db.session() as conn:
        mode = ctx.get_mode(conn)
    return {
        "mode": mode.value,
        "ml_automatic_enabled": ctx.settings.enable_ml_automatic,
        "device_control_enabled": ctx.settings.device_control_enabled,
        "model_available": ctx.ml.model_available,
        "forecast_available": ctx.ml.get_forecast_model() is not None,
    }


@router.put("/mode")
def put_mode(body: ModeIn, ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(admin_user)):
    mode = OperatingMode(body.mode)
    # monitor-only still allows the ML modes: ML_AUTOMATIC only steers the fan via the forecast lease
    if not ctx.settings.device_control_enabled and mode not in (OperatingMode.ML_RECOMMENDATION,
                                                                OperatingMode.ML_AUTOMATIC):
        raise HTTPException(status_code=409, detail="Monitor-only: the firmware's own rules control the outputs")
    problem = mode_allowed(mode, ctx.settings, ctx.ml.get_forecast_model() is not None)
    if problem:
        raise HTTPException(status_code=409, detail=problem)
    with ctx.db.transaction() as conn:
        ctx.set_mode(conn, mode, user.username)
    ctx.hub.publish("mode", {"mode": mode.value})
    return {"mode": mode.value}


@router.get("/warnings")
def warnings(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    return {"warnings": ctx.gas.warnings(), "disclaimer": GAS_DISCLAIMER}
