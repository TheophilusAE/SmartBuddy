from __future__ import annotations

import hashlib
import http.client
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard"
sys.path.insert(0, str(DASHBOARD))

from backend.security import hash_password  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    RESULTS.append((name, ok, info))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{'  - ' + info if info and not ok else ''}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Client:
    def __init__(self, base: str):
        self.base = base
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf: str | None = None

    def call(self, method: str, path: str, body=None, headers=None, raw: bytes | None = None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with self.opener.open(req, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()


def jbody(b: bytes):
    try:
        return json.loads(b)
    except ValueError:
        return {}


def iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def reading(device_id: str, seq: int, boot: str = "0badf00d", source: str = "device", **over):
    r = {
        "device_id": device_id, "boot_id": boot, "sequence": seq, "timestamp": iso_now(), "uptime_ms": 1000 + seq,
        "temperature_c": 24.5, "humidity_pct": 50.0, "light_pct": 62.5, "ldr_raw": 1535, "motion_detected": False,
        "gas_adc": 800, "gas_warning_local": False,
        "sensor_status": {"dht": "ok", "ldr": "ok", "pir": "ok", "mq2": "ok"},
        "actuators": {"fan": False, "light": False, "buzzer": False}, "source": source,
    }
    r.update(over)
    return r


def start_backend(env: dict, port: int) -> subprocess.Popen:
    cmd = [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port),
           "--log-level", "warning", "--no-server-header"]
    proc = subprocess.Popen(cmd, cwd=DASHBOARD, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/v1/health", timeout=1):
                return proc
        except OSError:
            time.sleep(0.3)
    proc.kill()
    out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
    raise RuntimeError("backend did not start:\n" + out[-2000:])


def stop_backend(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="smartbuddy_smoke_"))
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    origin = "http://127.0.0.1:5173"

    device_key = secrets.token_urlsafe(32)
    sim_key = secrets.token_urlsafe(32)
    admin_pw = secrets.token_urlsafe(12)
    env = dict(os.environ)
    env.update({
        "SMARTBUDDY_ENV_FILE": "none",
        "APP_ENV": "production",
        "DATABASE_PATH": str(tmp / "smoke.db"),
        "MODELS_DIR": str(tmp / "models"),
        "FRONTEND_DIST": str(tmp / "no-frontend"),
        "ADMIN_USERNAME": "admin",
        "ADMIN_PASSWORD_HASH": hash_password(admin_pw),
        "DEVICE_KEYS": f"sb-esp32-01:{hashlib.sha256(device_key.encode()).hexdigest()}",
        "SIMULATOR_KEYS": f"sim-01:{hashlib.sha256(sim_key.encode()).hexdigest()}",
        "ALLOW_SIMULATOR": "true",
        "CORS_ORIGINS": origin,
        "DEVICE_CONTROL_ENABLED": "true",
    })
    dev = {"Authorization": f"Bearer {device_key}"}
    sim = {"Authorization": f"Bearer {sim_key}"}

    proc = start_backend(env, port)
    try:
        c = Client(base)

        code, headers, body = c.call("GET", "/api/v1/health")
        hb = jbody(body)
        check("health returns 200 with no internals",
              code == 200 and hb.get("status") == "ok" and set(hb) <= {"status", "server_time_ms"})
        h = {k.lower(): v for k, v in headers.items()}
        check("security headers present", all(k in h for k in (
            "content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy")))
        check("server header hidden", "server" not in h or "uvicorn" not in h.get("server", "").lower())
        code, _, _ = c.call("GET", "/api/v1/ready")
        check("ready returns 200", code == 200)
        code, _, _ = c.call("GET", "/api/docs")
        check("API docs disabled in production", code == 404)

        code, _, _ = c.call("GET", "/api/v1/readings/latest")
        check("unauthenticated request rejected (401)", code == 401)
        code, _, _ = c.call("POST", "/api/v1/auth/login", {"username": "admin", "password": "wrong-password"})
        check("wrong password rejected (401)", code == 401)
        code, _, _ = c.call("POST", "/api/v1/auth/login", {"username": "admin' OR '1'='1", "password": "x"})
        check("SQL-injection-shaped username rejected by validation (422)", code == 422)
        code, _, _ = c.call("POST", "/api/v1/auth/login", raw=b"{not json")
        check("malformed JSON rejected (422)", code == 422)

        code, headers, body = c.call("POST", "/api/v1/auth/login", {"username": "admin", "password": admin_pw})
        c.csrf = jbody(body).get("csrf_token")
        cookie = headers.get("set-cookie") or headers.get("Set-Cookie") or ""
        check("correct login succeeds", code == 200 and bool(c.csrf))
        check("session cookie is HttpOnly + SameSite=Strict",
              "httponly" in cookie.lower() and "samesite=strict" in cookie.lower())

        code, _, _ = c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 0))
        check("reading without device key rejected (401)", code == 401)
        code, _, _ = c.call("POST", "/api/v1/device/readings", reading("other-dev", 0), headers=dev)
        check("reading for a different device_id rejected (403)", code == 403)
        code, _, _ = c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 0, source="simulator"), headers=dev)
        check("real key can't send simulator-labelled data (403)", code == 403)
        code, _, _ = c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 0, temperature_c=500.0), headers=dev)
        check("out-of-range temperature rejected (422)", code == 422)
        code, _, _ = c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 0, temperature_c="24"), headers=dev)
        check("string instead of number rejected (422)", code == 422)
        bad = reading("sb-esp32-01", 0, temperature_c=None)
        code, _, _ = c.call("POST", "/api/v1/device/readings", bad, headers=dev)
        check("status 'ok' with null value rejected (422)", code == 422)
        code, _, _ = c.call("POST", "/api/v1/device/readings", raw=b'{"temperature_c": NaN}', headers=dev)
        check("NaN rejected (422)", code == 422)
        extra = reading("sb-esp32-01", 0)
        extra["admin"] = True
        code, _, _ = c.call("POST", "/api/v1/device/readings", extra, headers=dev)
        check("unknown field rejected (422)", code == 422)
        code, _, _ = c.call("POST", "/api/v1/device/readings", raw=b"{" + b" " * 3000 + b"}", headers=dev)
        check("oversized body rejected (413)", code == 413)

        code, _, body = c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 1), headers=dev)
        stored = jbody(body)
        check("valid reading stored (201)", code == 201 and stored.get("status") == "stored" and stored.get("valid") is True)
        check("response carries server_time_ms for the device clock", isinstance(stored.get("server_time_ms"), int))
        code, _, body = c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 1), headers=dev)
        check("duplicate detected (200 duplicate)", code == 200 and jbody(body).get("status") == "duplicate")
        old = reading("sb-esp32-01", 2, timestamp="2020-01-01T00:00:00.000Z")
        code, _, _ = c.call("POST", "/api/v1/device/readings", old, headers=dev)
        warm = reading("sb-esp32-01", 3, timestamp=None, gas_adc=None,
                       sensor_status={"dht": "ok", "ldr": "ok", "pir": "warming_up", "mq2": "warming_up"},
                       motion_detected=None)
        code2, _, _ = c.call("POST", "/api/v1/device/readings", warm, headers=dev)
        check("skewed and null timestamps accepted but marked untrusted", code == 201 and code2 == 201)

        code, _, body = c.call("POST", "/api/v1/device/readings", reading("sim-01", 0, source="simulator"), headers=sim)
        check("simulator reading accepted with simulator key", code == 201)

        code, _, body = c.call("GET", "/api/v1/stats")
        st = jbody(body)
        check("stats keep real and simulated apart",
              st.get("real_valid_readings") == 3 and st.get("simulated_readings") == 1, json.dumps(st))
        check("stats count rejections by reason",
              st.get("rejected_duplicate") == 1 and st.get("rejected_invalid", 0) >= 4 and st.get("rejected_unauthorized", 0) >= 1
              and st.get("rejected_too_large") == 1 and st.get("untrusted_timestamps") == 2, json.dumps(st))

        code, _, body = c.call("GET", "/api/v1/readings/latest")
        latest = jbody(body).get("reading") or {}
        check("latest reading prefers real hardware data", latest.get("device_id") == "sb-esp32-01" and latest.get("is_simulated") is False)

        code, _, _ = c.call("GET", "/api/v1/readings?device_id=x'%20OR%201=1--")
        check("SQL-injection-shaped query parameter rejected (422)", code == 422)
        start = (datetime.now(timezone.utc) - timedelta(days=40)).strftime("%Y-%m-%dT%H:%M:%SZ")
        code, _, _ = c.call("GET", f"/api/v1/readings?start={start}")
        check("range over 31 days rejected (422)", code == 422)
        code, _, body = c.call("GET", "/api/v1/readings?page_size=10")
        check("paginated history works", code == 200 and jbody(body).get("total") == 3)
        code, _, _ = c.call("GET", "/api/v1/readings?page_size=10000")
        check("page_size is bounded (422)", code == 422)

        cmd = {"device_id": "sb-esp32-01", "target": "fan", "state": "on"}
        code, _, _ = c.call("POST", "/api/v1/devices/commands", cmd)
        check("command without CSRF token rejected (403)", code == 403)
        code, _, _ = c.call("POST", "/api/v1/devices/commands", cmd,
                            headers={"X-CSRF-Token": c.csrf, "Origin": "http://evil.example"})
        check("command from a foreign Origin rejected (403)", code == 403)
        code, _, _ = c.call("POST", "/api/v1/devices/commands", dict(cmd, device_id="ghost-01"),
                            headers={"X-CSRF-Token": c.csrf})
        check("command for an unknown device refused (404)", code == 404)

        c.call("GET", "/api/v1/device/commands", headers=dev)
        code, _, body = c.call("POST", "/api/v1/devices/commands", cmd, headers={"X-CSRF-Token": c.csrf})
        ev = jbody(body)
        check("command queued (202, pending - not reported as done)", code == 202 and ev.get("status") == "pending")
        bogus = dict(cmd, target="door")
        code, _, _ = c.call("POST", "/api/v1/devices/commands", bogus, headers={"X-CSRF-Token": c.csrf})
        check("unknown actuator rejected (422)", code == 422)

        code, _, body = c.call("GET", "/api/v1/device/commands", headers=dev)
        cmds = jbody(body).get("commands", [])
        check("device receives the command once", code == 200 and len(cmds) == 1 and cmds[0]["target"] == "fan")
        code, _, body = c.call("GET", "/api/v1/device/commands", headers=dev)
        check("command not delivered twice", jbody(body).get("commands") == [])

        ack = {"device_id": "sb-esp32-01", "command_id": cmds[0]["id"], "result": "applied", "reason": None,
               "observed": {"fan": True, "light": False, "buzzer": False}}
        code, _, _ = c.call("POST", "/api/v1/device/acks", ack, headers=sim)
        check("another device can't ack this command", code in (403, 404))
        code, _, _ = c.call("POST", "/api/v1/device/acks", ack, headers=dev)
        check("ack accepted", code == 200)
        code, _, body = c.call("GET", f"/api/v1/devices/commands/{cmds[0]['id']}")
        ev = jbody(body)
        check("command shows acked with the observed state", ev.get("status") == "acked" and ev.get("observed", {}).get("fan") is True)

        gas = reading("sb-esp32-01", 10, gas_adc=3000, gas_warning_local=True)
        c.call("POST", "/api/v1/device/readings", gas, headers=dev)
        code, _, body = c.call("GET", "/api/v1/warnings")
        check("gas warning raised from a high reading", any(w.get("active") for w in jbody(body).get("warnings", [])))
        c.call("GET", "/api/v1/device/commands", headers=dev)
        off = {"device_id": "sb-esp32-01", "target": "fan", "state": "off"}
        c.call("POST", "/api/v1/devices/commands", off, headers={"X-CSRF-Token": c.csrf})
        code, _, body = c.call("POST", "/api/v1/devices/commands", cmd, headers={"X-CSRF-Token": c.csrf})
        check("fan ON during gas warning needs explicit confirmation (409)", code == 409)
        code, _, _ = c.call("POST", "/api/v1/devices/commands", dict(cmd, acknowledge_gas_warning=True),
                            headers={"X-CSRF-Token": c.csrf})
        check("fan ON allowed after explicit confirmation", code == 202)
        c.call("POST", "/api/v1/device/readings", reading("sb-esp32-01", 11, gas_adc=700), headers=dev)
        code, _, body = c.call("GET", "/api/v1/warnings")
        check("gas warning clears below the clear threshold", not jbody(body).get("warnings"))

        code, _, _ = c.call("PUT", "/api/v1/mode", {"mode": "ML_AUTOMATIC"}, headers={"X-CSRF-Token": c.csrf})
        check("ML_AUTOMATIC refused without validation flag/model (409)", code == 409)
        code, _, _ = c.call("PUT", "/api/v1/mode", {"mode": "TURBO"}, headers={"X-CSRF-Token": c.csrf})
        check("unknown mode rejected (422)", code == 422)
        code, _, body = c.call("PUT", "/api/v1/mode", {"mode": "RULE_BASED"}, headers={"X-CSRF-Token": c.csrf})
        check("mode change to RULE_BASED", code == 200)

        code, _, body = c.call("POST", "/api/v1/feedback", {"rating": 4, "device_id": "sb-esp32-01"},
                               headers={"X-CSRF-Token": c.csrf})
        check("feedback stored with reading context", code == 201 and jbody(body).get("context_simulated") is False)
        code, _, _ = c.call("POST", "/api/v1/feedback", {"rating": 9}, headers={"X-CSRF-Token": c.csrf})
        check("rating outside 1-5 rejected (422)", code == 422)
        code, _, body = c.call("GET", "/api/v1/ml/status")
        check("ML status reports no model (nothing fabricated)", code == 200 and jbody(body).get("model_available") is False)
        code, _, body = c.call("GET", "/api/v1/ml/advice")
        adv = jbody(body)
        check("advice falls back to general guidance without a model", adv.get("basis") == "general" and adv.get("estimate") is None)

        code, headers, body = c.call("GET", "/api/v1/readings/export.csv")
        text = body.decode()
        check("CSV export works for admin", code == 200 and text.startswith("id,device_id,boot_id"))
        check("CSV keeps negative numbers intact and has no simulated rows by default", "sim-01" not in text)

        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("OPTIONS", "/api/v1/auth/login", headers={
            "Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
        r = conn.getresponse()
        r.read()
        check("CORS preflight from unknown origin not allowed", r.getheader("access-control-allow-origin") is None)
        conn.request("OPTIONS", "/api/v1/auth/login", headers={"Origin": origin, "Access-Control-Request-Method": "POST"})
        r = conn.getresponse()
        r.read()
        check("CORS preflight from the dashboard origin allowed", r.getheader("access-control-allow-origin") == origin)
        conn.close()

        code, _, body = c.call("POST", "/api/v1/devices/emergency-stop", {"device_id": "sb-esp32-01"},
                               headers={"X-CSRF-Token": c.csrf})
        code2, _, body2 = c.call("GET", "/api/v1/mode")
        check("emergency stop queues all-off and switches to MANUAL",
              code == 202 and jbody(body).get("target") == "all" and jbody(body2).get("mode") == "MANUAL")

        code, _, _ = c.call("POST", "/api/v1/auth/logout", headers={"X-CSRF-Token": c.csrf})
        code2, _, _ = c.call("GET", "/api/v1/auth/me")
        check("logout revokes the session", code == 200 and code2 == 401)

        rl = Client(base)
        codes = [rl.call("POST", "/api/v1/auth/login", {"username": "admin", "password": "nope-nope"})[0] for _ in range(7)]
        check("login rate limit kicks in", 429 in codes, str(codes))
    finally:
        stop_backend(proc)

    env["DEVICE_CONTROL_ENABLED"] = "false"
    proc = start_backend(env, port)
    try:
        c = Client(base)
        _, _, body = c.call("POST", "/api/v1/auth/login", {"username": "admin", "password": admin_pw})
        c.csrf = jbody(body).get("csrf_token")
        code, _, body = c.call("GET", "/api/v1/stats")
        check("readings persist after restart", code == 200 and jbody(body).get("real_valid_readings", 0) >= 3)
        c.call("GET", "/api/v1/device/commands", headers=dev)
        code, _, body = c.call("POST", "/api/v1/devices/commands", {"device_id": "sb-esp32-01", "target": "fan", "state": "on"},
                               headers={"X-CSRF-Token": c.csrf})
        check("monitor-only mode refuses commands (409)", code == 409)
        _, _, body = c.call("GET", "/api/v1/devices/state")
        check("device state says monitor-only", jbody(body).get("device_control_enabled") is False)
    finally:
        stop_backend(proc)
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
