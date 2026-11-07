"""Fake ESP32 for testing without hardware. Readings are marked as simulated.

    python scripts/simulate_device.py --device-id sim-01 --key <key>
"""
from __future__ import annotations

import argparse
import json
import math
import random
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone


class Sim:
    def __init__(self, url: str, device_id: str, key: str):
        self.url = url.rstrip("/")
        self.device_id = device_id
        self.key = key
        self.boot_id = secrets.token_hex(4)
        self.seq = 0
        self.fan = self.light = self.buzzer = False
        self.started = time.monotonic()

    def _req(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, {}
        except (urllib.error.URLError, OSError):
            return -1, {}

    def reading(self) -> dict:
        t = time.monotonic() - self.started
        temp = 25 + 3 * math.sin(t / 300) + random.uniform(-0.2, 0.2) - (0.8 if self.fan else 0)
        hum = 55 + 8 * math.sin(t / 500) + random.uniform(-1, 1)
        light = min(100.0, max(0.0, 55 + 30 * math.sin(t / 400) + random.uniform(-1, 1) + (3 if self.light else 0)))
        warm = t < 30
        body = {
            "device_id": self.device_id,
            "boot_id": self.boot_id,
            "sequence": self.seq,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "uptime_ms": int(t * 1000),
            "temperature_c": round(temp, 1),
            "humidity_pct": round(hum, 1),
            "light_pct": round(light, 1),
            "ldr_raw": int(round((100 - light) * 40.95)),
            "motion_detected": random.random() < 0.3,
            "gas_adc": None if warm else int(900 + random.uniform(-40, 40)),
            "gas_warning_local": False,
            "sensor_status": {"dht": "ok", "ldr": "ok", "pir": "ok", "mq2": "warming_up" if warm else "ok"},
            "actuators": {"fan": self.fan, "light": self.light, "buzzer": self.buzzer},
            "source": "simulator",
        }
        self.seq += 1
        return body

    def apply(self, cmd: dict) -> dict:
        result, reason = "applied", None
        target, state = cmd.get("target"), cmd.get("state")
        if cmd.get("expires_in_ms", 0) <= 0:
            result, reason = "expired", "expired on arrival"
        elif target == "fan" and state in ("on", "off"):
            self.fan = state == "on"
        elif target == "light" and state in ("on", "off"):
            self.light = state == "on"
        elif target == "buzzer" and state in ("on", "off"):
            self.buzzer = state == "on"
        elif target == "all" and state == "off":
            self.fan = self.light = self.buzzer = False
        elif target == "alarm" and state == "mute":
            result, reason = "rejected", "no active alarm"
        else:
            result, reason = "rejected", "unknown target/state"
        return {
            "device_id": self.device_id,
            "command_id": cmd["id"],
            "result": result,
            "reason": reason,
            "observed": {"fan": self.fan, "light": self.light, "buzzer": self.buzzer},
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-id", default="sim-01")
    parser.add_argument("--key", required=True)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--count", type=int, default=0, help="stop after N readings (0 = run until Ctrl+C)")
    args = parser.parse_args()

    sim = Sim(args.url, args.device_id, args.key)
    print(f"simulating {args.device_id} (boot {sim.boot_id}) -> {sim.url}. Ctrl+C to stop.")
    next_reading = 0.0
    sent = 0
    try:
        while args.count == 0 or sent < args.count:
            now = time.monotonic()
            if now >= next_reading:
                next_reading = now + args.interval
                code, body = sim._req("POST", "/api/v1/device/readings", sim.reading())
                sent += 1
                print(f"reading #{sim.seq - 1}: HTTP {code} {body.get('status', '')}")
            code, body = sim._req("GET", "/api/v1/device/commands")
            for cmd in body.get("commands", []) if code == 200 else []:
                ack = sim.apply(cmd)
                ack_code, _ = sim._req("POST", "/api/v1/device/acks", ack)
                print(f"command #{cmd['id']} {cmd['target']}={cmd['state']} -> {ack['result']} (ack HTTP {ack_code})")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nstopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
