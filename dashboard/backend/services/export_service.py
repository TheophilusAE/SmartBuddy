from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any, Iterator, Optional

EXPORT_FIELDS = [
    "id", "device_id", "boot_id", "sequence", "measured_at", "received_at", "timestamp_trusted",
    "temperature_c", "humidity_pct", "light_pct", "ldr_raw", "motion_detected", "gas_adc", "gas_warning_local",
    "dht_status", "ldr_status", "pir_status", "mq2_status", "fan_on", "light_on", "buzzer_on",
    "valid", "out_of_order", "is_simulated",
    "rain_raw", "rain_filtered", "rain_status", "window_state", "servo_angle", "window_auto", "fan_control",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def iter_csv(
    conn: sqlite3.Connection,
    start_ms: int,
    end_ms: int,
    include_simulated: bool,
    device_id: Optional[str],
) -> Iterator[str]:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(EXPORT_FIELDS)

    where = ["measured_ms >= ?", "measured_ms <= ?"]
    params: list[Any] = [start_ms, end_ms]
    if not include_simulated:
        where.append("is_simulated = 0")
    if device_id:
        where.append("device_id = ?")
        params.append(device_id)

    cursor = conn.execute(
        f"SELECT {', '.join(EXPORT_FIELDS)} FROM sensor_readings WHERE {' AND '.join(where)} ORDER BY measured_ms, id",
        params,
    )
    count = 0
    for row in cursor:
        writer.writerow([safe_cell(row[f]) for f in EXPORT_FIELDS])
        count += 1
        if count % 500 == 0:
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate(0)
    yield buf.getvalue()
