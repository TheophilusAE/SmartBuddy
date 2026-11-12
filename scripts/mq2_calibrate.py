"""Finds the MQ-2 clean-air baseline from real readings in the database and suggests alarm thresholds.

    dashboard\\.venv\\Scripts\\python scripts\\mq2_calibrate.py
    dashboard\\.venv\\Scripts\\python scripts\\mq2_calibrate.py --settle-min 20 --since 2026-11-01

Only reads the database. Values are raw ADC counts (0-4095), not ppm.
"""
from __future__ import annotations

import argparse
import math
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))

from backend.config import load_settings  # noqa: E402
from backend.database import Database, open_database  # noqa: E402

CURRENT_WARNING = 420
MIN_MARGIN = 300


def pct(values: list[int], p: float) -> float:
    s = sorted(values)
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def robust_sigma(values: list[int]) -> float:
    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    return 1.4826 * mad


def round_up(x: float, step: int = 10) -> int:
    return int(math.ceil(x / step) * step)


def load_rows(conn, since_ms: int | None):
    sql = ("SELECT boot_id, measured_ms, uptime_ms, gas_adc, gas_warning_local, temperature_c, humidity_pct "
           "FROM sensor_readings WHERE is_simulated = 0 AND mq2_status = 'ok' AND gas_adc IS NOT NULL")
    params: tuple = ()
    if since_ms is not None:
        sql += " AND measured_ms >= ?"
        params = (since_ms,)
    return conn.execute(sql + " ORDER BY measured_ms", params).fetchall()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, help="read this SQLite file instead")
    parser.add_argument("--settle-min", type=float, default=20, help="skip this many minutes after each power-on")
    parser.add_argument("--since", help="only use readings from this UTC time (YYYY-MM-DD or YYYY-MM-DDTHH:MM)")
    parser.add_argument("--min-boot-readings", type=int, default=100)
    args = parser.parse_args()

    since_ms = None
    if args.since:
        fmt = "%Y-%m-%dT%H:%M" if "T" in args.since else "%Y-%m-%d"
        since_ms = int(datetime.strptime(args.since, fmt).replace(tzinfo=timezone.utc).timestamp() * 1000)

    if args.db:
        db = Database(args.db)
    else:
        db = open_database(load_settings())
    try:
        with db.session() as conn:
            rows = load_rows(conn, since_ms)
    finally:
        db.close()

    if not rows:
        print("No real MQ-2 readings with status ok found.")
        return 1

    settle_ms = args.settle_min * 60_000
    boots: dict[str, list] = {}
    for r in rows:
        boots.setdefault(r["boot_id"], []).append(r)

    clean: list[int] = []
    per_boot = []
    skipped_warm = skipped_alarm = 0
    for boot_id, items in boots.items():
        first_ms = items[0]["measured_ms"]
        vals, temps, hums = [], [], []
        for r in items:
            # uptime is missing on some bridge rows, then use time since the first reading of that boot
            age = r["uptime_ms"] if r["uptime_ms"] is not None else r["measured_ms"] - first_ms
            if age < settle_ms:
                skipped_warm += 1
                continue
            if r["gas_warning_local"]:
                skipped_alarm += 1
                continue
            vals.append(r["gas_adc"])
            if r["temperature_c"] is not None:
                temps.append(r["temperature_c"])
            if r["humidity_pct"] is not None:
                hums.append(r["humidity_pct"])
        if len(vals) < args.min_boot_readings:
            continue
        start = datetime.fromtimestamp(first_ms / 1000, timezone.utc).astimezone()
        hours = (items[-1]["measured_ms"] - first_ms) / 3_600_000
        per_boot.append((start, hours, vals, temps, hums))
        clean.extend(vals)

    if not clean:
        print(f"Not enough settled readings (need {args.min_boot_readings}+ per power-on after {args.settle_min:g} min).")
        return 1

    print(f"Real readings with MQ-2 ok : {len(rows)}")
    print(f"Skipped (first {args.settle_min:g} min)   : {skipped_warm}")
    print(f"Skipped (local alarm on)   : {skipped_alarm}")
    print(f"Used as clean air          : {len(clean)} from {len(per_boot)} power-on(s)\n")

    print(f"{'power-on (local time)':<22}{'hours':>6}{'n':>7}{'median':>8}{'sigma':>7}{'p1':>7}{'p99':>7}{'max':>6}"
          f"{'temp C':>8}{'RH %':>7}")
    medians = []
    for start, hours, vals, temps, hums in per_boot:
        med = statistics.median(vals)
        medians.append(med)
        t = f"{statistics.mean(temps):.1f}" if temps else "-"
        h = f"{statistics.mean(hums):.0f}" if hums else "-"
        print(f"{start:%Y-%m-%d %H:%M}{'':<6}{hours:>6.1f}{len(vals):>7}{med:>8.0f}{robust_sigma(vals):>7.1f}"
              f"{pct(vals, 1):>7.0f}{pct(vals, 99):>7.0f}{max(vals):>6}{t:>8}{h:>7}")

    baseline = statistics.median(clean)
    sigma = robust_sigma(clean)
    p999 = pct(clean, 99.9)
    drift = max(medians) - min(medians)
    spikes = sum(1 for v in clean if v > baseline + 8 * max(sigma, 1))

    warning = round_up(max(max(medians) + 5 * sigma, p999 + 50, baseline + MIN_MARGIN))
    warning = min(warning, 4000)
    clear = warning - round_up(max(100, 2 * sigma))

    print(f"\nBaseline (median)   : {baseline:.0f}")
    print(f"Noise (robust sigma): {sigma:.1f}")
    print(f"Day-to-day drift    : {drift:.0f}  (highest - lowest power-on median)")
    print(f"p99.9 of clean air  : {p999:.0f}")
    print(f"Spikes > base+8sig  : {spikes}  (cooking, tests, someone near the sensor?)")

    above_now = sum(1 for v in clean if v > CURRENT_WARNING) / len(clean) * 100
    print(f"\nCurrent threshold {CURRENT_WARNING}: {CURRENT_WARNING - baseline:+.0f} above baseline, "
          f"{above_now:.2f}% of clean readings above it")

    # sar adc ending on ...111111111 (1535, 2047, 2559...) means the pin is not sampled properly
    stuck = sum(1 for v in clean if (v + 1) % 512 == 0) / len(clean) * 100
    print(f"Stuck codes (x*512-1): {stuck:.1f}%")
    if stuck > 5 or sigma > 100:
        print("\nNOT CALIBRATING: the signal is too noisy / stuck on ADC codes for a clean-air sensor.")
        print("Fix the AO -> divider -> GPIO34 path first (100 nF from GPIO34 to GND, smaller divider")
        print("resistors, solid GND and 5 V heater supply), collect new data, then run this again with --since.")
        return 2
    print("\nSuggested")
    print(f"  firmware : MQ2_ALARM_THRESHOLD = {warning};  MQ2_ALARM_HYSTERESIS = {warning - clear};")
    print(f"  .env     : GAS_WARNING_ADC={warning}  GAS_CLEAR_ADC={clear}")
    if spikes:
        print("\nThere are spikes in the 'clean' data. If they were real smoke/gas tests, rerun with --since to skip them.")
    if baseline < 50:
        print("\nBaseline is close to 0, check the AO wiring and divider before trusting this.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
