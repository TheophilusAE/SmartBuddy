from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import Settings
from .security import lookup_key
from .timeutil import parse_iso, to_iso, utc_now

ALLOWED = {
    "fan": {"on", "off"},
    "light": {"on", "off"},
    "buzzer": {"on", "off"},
    "alarm": {"mute"},
    "all": {"off"},
}


@dataclass
class DeviceIdentity:
    device_id: str
    simulated: bool


def authenticate_device(settings: Settings, authorization: Optional[str]) -> Optional[DeviceIdentity]:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization[len("Bearer "):].strip()
    if not 16 <= len(token) <= 128:
        return None
    device_id = lookup_key(token, settings.device_keys)
    if device_id:
        return DeviceIdentity(device_id, simulated=False)
    if settings.allow_simulator:
        device_id = lookup_key(token, settings.simulator_keys)
        if device_id:
            return DeviceIdentity(device_id, simulated=True)
    return None


def event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    observed = None
    if row["observed_fan"] is not None:
        observed = {
            "fan": bool(row["observed_fan"]),
            "light": bool(row["observed_light"]),
            "buzzer": bool(row["observed_buzzer"]),
        }
    return {
        "id": row["id"],
        "device_id": row["device_id"],
        "target": row["target"],
        "state": row["state"],
        "source": row["source"],
        "requested_by": row["requested_by"],
        "reason": row["reason"],
        "status": row["status"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "sent_at": row["sent_at"],
        "acked_at": row["acked_at"],
        "result": row["ack_result"],
        "ack_reason": row["ack_reason"],
        "observed": observed,
    }


def get_event(conn: sqlite3.Connection, command_id: int) -> Optional[dict[str, Any]]:
    row = conn.execute("SELECT * FROM device_events WHERE id = ?", (command_id,)).fetchone()
    return event_to_dict(row) if row else None


def recent_events(conn: sqlite3.Connection, device_id: Optional[str], limit: int) -> list[dict[str, Any]]:
    if device_id:
        rows = conn.execute(
            "SELECT * FROM device_events WHERE device_id = ? ORDER BY id DESC LIMIT ?", (device_id, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM device_events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [event_to_dict(r) for r in rows]


def queue_command(
    conn: sqlite3.Connection,
    settings: Settings,
    device_id: str,
    target: str,
    state: str,
    source: str,
    requested_by: Optional[str],
    reason: Optional[str] = None,
) -> dict[str, Any]:
    if state not in ALLOWED.get(target, set()):
        raise ValueError(f"invalid command {target}={state}")
    now = utc_now()
    supersede_targets = ["fan", "light", "buzzer"] if target == "all" else [target]
    conn.execute(
        f"UPDATE device_events SET status = 'superseded' WHERE device_id = ? AND status = 'pending' "
        f"AND target IN ({','.join('?' * len(supersede_targets))})",
        (device_id, *supersede_targets),
    )
    cur = conn.execute(
        "INSERT INTO device_events (device_id, target, state, source, requested_by, reason, status, created_at, "
        "expires_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?) RETURNING *",
        (device_id, target, state, source, requested_by, reason, to_iso(now),
         to_iso(now + timedelta(seconds=settings.command_ttl_s))),
    )
    return event_to_dict(cur.fetchone())


def take_pending(conn: sqlite3.Connection, device_id: str, now: datetime) -> list[dict[str, Any]]:
    now_iso = to_iso(now)
    rows = conn.execute(
        "SELECT * FROM device_events WHERE device_id = ? AND status = 'pending' AND expires_at > ? "
        "ORDER BY id LIMIT 8",
        (device_id, now_iso),
    ).fetchall()
    out = []
    for row in rows:
        conn.execute("UPDATE device_events SET status = 'sent', sent_at = ? WHERE id = ?", (now_iso, row["id"]))
        remaining = int((parse_iso(row["expires_at"]) - now).total_seconds() * 1000)
        out.append({"id": row["id"], "target": row["target"], "state": row["state"], "expires_in_ms": remaining})
    return out


def record_ack(
    conn: sqlite3.Connection,
    device_id: str,
    command_id: int,
    result: str,
    reason: Optional[str],
    observed: dict[str, bool],
    now: datetime,
) -> Optional[dict[str, Any]]:
    row = conn.execute(
        "SELECT * FROM device_events WHERE id = ? AND device_id = ?", (command_id, device_id)
    ).fetchone()
    if row is None:
        return None
    status = {"applied": "acked", "rejected": "rejected", "expired": "expired"}[result]
    conn.execute(
        "UPDATE device_events SET status = ?, acked_at = ?, ack_result = ?, ack_reason = ?, observed_fan = ?, "
        "observed_light = ?, observed_buzzer = ? WHERE id = ?",
        (status, to_iso(now), result, reason, int(observed["fan"]), int(observed["light"]),
         int(observed["buzzer"]), command_id),
    )
    conn.execute(
        "UPDATE device_status SET fan_on = ?, light_on = ?, buzzer_on = ?, state_reported_at = ? WHERE device_id = ?",
        (int(observed["fan"]), int(observed["light"]), int(observed["buzzer"]), to_iso(now), device_id),
    )
    return get_event(conn, command_id)


def expire_overdue(conn: sqlite3.Connection, now: datetime) -> list[dict[str, Any]]:
    now_iso = to_iso(now)
    rows = conn.execute(
        "SELECT id FROM device_events WHERE status IN ('pending', 'sent') AND expires_at <= ?", (now_iso,)
    ).fetchall()
    expired = []
    for row in rows:
        conn.execute("UPDATE device_events SET status = 'expired' WHERE id = ?", (row["id"],))
        expired.append(get_event(conn, row["id"]))
    return [e for e in expired if e]


def touch_device(conn: sqlite3.Connection, identity: DeviceIdentity, now: datetime) -> None:
    conn.execute(
        "INSERT INTO device_status (device_id, is_simulated, last_seen_at) VALUES (?, ?, ?) "
        "ON CONFLICT(device_id) DO UPDATE SET last_seen_at = excluded.last_seen_at",
        (identity.device_id, int(identity.simulated), to_iso(now)),
    )


def device_states(conn: sqlite3.Connection, settings: Settings, now: datetime) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM device_status ORDER BY is_simulated, device_id").fetchall()
    out = []
    for r in rows:
        online = False
        if r["last_seen_at"]:
            online = (now - parse_iso(r["last_seen_at"])).total_seconds() <= settings.device_offline_s
        pending = conn.execute(
            "SELECT * FROM device_events WHERE device_id = ? AND status IN ('pending', 'sent') ORDER BY id",
            (r["device_id"],),
        ).fetchall()
        out.append({
            "device_id": r["device_id"],
            "is_simulated": bool(r["is_simulated"]),
            "online": online,
            "last_seen_at": r["last_seen_at"],
            "state_reported_at": r["state_reported_at"],
            "actuators": {
                "fan": None if r["fan_on"] is None else bool(r["fan_on"]),
                "light": None if r["light_on"] is None else bool(r["light_on"]),
                "buzzer": None if r["buzzer_on"] is None else bool(r["buzzer_on"]),
            },
            "gas_warning_local": bool(r["gas_warning_local"]),
            "rain_status": r["rain_status"],
            "rain_changed_at": r["rain_changed_at"],
            "window_state": r["window_state"],
            "window_changed_at": r["window_changed_at"],
            "pending_commands": [event_to_dict(p) for p in pending],
        })
    return out


def is_online(conn: sqlite3.Connection, settings: Settings, device_id: str, now: datetime) -> bool:
    row = conn.execute("SELECT last_seen_at FROM device_status WHERE device_id = ?", (device_id,)).fetchone()
    if row is None or row["last_seen_at"] is None:
        return False
    return (now - parse_iso(row["last_seen_at"])).total_seconds() <= settings.device_offline_s
