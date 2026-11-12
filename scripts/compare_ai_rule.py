"""Compares the forecast-driven fan (AI) with the firmware's temperature rule on real readings.

    dashboard\\.venv\\Scripts\\python scripts\\compare_ai_rule.py
    dashboard\\.venv\\Scripts\\python scripts\\compare_ai_rule.py --horizon 10 --json out.json

Part 1 replays both policies on the recorded temperatures. Each day is predicted by a model trained on the other
days only, so no prediction has seen its own day. The replay can't know how the room would have reacted to a
different fan state, so it compares decisions (timing, switches, fan-on time), not resulting temperatures.
Part 2 uses readings the device sent while the AI really controlled the fan (fan_control = 'ai'), if any.
Only reads the database.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))

from backend.config import load_settings  # noqa: E402
from backend.database import open_database  # noqa: E402
from backend.services.ai_fan import decide  # noqa: E402
from ml.forecast import FEATURES, STEP_S, _candidates, build_features, load_readings, resample  # noqa: E402

ON_C, OFF_C = 26.1, 25.5
LEAD_WINDOW_MIN = 15


def rule(now_c: float, prev: str) -> str:
    if now_c >= ON_C:
        return "on"
    if now_c <= OFF_C:
        return "off"
    return prev


def out_of_sample(series: pd.DataFrame, horizon: int, algo: str) -> pd.DataFrame:
    feats = build_features(series, horizon)
    feats = feats.assign(day=feats.index.date)
    have_x = feats.dropna(subset=FEATURES)
    train_all = have_x.dropna(subset=["target_temperature_c"])
    parts = []
    for day, g in have_x.groupby("day"):
        train = train_all[train_all["day"] != day]
        if len(train) < 100:
            continue
        model = _candidates()[algo]
        model.fit(train[FEATURES].to_numpy(float), train["target_temperature_c"].to_numpy(float))
        g = g.copy()
        g["pred"] = g["temperature_c"] + model.predict(g[FEATURES].to_numpy(float))
        parts.append(g)
    return pd.concat(parts) if parts else pd.DataFrame()


def replay(g: pd.DataFrame) -> pd.DataFrame:
    start = "on" if g["fan_on"].iloc[0] >= 0.5 else "off"
    r_state, a_state = start, start
    r_out, a_out = [], []
    for now_c, pred in zip(g["temperature_c"], g["pred"]):
        r_state = rule(now_c, r_state)
        a_state = decide(now_c, pred, a_state, ON_C, OFF_C)
        r_out.append(r_state == "on")
        a_out.append(a_state == "on")
    return g.assign(rule_on=r_out, ai_on=a_out)


def switch_ons(on: pd.Series) -> list[pd.Timestamp]:
    v = on.to_numpy()
    return [on.index[i] for i in range(1, len(v)) if v[i] and not v[i - 1]]


def compare(rep: pd.DataFrame, horizon: int) -> dict:
    step_min = STEP_S / 60
    out = {"samples": int(len(rep)), "hours": round(len(rep) * step_min / 60, 2)}
    for name in ("rule", "ai"):
        col = rep[f"{name}_on"]
        out[name] = {
            "fan_on_min": round(float(col.sum()) * step_min, 1),
            "switch_ons": int(sum(len(switch_ons(g[f"{name}_on"])) for _, g in rep.groupby("segment"))),
        }
    out["agreement_pct"] = round(float((rep["rule_on"] == rep["ai_on"]).mean()) * 100, 1)

    leads, matched, false_starts = [], 0, 0
    for _, g in rep.groupby("segment"):
        rule_ons = switch_ons(g["rule_on"])
        ai_ons = switch_ons(g["ai_on"])
        for t in rule_ons:
            before = [a for a in ai_ons if t - pd.Timedelta(minutes=LEAD_WINDOW_MIN) <= a <= t]
            if before:
                matched += 1
                leads.append((t - before[0]).total_seconds() / 60)
        for a in ai_ons:
            later = [t for t in rule_ons if a <= t <= a + pd.Timedelta(minutes=horizon + 5)]
            if not later and g.loc[a:a + pd.Timedelta(minutes=horizon + 5), "temperature_c"].max() < ON_C:
                false_starts += 1
    out["rule_switch_ons"] = int(sum(len(switch_ons(g["rule_on"])) for _, g in rep.groupby("segment")))
    out["ai_started_before_rule"] = matched
    out["lead_min_median"] = round(float(np.median(leads)), 1) if leads else None
    out["lead_min_range"] = [round(min(leads), 1), round(max(leads), 1)] if leads else None
    out["ai_false_starts"] = false_starts

    warm = rep[rep["temperature_c"] >= ON_C]
    out["warm_samples"] = int(len(warm))
    out["fan_on_when_warm_pct"] = {
        "rule": round(float(warm["rule_on"].mean()) * 100, 1) if len(warm) else None,
        "ai": round(float(warm["ai_on"].mean()) * 100, 1) if len(warm) else None,
    }
    return out


def accuracy(rep: pd.DataFrame, horizon: int) -> dict:
    ok = rep.dropna(subset=["target_temperature_c"])
    actual = ok["temperature_c"] + ok["target_temperature_c"]
    per_day = {}
    for day, g in ok.groupby("day"):
        a = g["temperature_c"] + g["target_temperature_c"]
        per_day[str(day)] = {
            "n": int(len(g)),
            "mae": round(float((g["pred"] - a).abs().mean()), 3),
            "mae_no_change": round(float((g["temperature_c"] - a).abs().mean()), 3),
        }
    return {
        "horizon_min": horizon,
        "n": int(len(ok)),
        "mae": round(float((ok["pred"] - actual).abs().mean()), 3),
        "rmse": round(float(np.sqrt(((ok["pred"] - actual) ** 2).mean())), 3),
        "mae_no_change": round(float((ok["temperature_c"] - actual).abs().mean()), 3),
        "rmse_no_change": round(float(np.sqrt(((ok["temperature_c"] - actual) ** 2).mean())), 3),
        "per_day": per_day,
    }


def live(conn) -> dict:
    try:
        rows = conn.execute(
            "SELECT measured_ms, temperature_c, fan_on, fan_control FROM sensor_readings "
            "WHERE is_simulated = 0 AND valid = 1 AND fan_control IS NOT NULL ORDER BY measured_ms"
        ).fetchall()
    except Exception:
        # database not migrated yet (backend older than firmware 1.6.0 support)
        return {"available": False}
    if not rows:
        return {"available": False}
    df = pd.DataFrame([tuple(r) for r in rows], columns=["ms", "temp", "fan", "control"])
    out = {"available": True}
    for ctl, g in df.groupby("control"):
        gaps = g["ms"].diff().fillna(2000).clip(upper=10_000) / 60_000
        fan = g["fan"].to_numpy()
        out[ctl] = {
            "readings": int(len(g)),
            "minutes": round(float(gaps.sum()), 1),
            "fan_on_pct": round(float(g["fan"].mean()) * 100, 1),
            "switch_ons": int(((fan[1:] == 1) & (fan[:-1] == 0)).sum()),
            "temp_mean": round(float(g["temp"].mean()), 2),
            "temp_max": round(float(g["temp"].max()), 2),
            "minutes_at_or_above_on": round(float(gaps[g["temp"] >= ON_C].sum()), 1),
        }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--horizon", type=int, default=5)
    ap.add_argument("--algo", default="linear", choices=["random_forest", "linear"])
    ap.add_argument("--json", type=Path, help="also write the results here")
    args = ap.parse_args()

    db = open_database(load_settings())
    try:
        with db.session() as conn:
            readings = load_readings(conn)
        with db.session() as conn:
            live_res = live(conn)
    finally:
        db.close()

    series = resample(readings)
    rep = out_of_sample(series, args.horizon, args.algo)
    if rep.empty:
        print("Not enough data for a leave-one-day-out replay.")
        return 1
    rep = pd.concat(replay(g) for _, g in rep.groupby("segment"))
    result = {
        "algo": args.algo,
        "accuracy": accuracy(rep, args.horizon),
        "replay": compare(rep, args.horizon),
        "live": live_res,
    }
    print(json.dumps(result, indent=2))
    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
