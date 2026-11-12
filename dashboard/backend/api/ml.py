from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import AppContext
from ..deps import admin_user, current_user, get_ctx
from ..security import SessionUser
from ..services.ai_fan import history
from ..services.ml_service import TrainingBusy
from ..services.readings_service import latest_reading

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get("/status")
def status(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    with ctx.db.session() as conn:
        return ctx.ml.status(conn)


@router.get("/evaluation")
def evaluation(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    with ctx.db.session() as conn:
        return ctx.ml.evaluation(conn)


@router.post("/train")
def train(ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(admin_user)):
    if not ctx.train_limiter.hit(user.username):
        raise HTTPException(status_code=429, detail="Training was started too often, wait a few minutes")
    try:
        return ctx.ml.train_now()
    except TrainingBusy:
        raise HTTPException(status_code=409, detail="Training is already running")


@router.get("/forecast")
def forecast(
    device_id: Optional[str] = Query(None, pattern=r"^[a-z0-9-]{3,32}$"),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    return ctx.ml.forecast(device_id)


@router.get("/forecast/history")
def forecast_history(
    hours: float = Query(6, gt=0, le=24),
    device_id: Optional[str] = Query(None, pattern=r"^[a-z0-9-]{3,32}$"),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    with ctx.db.session() as conn:
        return history(conn, hours, device_id)


@router.post("/forecast/train")
def train_forecast(
    horizon: int = Query(5),
    ctx: AppContext = Depends(get_ctx),
    user: SessionUser = Depends(admin_user),
):
    if horizon not in (5, 10, 15, 30):
        raise HTTPException(status_code=422, detail="horizon must be 5, 10, 15 or 30 minutes")
    if not ctx.train_limiter.hit(user.username):
        raise HTTPException(status_code=429, detail="Training was started too often, wait a few minutes")
    try:
        return ctx.ml.train_forecast_now(horizon)
    except TrainingBusy:
        raise HTTPException(status_code=409, detail="Training is already running")


@router.get("/advice")
def advice(
    device_id: Optional[str] = Query(None, pattern=r"^[a-z0-9-]{3,32}$"),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    with ctx.db.session() as conn:
        reading = latest_reading(conn, device_id)
    if reading is not None and not reading["valid"]:
        return {"available": False, "reason": "Latest reading is incomplete (a sensor reported an error)"}
    return ctx.ml.advise(reading)
