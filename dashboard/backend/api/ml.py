from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..context import AppContext
from ..deps import current_user, get_ctx
from ..security import SessionUser
from ..services.readings_service import latest_reading

router = APIRouter(prefix="/api/v1/ml", tags=["ml"])


@router.get("/status")
def status(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    with ctx.db.session() as conn:
        return ctx.ml.status(conn)


@router.get("/evaluation")
def evaluation(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    return ctx.ml.evaluation()


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
