"""Writes secrets.h for New_Code.ino.

    dashboard\\.venv\\Scripts\\python scripts\\make_firmware_secrets.py --ssid "MyWifi"
    dashboard\\.venv\\Scripts\\python scripts\\make_firmware_secrets.py --ssid "MyWifi" --url https://smartbuddy.onrender.com
    dashboard\\.venv\\Scripts\\python scripts\\make_firmware_secrets.py --keep-wifi --url https://smartbuddy.onrender.com --force
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import os
import re
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKETCH_DIR = ROOT / "iot" / "firmware" / "smartbuddy_esp32" / "New_Code"
ENV_FILE = ROOT / "dashboard" / ".env"
DEFAULT_KEY_FILE = ROOT / "dashboard" / ".env.bridge-key"


def laptop_ip() -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
        except OSError:
            return ""


def c_string(value: str, name: str) -> str:
    if any(ord(ch) < 32 or ord(ch) > 126 for ch in value):
        sys.exit(f"{name} contains characters that can't go into the firmware (non-ASCII or control characters).")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def read_define(text: str, name: str) -> str | None:
    m = re.search(rf'^#define\s+{name}\s+"((?:[^"\\]|\\.)*)"', text, re.M)
    if not m:
        return None
    return re.sub(r"\\(.)", r"\1", m.group(1))


def registered_hashes(device_id: str) -> set[str]:
    if not ENV_FILE.is_file():
        return set()
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEVICE_KEYS="):
            entries = line.split("=", 1)[1].split(",")
            return {e.split(":", 1)[1].strip().lower() for e in entries if e.strip().startswith(device_id + ":")}
    return set()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ssid", help="2.4 GHz Wi-Fi name the ESP32 should join")
    parser.add_argument("--keep-wifi", action="store_true", help="reuse the Wi-Fi name and password from secrets.h")
    parser.add_argument("--url", help="https address of the hosted backend, e.g. https://smartbuddy.onrender.com")
    parser.add_argument("--host", help="backend address on the local network (default: this laptop's IPv4 address)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--device-id", default="sb-esp32-01")
    parser.add_argument("--key-file", help=f"file with the device key (default: {DEFAULT_KEY_FILE.relative_to(ROOT)})")
    parser.add_argument("--force", action="store_true", help="overwrite an existing secrets.h")
    args = parser.parse_args(argv)

    target = SKETCH_DIR / "secrets.h"
    if target.exists() and not args.force:
        sys.exit(f"{target.relative_to(ROOT)} already exists. Use --force to replace it.")
    if not args.ssid and not args.keep_wifi:
        sys.exit("Pass --ssid \"WifiName\", or --keep-wifi to reuse the Wi-Fi from the current secrets.h.")

    if args.url:
        if args.host:
            sys.exit("Use either --url (hosted backend) or --host (laptop), not both.")
        m = re.fullmatch(r"https://([A-Za-z0-9.\-]{1,100})/?", args.url.strip())
        if not m:
            sys.exit("--url must look like https://your-app.onrender.com (https, no path).")
        host, port, https = m.group(1), 443, 1
    else:
        host, port, https = args.host or laptop_ip(), args.port, 0
        if not re.fullmatch(r"[A-Za-z0-9.\-]{1,63}", host or ""):
            sys.exit("Couldn't work out this laptop's IP address. Pass it with --host (see ipconfig).")
        if host.startswith("127."):
            sys.exit("127.x.x.x is the ESP32 itself, not your laptop. Pass the laptop's Wi-Fi address with --host.")

    key_file = Path(args.key_file) if args.key_file else DEFAULT_KEY_FILE
    if key_file.is_file():
        key = key_file.read_text(encoding="utf-8").strip()
    else:
        key = os.environ.get("SMARTBUDDY_DEVICE_KEY", "").strip()
    if not 16 <= len(key) <= 128 or not re.fullmatch(r"[A-Za-z0-9_\-]+", key):
        sys.exit("No usable device key found. Create one with scripts/gen_device_key.py and pass --key-file.")

    hashes = registered_hashes(args.device_id)
    if hashes and hashlib.sha256(key.encode()).hexdigest() not in hashes:
        sys.exit(f"That key doesn't match DEVICE_KEYS for {args.device_id} in dashboard/.env (the backend would answer 401).")
    if not hashes:
        print(f"Note: no DEVICE_KEYS entry for {args.device_id} in dashboard/.env yet - add it before starting the backend.")

    if args.keep_wifi:
        old = target.read_text(encoding="utf-8") if target.exists() else ""
        ssid, password = read_define(old, "WIFI_SSID"), read_define(old, "WIFI_PASSWORD")
        if not ssid or not password or ssid == "your-wifi-name":
            sys.exit("No Wi-Fi settings in the current secrets.h to keep. Use --ssid instead.")
    else:
        ssid = args.ssid
        password = getpass.getpass(f"Wi-Fi password for '{ssid}' (not shown): ")
    if not 8 <= len(password) <= 63:
        sys.exit("WPA2 Wi-Fi passwords are 8-63 characters.")

    target.write_text(
        "// Generated by scripts/make_firmware_secrets.py. Gitignored - never commit this file.\n"
        "#pragma once\n\n"
        f"#define WIFI_SSID     {c_string(ssid, 'SSID')}\n"
        f"#define WIFI_PASSWORD {c_string(password, 'Password')}\n\n"
        f"#define BACKEND_HOST  {c_string(host, 'Host')}\n"
        f"#define BACKEND_PORT  {port}\n"
        f"#define BACKEND_HTTPS {https}\n\n"
        f"#define DEVICE_ID     {c_string(args.device_id, 'Device id')}\n"
        f"#define DEVICE_KEY    {c_string(key, 'Key')}\n",
        encoding="utf-8",
    )
    scheme = "https" if https else "http"
    print(f"Wrote {target.relative_to(ROOT)}: Wi-Fi '{ssid}', backend {scheme}://{host}:{port}, device {args.device_id}.")
    print("Now open New_Code.ino in Arduino IDE and upload it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
