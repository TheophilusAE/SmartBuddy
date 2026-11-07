"""USB serial bridge (backup if there's no Wi-Fi): reads the CSV from the ESP32 and POSTs it to the backend.

    dashboard\\.venv\\Scripts\\python scripts\\serial_bridge.py --list-ports
    dashboard\\.venv\\Scripts\\python scripts\\serial_bridge.py --port COM4

Close the Arduino Serial Monitor first.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

CSV_HEADER = [
    "timestamp_ms", "temperature_c", "humidity_percent", "light_percent", "ldr_raw", "motion_detected",
    "mq2_raw", "mq2_filtered", "mq2_status", "fan_state", "led_state", "buzzer_state",
    "dht_status", "ldr_status", "pir_status", "mq2_sensor_status", "dht_new_reading", "record_valid",
    "rain_raw", "rain_filtered", "rain_status", "window_state", "servo_angle",
]
OLD_FIELD_COUNT = 18   # firmware before the rain sensor
SENSOR_STATES = {"INITIALIZING", "WARMING_UP", "READY", "ERROR"}
MQ2_INDICATIONS = {"WARMING", "NORMAL", "ALERT", "ERROR"}
RAIN_STATES = {"INITIALIZING", "DRY", "RAIN", "ERROR"}
WINDOW_STATES = {"UNKNOWN", "OPEN", "CLOSED", "MOVING"}
MAX_LINE = 400
QUEUE_LIMIT = 500
CSV_SILENCE_RESEND_S = 6


class LineError(ValueError):
    pass


@dataclass
class CsvRow:
    timestamp_ms: int
    temperature_c: Optional[float]
    humidity_pct: Optional[float]
    light_pct: Optional[float]
    ldr_raw: Optional[int]
    motion: Optional[bool]
    mq2_raw: Optional[int]
    mq2_filtered: Optional[int]
    mq2_indication: str
    fan_on: bool
    led_on: bool
    alarm_on: bool
    dht_state: str
    ldr_state: str
    pir_state: str
    mq2_state: str
    rain_raw: Optional[int] = None
    rain_filtered: Optional[int] = None
    rain_status: Optional[str] = None
    window_state: Optional[str] = None
    servo_angle: Optional[int] = None


def _opt_float(text: str, name: str, lo: float, hi: float) -> Optional[float]:
    if text == "":
        return None
    try:
        v = float(text)
    except ValueError as exc:
        raise LineError(f"{name} is not a number") from exc
    if not lo <= v <= hi or v != v:
        raise LineError(f"{name} out of range")
    return v


def _opt_int(text: str, name: str, lo: int, hi: int) -> Optional[int]:
    if text == "":
        return None
    if not text.isdigit():
        raise LineError(f"{name} is not an integer")
    v = int(text)
    if not lo <= v <= hi:
        raise LineError(f"{name} out of range")
    return v


def _flag(text: str, name: str) -> bool:
    if text not in ("0", "1"):
        raise LineError(f"{name} must be 0 or 1")
    return text == "1"


def _state(text: str, name: str, allowed: set[str]) -> str:
    if text not in allowed:
        raise LineError(f"{name} has unknown value")
    return text


def parse_csv_line(line: str) -> CsvRow:
    line = line.strip()
    if len(line) > MAX_LINE:
        raise LineError("line too long")
    parts = line.split(",")
    if len(parts) not in (len(CSV_HEADER), OLD_FIELD_COUNT):
        raise LineError("wrong number of fields")
    f = dict(zip(CSV_HEADER, parts))
    has_rain = len(parts) == len(CSV_HEADER)

    ts = _opt_int(f["timestamp_ms"], "timestamp_ms", 0, 2**32 - 1)
    if ts is None:
        raise LineError("timestamp_ms missing")
    motion = f["motion_detected"]
    if motion not in ("", "0", "1"):
        raise LineError("motion_detected must be empty, 0 or 1")
    _flag(f["dht_new_reading"], "dht_new_reading")
    _flag(f["record_valid"], "record_valid")

    rain = {}
    if has_rain:
        rain = {
            "rain_raw": _opt_int(f["rain_raw"], "rain_raw", 0, 4095),
            "rain_filtered": _opt_int(f["rain_filtered"], "rain_filtered", 0, 4095),
            "rain_status": _state(f["rain_status"], "rain_status", RAIN_STATES).lower(),
            "window_state": _state(f["window_state"], "window_state", WINDOW_STATES).lower(),
            "servo_angle": _opt_int(f["servo_angle"], "servo_angle", 0, 180),
        }
        if rain["rain_status"] in ("dry", "rain") and rain["rain_filtered"] is None:
            raise LineError("rain_status without rain_filtered")
        if (rain["window_state"] == "unknown") != (rain["servo_angle"] is None):
            raise LineError("window_state and servo_angle don't match")

    return CsvRow(
        timestamp_ms=ts,
        temperature_c=_opt_float(f["temperature_c"], "temperature_c", -40, 80),
        humidity_pct=_opt_float(f["humidity_percent"], "humidity_percent", 0, 100),
        light_pct=_opt_float(f["light_percent"], "light_percent", 0, 100),
        ldr_raw=_opt_int(f["ldr_raw"], "ldr_raw", 0, 4095),
        motion=None if motion == "" else motion == "1",
        mq2_raw=_opt_int(f["mq2_raw"], "mq2_raw", 0, 4095),
        mq2_filtered=_opt_int(f["mq2_filtered"], "mq2_filtered", 0, 4095),
        mq2_indication=_state(f["mq2_status"], "mq2_status", MQ2_INDICATIONS),
        fan_on=_flag(f["fan_state"], "fan_state"),
        led_on=_flag(f["led_state"], "led_state"),
        alarm_on=_flag(f["buzzer_state"], "buzzer_state"),
        dht_state=_state(f["dht_status"], "dht_status", SENSOR_STATES),
        ldr_state=_state(f["ldr_status"], "ldr_status", SENSOR_STATES),
        pir_state=_state(f["pir_status"], "pir_status", SENSOR_STATES),
        mq2_state=_state(f["mq2_sensor_status"], "mq2_sensor_status", SENSOR_STATES),
        **rain,
    )


def _health(state: str, has_value: bool) -> str:
    if state == "READY":
        return "ok" if has_value else "error"
    if state == "ERROR":
        return "error"
    return "warming_up"


def to_payload(row: CsvRow, device_id: str, boot_id: str, sequence: int, received: datetime) -> dict[str, Any]:
    dht = _health(row.dht_state, row.temperature_c is not None and row.humidity_pct is not None)
    ldr = _health(row.ldr_state, row.light_pct is not None and row.ldr_raw is not None)
    pir = _health(row.pir_state, row.motion is not None)
    mq2 = _health(row.mq2_state, row.mq2_filtered is not None)

    return {
        "device_id": device_id,
        "boot_id": boot_id,
        "sequence": sequence,
        "timestamp": received.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "uptime_ms": row.timestamp_ms,
        "temperature_c": row.temperature_c if dht == "ok" else None,
        "humidity_pct": row.humidity_pct if dht == "ok" else None,
        "light_pct": round(row.light_pct, 1) if ldr == "ok" and row.light_pct is not None else None,
        "ldr_raw": row.ldr_raw if ldr == "ok" else None,
        "motion_detected": row.motion if pir == "ok" else None,
        "gas_adc": row.mq2_filtered if mq2 == "ok" else None,
        "gas_warning_local": row.alarm_on,
        "sensor_status": {"dht": dht, "ldr": ldr, "pir": pir, "mq2": mq2},
        "actuators": {"fan": row.fan_on, "light": row.led_on, "buzzer": row.alarm_on},
        "rain_raw": row.rain_raw,
        "rain_filtered": row.rain_filtered,
        "rain_status": row.rain_status,
        "window_state": row.window_state,
        "servo_angle": row.servo_angle,
        "source": "device",
    }


class Session:
    def __init__(self, device_id: str, interval_s: float):
        self.device_id = device_id
        self.interval_ms = int(interval_s * 1000)
        self.boot_id = secrets.token_hex(4)
        self.sequence = 0
        self.last_ts: Optional[int] = None
        self.last_sent_ts: Optional[int] = None

    def accept(self, row: CsvRow, received: datetime) -> Optional[dict[str, Any]]:
        if self.last_ts is not None and row.timestamp_ms < self.last_ts:
            self.boot_id = secrets.token_hex(4)
            self.sequence = 0
            self.last_sent_ts = None
            print(f"[bridge] ESP32 restart detected, new boot id {self.boot_id}")
        self.last_ts = row.timestamp_ms

        if self.last_sent_ts is not None and row.timestamp_ms - self.last_sent_ts < self.interval_ms:
            return None
        self.last_sent_ts = row.timestamp_ms
        payload = to_payload(row, self.device_id, self.boot_id, self.sequence, received)
        self.sequence += 1
        return payload


def post_reading(url: str, key: str, payload: dict[str, Any]) -> int:
    req = urllib.request.Request(f"{url}/api/v1/device/readings", data=json.dumps(payload).encode(), method="POST")
    req.add_header("Authorization", f"Bearer {key}")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, OSError):
        return -1


def read_key(args: argparse.Namespace) -> str:
    if args.key_file:
        key = Path(args.key_file).read_text(encoding="utf-8").strip()
    else:
        key = os.environ.get("SMARTBUDDY_DEVICE_KEY", "").strip()
    if not 16 <= len(key) <= 128:
        sys.exit("Set the device key in SMARTBUDDY_DEVICE_KEY (or use --key-file). See iot/README.md.")
    return key


def run(args: argparse.Namespace) -> int:
    try:
        import serial
    except ImportError:
        sys.exit("pyserial is not installed: dashboard\\.venv\\Scripts\\pip install -r dashboard\\requirements.txt")

    key = read_key(args)
    url = args.url.rstrip("/")
    host = urlparse(url).hostname or ""
    if host not in ("127.0.0.1", "localhost") and url.startswith("http://"):
        print("[bridge] warning: sending the device key over plain HTTP to another machine")

    session = Session(args.device_id, args.interval)
    queue: deque[dict[str, Any]] = deque(maxlen=QUEUE_LIMIT)
    counts = {"rows": 0, "bad": 0, "sent": 0, "rejected": 0}
    retry_at = 0.0
    last_status = time.monotonic()

    while True:
        try:
            ser = serial.Serial()
            ser.port = args.port
            ser.baudrate = 115200
            ser.timeout = 1
            ser.dtr = False
            ser.rts = False
            ser.open()
        except serial.SerialException as exc:
            print(f"[bridge] can't open {args.port} ({exc.__class__.__name__}); retrying in 3 s")
            time.sleep(3)
            continue

        print(f"[bridge] reading {args.port}, forwarding to {url} as {args.device_id} every {args.interval:g} s")
        ser.write(b"c")
        last_csv = time.monotonic()
        try:
            while True:
                raw = ser.readline()
                now = time.monotonic()
                if raw:
                    line = raw.decode("ascii", errors="replace").strip()
                    if line and line[0].isdigit():
                        try:
                            row = parse_csv_line(line)
                        except LineError as exc:
                            counts["bad"] += 1
                            if args.verbose:
                                print(f"[bridge] dropped line: {exc}")
                        else:
                            counts["rows"] += 1
                            last_csv = now
                            payload = session.accept(row, datetime.now(timezone.utc))
                            if payload:
                                queue.append(payload)

                if now - last_csv > CSV_SILENCE_RESEND_S:
                    ser.write(b"c")
                    last_csv = now

                while queue and now >= retry_at:
                    code = post_reading(url, key, queue[0])
                    if code in (200, 201):
                        queue.popleft()
                        counts["sent"] += 1
                    elif 400 <= code < 500 and code != 429:
                        queue.popleft()
                        counts["rejected"] += 1
                        print(f"[bridge] backend rejected a reading: HTTP {code}")
                    else:
                        retry_at = now + 5
                        print(f"[bridge] backend unreachable (code {code}); {len(queue)} reading(s) waiting")
                        break

                if now - last_status >= 60:
                    last_status = now
                    print(f"[bridge] rows {counts['rows']}, sent {counts['sent']}, rejected {counts['rejected']}, "
                          f"bad lines {counts['bad']}, queued {len(queue)}")
        except serial.SerialException:
            print("[bridge] serial port lost (ESP32 unplugged?); reconnecting")
            time.sleep(2)
        finally:
            try:
                ser.close()
            except Exception:
                pass


def list_ports() -> int:
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        sys.exit("pyserial is not installed: dashboard\\.venv\\Scripts\\pip install -r dashboard\\requirements.txt")
    ports = list(lp.comports())
    if not ports:
        print("No serial ports found. Check the USB cable (it must carry data) and the CP210x/CH340 driver.")
    for p in ports:
        print(f"{p.device:8} {p.description}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="serial port, e.g. COM5")
    parser.add_argument("--list-ports", action="store_true")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-id", default="sb-esp32-01")
    parser.add_argument("--key-file", help="file containing the device key (instead of SMARTBUDDY_DEVICE_KEY)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="seconds between forwarded readings; the firmware prints every 2 s (default: every row)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    if args.list_ports:
        return list_ports()
    if not args.port:
        parser.error("--port is required (use --list-ports to find it)")
    if args.interval < 2:
        parser.error("--interval must be at least 2 s (the firmware prints a row every 2 s)")
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\n[bridge] stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
