from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..context import AppContext
from ..deps import admin_reader, current_user, get_ctx
from ..security import SessionUser
from ..services import readings_service as rs
from ..services.export_service import iter_csv
from ..timeutil import parse_iso, to_epoch_ms, utc_now

router = APIRouter(prefix="/api/v1", tags=["readings"])

MAX_RANGE = timedelta(days=31)
DEFAULT_RANGE = timedelta(hours=24)
DEVICE_ID_PATTERN = r"^[a-z0-9-]{3,32}$"


def resolve_range(start: Optional[str], end: Optional[str]) -> tuple[datetime, datetime]:
    try:
        end_dt = parse_iso(end) if end else utc_now()
        start_dt = parse_iso(start) if start else end_dt - DEFAULT_RANGE
    except ValueError:
        raise HTTPException(status_code=422, detail="start/end must be ISO-8601 timestamps with a timezone")
    if start_dt >= end_dt:
        raise HTTPException(status_code=422, detail="start must be before end")
    if end_dt - start_dt > MAX_RANGE:
        raise HTTPException(status_code=422, detail="Range is limited to 31 days")
    return start_dt, end_dt


@router.get("/readings/latest")
def latest(
    device_id: Optional[str] = Query(None, pattern=DEVICE_ID_PATTERN),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    with ctx.db.session() as conn:
        reading = rs.latest_reading(conn, device_id)
    if reading is None:
        return {"reading": None, "age_s": None}
    age = (utc_now() - parse_iso(reading["received_at"])).total_seconds()
    return {"reading": reading, "age_s": round(age, 1)}


@router.get("/readings")
def list_readings(
    start: Optional[str] = Query(None, max_length=40),
    end: Optional[str] = Query(None, max_length=40),
    page: int = Query(1, ge=1, le=100000),
    page_size: int = Query(50, ge=1, le=500),
    include_simulated: bool = False,
    device_id: Optional[str] = Query(None, pattern=DEVICE_ID_PATTERN),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    s, e = resolve_range(start, end)
    with ctx.db.session() as conn:
        items, total = rs.query_readings(conn, to_epoch_ms(s), to_epoch_ms(e), include_simulated, device_id,
                                         page_size, (page - 1) * page_size)
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/readings/series")
def series(
    start: Optional[str] = Query(None, max_length=40),
    end: Optional[str] = Query(None, max_length=40),
    include_simulated: bool = False,
    device_id: Optional[str] = Query(None, pattern=DEVICE_ID_PATTERN),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(current_user),
):
    s, e = resolve_range(start, end)
    with ctx.db.session() as conn:
        data = rs.reading_series(conn, to_epoch_ms(s), to_epoch_ms(e), include_simulated, device_id)
    return data


@router.get("/readings/export.csv")
def export_csv(
    start: Optional[str] = Query(None, max_length=40),
    end: Optional[str] = Query(None, max_length=40),
    include_simulated: bool = False,
    device_id: Optional[str] = Query(None, pattern=DEVICE_ID_PATTERN),
    ctx: AppContext = Depends(get_ctx),
    _: SessionUser = Depends(admin_reader),
):
    s, e = resolve_range(start, end)

    def generate():
        with ctx.db.session() as conn:
            yield from iter_csv(conn, to_epoch_ms(s), to_epoch_ms(e), include_simulated, device_id)

    filename = f"smartbuddy_readings_{s.strftime('%Y%m%d%H%M')}_{e.strftime('%Y%m%d%H%M')}.csv"
    return StreamingResponse(
        generate(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/stats")
def stats(ctx: AppContext = Depends(get_ctx), _: SessionUser = Depends(current_user)):
    with ctx.db.session() as conn:
        return rs.collection_stats(conn)
