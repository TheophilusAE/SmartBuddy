"""Trains the short-term room forecast (temperature and humidity a few minutes ahead) from real readings.

    python -m ml.forecast              (database from .env)
    python -m ml.forecast --publish    (also save it in the database so Render uses it)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np
import pandas as pd

from .common import CURRENT_FILE, FORECAST_FILE_RE, LAST_TRAINING_FILE, MODELS_DIR, RANDOM_SEED, file_sha256
from .inference import ModelUnavailable

FORECAST_DIR = MODELS_DIR / "forecast"
STEP_S = 30
HORIZON_MIN = 5
GAP_S = 60
HISTORY_MIN = 5
TARGETS = ["temperature_c", "humidity_pct"]
# only short-term changes, fan and motion: absolute levels differ from day to day and made the model
# worse than "no change" on days it had not seen
FEATURES = ["t_d1", "t_d5", "h_d1", "h_d5", "fan_on", "motion_5"]
MIN_TRAIN_ROWS = 100
MIN_TEST_ROWS = 30
TEST_SHARE = 0.3
MAX_TEST_POINTS = 300

LIMITATIONS = [
    "Trained on a few hours of recordings from one room on a few days; other times of day or seasons may differ.",
    "It only knows what the sensors see. People, doors or cooking can change the room faster than it expects.",
    "The test period is short and its samples overlap in time, so the error is a rough indicator.",
    "The deployed model is refit on all rows after evaluation, so the reported metrics come from the held-out period.",
]


def load_readings(conn, since_ms: Optional[int] = None, device_id: Optional[str] = None) -> pd.DataFrame:
    sql = ("SELECT measured_ms, temperature_c, humidity_pct, light_pct, motion_detected, fan_on FROM sensor_readings "
           "WHERE is_simulated = 0 AND valid = 1 AND timestamp_trusted = 1")
    params: list[Any] = []
    if since_ms is not None:
        sql += " AND measured_ms >= ?"
        params.append(since_ms)
    if device_id is not None:
        sql += " AND device_id = ?"
        params.append(device_id)
    rows = conn.execute(sql + " ORDER BY measured_ms", tuple(params)).fetchall()
    cols = ["measured_ms", "temperature_c", "humidity_pct", "light_pct", "motion_detected", "fan_on"]
    return pd.DataFrame([tuple(r) for r in rows], columns=cols)


def resample(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    df = df.copy()
    df["ts"] = pd.to_datetime(df["measured_ms"], unit="ms", utc=True)
    df = df.sort_values("ts")
    # a gap means the device was off, so never interpolate across it
    df["segment"] = (df["ts"].diff().dt.total_seconds() > GAP_S).cumsum()
    cols = ["temperature_c", "humidity_pct", "light_pct", "motion_detected", "fan_on"]
    parts = []
    for seg, g in df.groupby("segment"):
        r = g.set_index("ts")[cols].astype(float).resample(f"{STEP_S}s").mean()
        r = r.interpolate(limit=2, limit_area="inside")
        r["segment"] = seg
        parts.append(r)
    return pd.concat(parts)


def build_features(series: pd.DataFrame, horizon_min: int = HORIZON_MIN) -> pd.DataFrame:
    if series.empty:
        return pd.DataFrame(columns=[*FEATURES, *[f"target_{t}" for t in TARGETS]])
    per_min = 60 // STEP_S
    ahead = horizon_min * per_min
    parts = []
    for _, g in series.groupby("segment"):
        g = g.copy()
        g["t_d1"] = g["temperature_c"] - g["temperature_c"].shift(per_min)
        g["t_d5"] = g["temperature_c"] - g["temperature_c"].shift(HISTORY_MIN * per_min)
        g["h_d1"] = g["humidity_pct"] - g["humidity_pct"].shift(per_min)
        g["h_d5"] = g["humidity_pct"] - g["humidity_pct"].shift(HISTORY_MIN * per_min)
        g["motion_5"] = g["motion_detected"].rolling(HISTORY_MIN * per_min, min_periods=per_min).mean()
        for t in TARGETS:
            g[f"target_{t}"] = g[t].shift(-ahead) - g[t]
        parts.append(g)
    return pd.concat(parts)


def _metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    return {"mae": round(float(np.mean(np.abs(y - p))), 4), "rmse": round(float(np.sqrt(np.mean((y - p) ** 2))), 4)}


def _candidates() -> dict[str, Any]:
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return {
        "linear": make_pipeline(StandardScaler(), Ridge(alpha=1.0)),
        "random_forest": RandomForestRegressor(n_estimators=200, max_depth=6, min_samples_leaf=10,
                                               random_state=RANDOM_SEED, n_jobs=1),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def train_forecast(readings: pd.DataFrame, models_dir: Path = FORECAST_DIR,
                   horizon_min: int = HORIZON_MIN) -> dict[str, Any]:
    import sklearn

    now = datetime.now(timezone.utc)
    version = now.strftime("v%Y%m%d-%H%M%S")
    series = resample(readings)
    data = build_features(series, horizon_min).dropna(subset=[*FEATURES, *[f"target_{t}" for t in TARGETS]])
    data = data.sort_index()
    data = data.assign(day=data.index.date) if len(data) else data.assign(day=[])

    result: dict[str, Any] = {
        "attempted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attempt_version": version,
        "kind": "forecast",
        "horizon_min": horizon_min,
        "step_s": STEP_S,
        "features": FEATURES,
        "targets": TARGETS,
        "summary": {
            "readings": int(len(readings)),
            "hours_recorded": round(len(series) * STEP_S / 3600, 2) if len(series) else 0,
            "segments": int(series["segment"].nunique()) if len(series) else 0,
            "samples": int(len(data)),
            "days": sorted({str(d) for d in data["day"]}) if len(data) else [],
        },
        "requirements": {"min_train_rows": MIN_TRAIN_ROWS, "min_test_rows": MIN_TEST_ROWS},
    }

    cut = int(len(data) * (1 - TEST_SHARE))
    test = data.iloc[cut:]
    # drop training rows whose target lies inside the test period, so nothing leaks
    train = data.iloc[:cut]
    if len(test):
        train = train[train.index + pd.Timedelta(minutes=horizon_min) < test.index[0]]
    if len(test) < MIN_TEST_ROWS or len(train) < MIN_TRAIN_ROWS:
        result["status"] = "insufficient_data"
        result["message"] = (
            f"Need {MIN_TRAIN_ROWS}+ training and {MIN_TEST_ROWS}+ test samples; have {len(train)} and {len(test)} "
            f"({len(data)} in total). Each sample needs {HISTORY_MIN + horizon_min} min of continuous recording, "
            "so keep the device running for longer stretches."
        )
        _write_json(models_dir / LAST_TRAINING_FILE, result)
        return result

    X_train, X_test = train[FEATURES].to_numpy(float), test[FEATURES].to_numpy(float)

    metrics: dict[str, dict[str, dict[str, float]]] = {}
    best: dict[str, str] = {}
    beats: dict[str, bool] = {}
    preds: dict[str, np.ndarray] = {}
    chosen: dict[str, Any] = {}
    for t in TARGETS:
        y_train, y_test = train[f"target_{t}"].to_numpy(float), test[f"target_{t}"].to_numpy(float)
        metrics[t] = {"persistence": _metrics(y_test, np.zeros_like(y_test))}
        fitted = {}
        for name, model in _candidates().items():
            model.fit(X_train, y_train)
            p = model.predict(X_test)
            metrics[t][name] = _metrics(y_test, p)
            fitted[name] = (model, p)
        name = min(fitted, key=lambda k: metrics[t][k]["mae"])
        best[t] = name
        beats[t] = metrics[t][name]["mae"] < metrics[t]["persistence"]["mae"]
        preds[t] = fitted[name][1] if beats[t] else np.zeros(len(test))
        chosen[t] = name if beats[t] else None

    step = max(1, len(test) // MAX_TEST_POINTS)
    sample = test.iloc[::step]
    idx = np.arange(len(test))[::step]
    result.update({
        "split": {
            "method": f"chronological: first {round((1 - TEST_SHARE) * 100)}% in time to train, last "
                      f"{round(TEST_SHARE * 100)}% to test, with a {horizon_min} min gap",
            "train_rows": int(len(train)),
            "test_rows": int(len(test)),
            "train_until": train.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "test_from": test.index[0].strftime("%Y-%m-%dT%H:%M:%SZ"),
            "test_to": test.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "metrics": metrics,
        "best_candidate": best,
        "beats_baseline": beats,
        "test_series": [
            {
                "at": ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "now": round(float(row["temperature_c"]), 2),
                "actual": round(float(row["temperature_c"] + row["target_temperature_c"]), 2),
                "predicted": round(float(row["temperature_c"] + preds["temperature_c"][i]), 2),
            }
            for (ts, row), i in zip(sample.iterrows(), idx)
        ],
        "limitations": LIMITATIONS,
        "sklearn_version": sklearn.__version__,
    })

    if not beats["temperature_c"]:
        result["status"] = "no_improvement"
        result["message"] = (
            f"Best temperature model ({best['temperature_c']}, MAE {metrics['temperature_c'][best['temperature_c']]['mae']} °C) "
            f"did not beat 'no change' (MAE {metrics['temperature_c']['persistence']['mae']} °C). Nothing deployed."
        )
        _write_json(models_dir / LAST_TRAINING_FILE, result)
        return result

    X_all = data[FEATURES].to_numpy(float)
    estimators = {}
    for t in TARGETS:
        if chosen[t] is None:
            estimators[t] = None
            continue
        model = _candidates()[chosen[t]]
        model.fit(X_all, data[f"target_{t}"].to_numpy(float))
        estimators[t] = model

    models_dir.mkdir(parents=True, exist_ok=True)
    model_file = f"forecast_{version}.joblib"
    joblib.dump(estimators, models_dir / model_file)
    result.update({
        "status": "deployed",
        "model_version": f"forecast-{version}",
        "model_file": model_file,
        "algorithm": ", ".join(f"{t}: {chosen[t] or 'no change'}" for t in TARGETS),
        "sha256": file_sha256(models_dir / model_file),
        "refit_on_all_rows": True,
    })
    _write_json(models_dir / LAST_TRAINING_FILE, result)
    _write_json(models_dir / CURRENT_FILE, result)
    return result


@dataclass
class ForecastModel:
    version: str
    estimators: dict[str, Any]
    metadata: dict[str, Any]

    def predict(self, feats: dict[str, float]) -> dict[str, Optional[float]]:
        row = np.array([[float(feats[f]) for f in FEATURES]])
        if not np.isfinite(row).all():
            raise ValueError("features are incomplete")
        out: dict[str, Optional[float]] = {}
        for t in TARGETS:
            est = self.estimators.get(t)
            out[t] = None if est is None else round(float(feats[t] + est.predict(row)[0]), 2)
        return out


def load_forecast(models_dir: Path = FORECAST_DIR) -> ForecastModel:
    path = models_dir / CURRENT_FILE
    if not path.is_file():
        raise ModelUnavailable("no deployed forecast")
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ModelUnavailable("forecast metadata unreadable")
    if meta.get("status") != "deployed" or meta.get("kind") != "forecast":
        raise ModelUnavailable("no deployed forecast")
    name = str(meta.get("model_file", ""))
    if not FORECAST_FILE_RE.match(name):
        raise ModelUnavailable("model file name in metadata is not one this project produces")
    file = (models_dir / name).resolve()
    if file.parent != models_dir.resolve() or not file.is_file():
        raise ModelUnavailable("model file missing")
    if file_sha256(file) != meta.get("sha256"):
        raise ModelUnavailable("model file hash does not match its metadata - refusing to load")
    if meta.get("features") != FEATURES:
        raise ModelUnavailable("forecast was trained with different features")
    return ForecastModel(meta["model_version"], joblib.load(file), meta)


def latest_features(conn, device_id: Optional[str] = None, now_ms: Optional[int] = None) -> Optional[dict[str, Any]]:
    now_ms = now_ms or int(time.time() * 1000)
    df = load_readings(conn, now_ms - (HISTORY_MIN + 2) * 60_000, device_id)
    if df.empty or now_ms - int(df["measured_ms"].iloc[-1]) > 120_000:
        return None
    feats = build_features(resample(df)).dropna(subset=FEATURES)
    if feats.empty:
        return None
    last = feats.iloc[-1]
    if last["segment"] != feats["segment"].max():
        return None
    out = {f: float(last[f]) for f in [*FEATURES, *TARGETS]}
    out["at"] = feats.index[-1].strftime("%Y-%m-%dT%H:%M:%SZ")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--models-dir", type=Path, default=FORECAST_DIR)
    parser.add_argument("--publish", action="store_true", help="also save the result in the database from .env")
    parser.add_argument("--horizon", type=int, default=HORIZON_MIN, choices=[5, 10, 15, 30],
                        help="minutes ahead to forecast (longer needs longer continuous recordings)")
    args = parser.parse_args(argv)

    from backend.config import load_settings
    from backend.database import open_database

    db = open_database(load_settings())
    try:
        with db.session() as conn:
            readings = load_readings(conn)
        result = train_forecast(readings, args.models_dir, args.horizon)
        print(json.dumps({k: v for k, v in result.items() if k not in {"test_series", "limitations"}}, indent=2))
        if args.publish:
            from .store import save_attempt, save_model

            db.init()
            with db.transaction() as conn:
                save_attempt(conn, result, "forecast")
                if result["status"] == "deployed":
                    save_model(conn, result, args.models_dir, "forecast")
            print("saved to the database" + (" and set as the active forecast" if result["status"] == "deployed" else ""))
    except Exception as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
