"""Makes a device key and the DEVICE_KEYS line for dashboard/.env.

    python scripts/gen_device_key.py sb-esp32-01
    python scripts/gen_device_key.py sim-01 --simulator
"""
from __future__ import annotations

import argparse
import hashlib
import re
import secrets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("device_id")
    parser.add_argument("--simulator", action="store_true", help="key for scripts/simulate_device.py")
    args = parser.parse_args()

    if not re.fullmatch(r"[a-z0-9-]{3,32}", args.device_id):
        parser.error("device_id must be 3-32 chars of a-z, 0-9 and '-'")

    key = secrets.token_urlsafe(32)
    digest = hashlib.sha256(key.encode()).hexdigest()
    var = "SIMULATOR_KEYS" if args.simulator else "DEVICE_KEYS"

    print(f"Device key (keep it secret):\n  {key}\n")
    if args.simulator:
        print(f"Use it with:  python scripts/simulate_device.py --device-id {args.device_id} --key <key>\n")
    else:
        print("For the serial bridge (PowerShell, same terminal):")
        print('  $env:SMARTBUDDY_DEVICE_KEY = "<the key above>"')
        print(f"  dashboard\\.venv\\Scripts\\python scripts\\serial_bridge.py --port COM5 --device-id {args.device_id}\n")
    print("In dashboard/.env (comma-separate multiple devices):")
    print(f"  {var}={args.device_id}:{digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
