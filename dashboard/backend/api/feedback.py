from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..context import AppContext
from ..deps import csrf_user, current_user, get_ctx
from ..schemas import FeedbackIn
from ..security import SessionUser
from ..services.readings_service import latest_reading
from ..timeutil import parse_iso, to_iso, utc_now

router = APIRouter(prefix="/api/v1/feedback", tags=["feedback"])

MAX_CONTEXT_AGE_S = 120


@router.post("", status_code=201)
def submit(body: FeedbackIn, ctx: AppContext = Depends(get_ctx), user: SessionUser = Depends(csrf_user)):
    if not ctx.feedback_limiter.hit(user.username):
        raise HTTPException(status_code=429, detail="Too many ratings in a short time")

    now = utc_now()
    with ctx.db.transaction() as conn:
        reading = latest_reading(conn, body.device_id)
        if reading is None or not reading["valid"]:
            raise HTTPException(status_code=409, detail="No valid sensor reading to attach this rating to")
        age = (now - parse_iso(reading["received_at"])).total_seconds()
        if age > MAX_CONTEXT_AGE_S:
            raise HTTPException(status_code=409, detail="The latest reading is too old; check that the device is online")

        cur = conn.execute(
            "INSERT INTO comfort_feedback (created_at, user_id, rating, reading_id, device_id, temperature_c, "
            "humidity_pct, light_pct, motion_detected, context_age_s, context_simulated, note) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING id",
            (to_iso(now), user.user_id, body.rating, reading["id"], reading["device_id"], reading["temperature_c"],
             reading["humidity_pct"], reading["light_pct"],
             None if reading["motion_detected"] is None else int(reading["motion_detected"]),
             round(age, 1), int(reading["is_simulated"]), body.note),
        )
        feedback_id = cur.fetchone()[0]
    return {
        "id": feedback_id,
        "rating": body.rating,
        "reading_id": reading["id"],
        "context_simulated": reading["is_simulated"],
        "created_at": to_iso(now),
    }


@router.get("")
def recent(
    limit: int = Query(20, ge=1, le=200),
    ctx: AppContext = Depends(get_ctx),
    user: SessionUser = Depends(current_user),
):
    with ctx.db.session() as conn:
        if user.is_admin:
            rows = conn.execute(
                "SELECT f.*, u.username FROM comfort_feedback f LEFT JOIN users u ON u.id = f.user_id "
                "ORDER BY f.id DESC LIMIT ?", (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT f.*, u.username FROM comfort_feedback f LEFT JOIN users u ON u.id = f.user_id "
                "WHERE f.user_id = ? ORDER BY f.id DESC LIMIT ?", (user.user_id, limit)
            ).fetchall()
        total_usable = conn.execute(
            "SELECT COUNT(*) FROM comfort_feedback WHERE context_simulated = 0 AND temperature_c IS NOT NULL AND light_pct IS NOT NULL"
        ).fetchone()[0]
    items = [
        {
            "id": r["id"], "created_at": r["created_at"], "username": r["username"], "rating": r["rating"],
            "temperature_c": r["temperature_c"], "humidity_pct": r["humidity_pct"],
            "light_pct": r["light_pct"], "motion_detected": None if r["motion_detected"] is None else bool(r["motion_detected"]),
            "context_simulated": bool(r["context_simulated"]), "note": r["note"],
        }
        for r in rows
    ]
    return {"items": items, "usable_for_training": total_usable}
