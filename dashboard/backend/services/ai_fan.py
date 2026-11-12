from __future__ import annotations

import logging
import threading
import time
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from typing import Any, Optional

from ..config import Settings
from ..schemas import OperatingMode
from ..timeutil import from_epoch_ms, parse_iso, to_epoch_ms, to_iso, utc_now

log = logging.getLogger(__name__)

STEP_S = 30
MAX_HISTORY_H = 24
ACTUAL_WINDOW_MS = 30_000


def decide(now_c: float, predicted_c: float, previous: Optional[str], on_c: float, off_c: float) -> str:
    # forecast leads, but the fan never goes off while the room is already above the on threshold
    if predicted_c >= on_c or now_c >= on_c:
        return "on"
    if predicted_c <= off_c:
        return "off"
    return previous or "off"


@dataclass
class _DeviceState:
    decision: Optional[str] = None
    computed_at: float = float("-inf")


class AiFan:
    def __init__(self, settings: Settings, ml, db):
        self.s = settings
        self.ml = ml
        self.db = db
        self._lock = threading.Lock()
        self._states: dict[str, _DeviceState] = {}

    def active(self, mode: OperatingMode) -> bool:
        return mode == OperatingMode.ML_AUTOMATIC and self.s.enable_ml_automatic

    def step(self, row: dict[str, Any], mode: OperatingMode, gas_active: bool) -> Optional[str]:
        if row.get("is_simulated") or not row.get("valid"):
            return None
        device_id = row["device_id"]
        fan_on = bool((row.get("actuators") or {}).get("fan"))
        with self._lock:
            st = self._states.setdefault(device_id, _DeviceState())
            if time.monotonic() - st.computed_at >= STEP_S:
                st.computed_at = time.monotonic()
                try:
                    st.decision = self._compute(device_id, mode, st.decision, fan_on)
                except Exception as exc:
                    log.warning("ai fan step failed: %s", type(exc).__name__)
                    st.decision = None
            decision = st.decision
        if not self.active(mode) or decision is None:
            return None
        if gas_active and decision == "on" and not fan_on:
            # a gas warning must never start the fan, so hold it off
            return "off"
        return decision

    def _compute(self, device_id: str, mode: OperatingMode, previous: Optional[str], fan_on: bool) -> Optional[str]:
        model = self.ml.get_forecast_model()
        if model is None:
            return None
        from ml.forecast import latest_features

        with self.db.session() as conn:
            feats = latest_features(conn, device_id)
        if feats is None:
            return None
        try:
            pred = model.predict(feats)
        except ValueError:
            return None
        t_pred = pred.get("temperature_c")
        if t_pred is None:
            return None
        now_c = feats["temperature_c"]
        if previous is None:
            previous = "on" if fan_on else "off"
        decision = decide(now_c, t_pred, previous, self.s.fan_on_temp_c, self.s.fan_off_temp_c)

        horizon = int(model.metadata.get("horizon_min") or 0)
        based_on = to_epoch_ms(parse_iso(feats["at"]))
        with self.db.transaction() as conn:
            conn.execute(
                "INSERT INTO forecast_log (created_at, device_id, model_version, horizon_min, based_on_ms, target_ms, "
                "temperature_now, predicted_temperature_c, predicted_humidity_pct, fan_decision, mode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (to_iso(utc_now()), device_id, model.version, horizon, based_on, based_on + horizon * 60_000,
                 round(now_c, 2), t_pred, pred.get("humidity_pct"), decision, mode.value),
            )
        return decision


def history(conn, hours: float, device_id: Optional[str], now_ms: Optional[int] = None) -> dict[str, Any]:
    now_ms = now_ms or to_epoch_ms(utc_now())
    start = now_ms - int(min(hours, MAX_HISTORY_H) * 3_600_000)
    dev_sql, dev_args = ("", ()) if device_id is None else (" AND device_id = ?", (device_id,))
    logs = conn.execute(
        "SELECT based_on_ms, target_ms, horizon_min, model_version, temperature_now, predicted_temperature_c, "
        f"fan_decision, mode FROM forecast_log WHERE based_on_ms >= ?{dev_sql} ORDER BY based_on_ms",
        (start, *dev_args),
    ).fetchall()
    readings = conn.execute(
        "SELECT measured_ms, temperature_c, fan_on, fan_control FROM sensor_readings WHERE is_simulated = 0 "
        f"AND valid = 1 AND measured_ms >= ?{dev_sql} ORDER BY measured_ms",
        (start, *dev_args),
    ).fetchall()

    times = [r["measured_ms"] for r in readings]
    points = []
    for lg in logs:
        lo = bisect_left(times, lg["target_ms"] - ACTUAL_WINDOW_MS)
        hi = bisect_right(times, lg["target_ms"] + ACTUAL_WINDOW_MS)
        temps = [readings[i]["temperature_c"] for i in range(lo, hi)]
        actual = round(sum(temps) / len(temps), 2) if temps and lg["target_ms"] <= now_ms else None
        points.append({
            "made_at": _iso_ms(lg["based_on_ms"]),
            "target_at": _iso_ms(lg["target_ms"]),
            "now": lg["temperature_now"],
            "predicted": lg["predicted_temperature_c"],
            "actual": actual,
            "decision": lg["fan_decision"],
            "mode": lg["mode"],
            "model_version": lg["model_version"],
        })

    # one fan sample per 30 s keeps the payload small
    fan = []
    bucket = None
    for r in readings:
        b = r["measured_ms"] // (STEP_S * 1000)
        if b == bucket:
            continue
        bucket = b
        fan.append({"at": _iso_ms(r["measured_ms"]), "temperature": r["temperature_c"], "on": bool(r["fan_on"]),
                    "control": r["fan_control"]})

    scored = [p for p in points if p["actual"] is not None and p["predicted"] is not None]
    summary = None
    if scored:
        summary = {
            "scored": len(scored),
            "mae": round(sum(abs(p["predicted"] - p["actual"]) for p in scored) / len(scored), 3),
            "mae_no_change": round(sum(abs(p["now"] - p["actual"]) for p in scored) / len(scored), 3),
        }
    return {
        "hours": min(hours, MAX_HISTORY_H),
        "horizon_min": logs[-1]["horizon_min"] if logs else None,
        "points": points,
        "fan": fan,
        "summary": summary,
    }


def _iso_ms(ms: int) -> str:
    return to_iso(from_epoch_ms(ms))
