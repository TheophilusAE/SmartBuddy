from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from ..schemas import ReadingIn
from ..timeutil import parse_iso, to_epoch_ms, to_iso

READING_COLUMNS = (
    "id, device_id, boot_id, sequence, measured_at, measured_ms, device_timestamp, received_at, "
    "timestamp_trusted, uptime_ms, temperature_c, humidity_pct, light_pct, ldr_raw, motion_detected, gas_adc, "
    "gas_warning_local, dht_status, ldr_status, pir_status, mq2_status, fan_on, light_on, buzzer_on, "
    "valid, out_of_order, is_simulated, rain_raw, rain_filtered, rain_status, window_state, servo_angle, window_auto"
)


@dataclass
class StoreResult:
    status: str
    reading_id: Optional[int] = None
    valid: bool = False
    row: Optional[dict[str, Any]] = None


def _opt_bool(v: Any) -> Optional[bool]:
    return None if v is None else bool(v)


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "sequence": row["sequence"],
        "measured_at": row["measured_at"],
        "received_at": row["received_at"],
        "timestamp_trusted": bool(row["timestamp_trusted"]),
        "temperature_c": row["temperature_c"],
        "humidity_pct": row["humidity_pct"],
        "light_pct": row["light_pct"],
        "ldr_raw": row["ldr_raw"],
        "motion_detected": _opt_bool(row["motion_detected"]),
        "gas_adc": row["gas_adc"],
        "gas_warning_local": bool(row["gas_warning_local"]),
        "sensor_status": {
            "dht": row["dht_status"],
            "ldr": row["ldr_status"] or "error",
            "pir": row["pir_status"],
            "mq2": row["mq2_status"],
        },
        "actuators": {
            "fan": _opt_bool(row["fan_on"]),
            "light": _opt_bool(row["light_on"]),
            "buzzer": _opt_bool(row["buzzer_on"]),
        },
        "valid": bool(row["valid"]),
        "out_of_order": bool(row["out_of_order"]),
        "is_simulated": bool(row["is_simulated"]),
        "rain_raw": row["rain_raw"],
        "rain_filtered": row["rain_filtered"],
        "rain_status": row["rain_status"],
        "window_state": row["window_state"],
        "servo_angle": row["servo_angle"],
        "window_auto": _opt_bool(row["window_auto"]),
    }


def store_reading(
    conn: sqlite3.Connection,
    reading: ReadingIn,
    simulated: bool,
    received: datetime,
    max_skew_s: float,
) -> StoreResult:
    measured = received
    trusted = False
    if reading.timestamp is not None:
        device_time = parse_iso(reading.timestamp)
        if abs((device_time - received).total_seconds()) <= max_skew_s:
            measured = device_time
            trusted = True

    last = conn.execute(
        "SELECT MAX(sequence) AS s FROM sensor_readings WHERE device_id = ? AND boot_id = ?",
        (reading.device_id, reading.boot_id),
    ).fetchone()["s"]
    out_of_order = last is not None and reading.sequence < last

    valid = None not in (reading.temperature_c, reading.humidity_pct, reading.light_pct)
    st = reading.sensor_status
    act = reading.actuators

    cur = conn.execute(
        "INSERT INTO sensor_readings (device_id, boot_id, sequence, measured_at, measured_ms, device_timestamp, "
        "received_at, timestamp_trusted, uptime_ms, temperature_c, humidity_pct, light_pct, ldr_raw, motion_detected, "
        "gas_adc, gas_warning_local, dht_status, ldr_status, pir_status, mq2_status, fan_on, light_on, "
        "buzzer_on, valid, out_of_order, is_simulated, rain_raw, rain_filtered, rain_status, window_state, "
        "servo_angle, window_auto) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        f"ON CONFLICT (device_id, boot_id, sequence) DO NOTHING RETURNING {READING_COLUMNS}",
        (
            reading.device_id, reading.boot_id, reading.sequence, to_iso(measured), to_epoch_ms(measured),
            reading.timestamp, to_iso(received), int(trusted), reading.uptime_ms,
            reading.temperature_c, reading.humidity_pct, reading.light_pct, reading.ldr_raw,
            None if reading.motion_detected is None else int(reading.motion_detected),
            reading.gas_adc, int(reading.gas_warning_local),
            st.dht, st.ldr, st.pir, st.mq2,
            int(act.fan), int(act.light), int(act.buzzer),
            int(valid), int(out_of_order), int(simulated),
            reading.rain_raw, reading.rain_filtered, reading.rain_status, reading.window_state,
            reading.servo_angle, None if reading.window_auto is None else int(reading.window_auto),
        ),
    )
    row = cur.fetchone()
    if row is None:
        return StoreResult(status="duplicate")

    reading_id = row["id"]
    now_iso = to_iso(received)
    conn.execute(
        "INSERT INTO device_status (device_id, is_simulated, last_seen_at, last_boot_id, fan_on, light_on, "
        "buzzer_on, gas_warning_local, state_reported_at, rain_status, rain_changed_at, window_state, "
        "window_changed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET is_simulated = excluded.is_simulated, "
        "last_seen_at = excluded.last_seen_at, last_boot_id = excluded.last_boot_id, fan_on = excluded.fan_on, "
        "light_on = excluded.light_on, buzzer_on = excluded.buzzer_on, "
        "gas_warning_local = excluded.gas_warning_local, state_reported_at = excluded.state_reported_at, "
        "rain_changed_at = CASE WHEN excluded.rain_status IS NOT DISTINCT FROM device_status.rain_status "
        "THEN device_status.rain_changed_at ELSE excluded.state_reported_at END, "
        "rain_status = excluded.rain_status, "
        "window_changed_at = CASE WHEN excluded.window_state IS NOT DISTINCT FROM device_status.window_state "
        "THEN device_status.window_changed_at ELSE excluded.state_reported_at END, "
        "window_state = excluded.window_state",
        (reading.device_id, int(simulated), now_iso, reading.boot_id, int(act.fan), int(act.light),
         int(act.buzzer), int(reading.gas_warning_local), now_iso,
         reading.rain_status, now_iso if reading.rain_status else None,
         reading.window_state, now_iso if reading.window_state else None),
    )
    return StoreResult(status="stored", reading_id=reading_id, valid=valid, row=row_to_dict(row))


def record_rejection(conn: sqlite3.Connection, reason: str, device_id: Optional[str], when: datetime) -> None:
    conn.execute(
        "INSERT INTO ingest_rejections (received_at, device_id, reason) VALUES (?, ?, ?)",
        (to_iso(when), device_id, reason),
    )


def latest_reading(conn: sqlite3.Connection, device_id: Optional[str] = None) -> Optional[dict[str, Any]]:
    if device_id:
        row = conn.execute(
            f"SELECT {READING_COLUMNS} FROM sensor_readings WHERE device_id = ? ORDER BY measured_ms DESC, id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    else:
        row = conn.execute(
            f"SELECT {READING_COLUMNS} FROM sensor_readings ORDER BY is_simulated ASC, measured_ms DESC, id DESC LIMIT 1"
        ).fetchone()
    return row_to_dict(row) if row else None


def query_readings(
    conn: sqlite3.Connection,
    start_ms: int,
    end_ms: int,
    include_simulated: bool,
    device_id: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    where = ["measured_ms >= ?", "measured_ms <= ?"]
    params: list[Any] = [start_ms, end_ms]
    if not include_simulated:
        where.append("is_simulated = 0")
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)
    clause = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM sensor_readings WHERE {clause}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT {READING_COLUMNS} FROM sensor_readings WHERE {clause} ORDER BY measured_ms DESC, id DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [row_to_dict(r) for r in rows], total


def reading_series(
    conn: sqlite3.Connection,
    start_ms: int,
    end_ms: int,
    include_simulated: bool,
    device_id: Optional[str],
    max_points: int = 400,
) -> dict[str, Any]:
    bucket_ms = max(5000, (end_ms - start_ms) // max_points)
    where = ["measured_ms >= ?", "measured_ms <= ?", "valid = 1"]
    params: list[Any] = [start_ms, end_ms]
    if not include_simulated:
        where.append("is_simulated = 0")
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)
    rows = conn.execute(
        "SELECT (measured_ms / ?) * ? AS bucket, AVG(temperature_c) AS t, AVG(humidity_pct) AS h, "
        "AVG(light_pct) AS light, MAX(gas_adc) AS gas, MAX(motion_detected) AS motion, COUNT(*) AS n "
        f"FROM sensor_readings WHERE {' AND '.join(where)} GROUP BY bucket ORDER BY bucket",
        [bucket_ms, bucket_ms, *params],
    ).fetchall()
    points = [
        {
            "t": int(r["bucket"]),
            "temperature_c": None if r["t"] is None else round(r["t"], 2),
            "humidity_pct": None if r["h"] is None else round(r["h"], 2),
            "light_pct": None if r["light"] is None else round(r["light"], 1),
            "gas_adc_max": r["gas"],
            "motion_any": None if r["motion"] is None else bool(r["motion"]),
            "samples": r["n"],
        }
        for r in rows
    ]
    return {"bucket_ms": bucket_ms, "points": points}


def collection_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    r = conn.execute(
        "SELECT "
        " SUM(CASE WHEN is_simulated = 0 THEN 1 ELSE 0 END) AS real_total,"
        " SUM(CASE WHEN is_simulated = 0 AND valid = 1 THEN 1 ELSE 0 END) AS real_valid,"
        " SUM(CASE WHEN is_simulated = 0 AND valid = 1 AND timestamp_trusted = 1 THEN 1 ELSE 0 END) AS real_valid_trusted,"
        " SUM(CASE WHEN is_simulated = 0 AND valid = 0 THEN 1 ELSE 0 END) AS real_incomplete,"
        " SUM(CASE WHEN is_simulated = 1 THEN 1 ELSE 0 END) AS simulated,"
        " SUM(CASE WHEN timestamp_trusted = 0 THEN 1 ELSE 0 END) AS untrusted_timestamps,"
        " SUM(out_of_order) AS out_of_order,"
        " MIN(CASE WHEN is_simulated = 0 THEN measured_at END) AS first_real,"
        " MAX(CASE WHEN is_simulated = 0 THEN measured_at END) AS last_real "
        "FROM sensor_readings"
    ).fetchone()
    rejections = {
        row["reason"]: row["n"]
        for row in conn.execute("SELECT reason, COUNT(*) AS n FROM ingest_rejections GROUP BY reason")
    }
    feedback = conn.execute(
        "SELECT COUNT(*) AS n, SUM(CASE WHEN context_simulated = 0 AND temperature_c IS NOT NULL AND light_pct IS NOT NULL THEN 1 ELSE 0 END) AS usable "
        "FROM comfort_feedback"
    ).fetchone()
    return {
        "real_readings": r["real_total"] or 0,
        "real_valid_readings": r["real_valid"] or 0,
        "real_valid_trusted_time": r["real_valid_trusted"] or 0,
        "real_incomplete_readings": r["real_incomplete"] or 0,
        "simulated_readings": r["simulated"] or 0,
        "untrusted_timestamps": r["untrusted_timestamps"] or 0,
        "out_of_order": r["out_of_order"] or 0,
        "rejected_invalid": rejections.get("invalid", 0),
        "rejected_duplicate": rejections.get("duplicate", 0),
        "rejected_unauthorized": rejections.get("unauthorized", 0),
        "rejected_too_large": rejections.get("too_large", 0),
        "rejected_rate_limited": rejections.get("rate_limited", 0),
        "first_real_at": r["first_real"],
        "last_real_at": r["last_real"],
        "target_valid_readings": 1000,
        "feedback_total": feedback["n"] or 0,
        "feedback_usable_for_ml": feedback["usable"] or 0,
    }
