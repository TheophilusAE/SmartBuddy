"""Trains the comfort model and only deploys it if it beats the baseline.

    python -m ml.train_model
    python -m ml.train_model --dataset path.csv --plot
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.model_selection import GroupShuffleSplit
from sklearn.tree import DecisionTreeRegressor

from .common import (
    BASE_FEATURES, CURRENT_FILE, DEFAULT_DATASET, GROUP, LAST_TRAINING_FILE, MIN_GROUPS, MIN_LABELS, MODELS_DIR,
    RANDOM_FOREST_MIN_LABELS, RANDOM_SEED, TARGET, file_sha256,
)
from .prepare_dataset import clean

MIN_TEST_ROWS = 5

LIMITATIONS = [
    "Trained only on the ratings collected in this project; it reflects those users and rooms, nothing more.",
    "Comfort also depends on clothing, activity, air movement and mood, none of which are measured.",
    "Small datasets give unstable metrics; treat MAE/RMSE as rough indicators.",
    "The deployed model is refit on all rows after evaluation, so the reported metrics come from the held-out split.",
    "This is not a medical or thermal-comfort standard (e.g. ISO 7730) assessment.",
]


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    return {
        "mae": round(float(mean_absolute_error(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
    }


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def train(df: pd.DataFrame, models_dir: Path = MODELS_DIR, use_motion: bool = False,
          dataset_name: str = "", plot: bool = False) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    version = now.strftime("v%Y%m%d-%H%M%S")
    features = list(BASE_FEATURES)
    if use_motion:
        df = df.dropna(subset=["motion_detected"])
        features.append("motion_detected")

    n = len(df)
    n_groups = int(df[GROUP].nunique()) if n else 0
    summary = {
        "dataset": dataset_name,
        "rows": n,
        "sessions": n_groups,
        "rating_counts": {str(k): int(v) for k, v in df[TARGET].value_counts().sort_index().items()} if n else {},
        "sources": {str(k): int(v) for k, v in df["source"].value_counts().items()} if n else {},
        "feature_ranges": {
            f: {"min": float(df[f].min()), "max": float(df[f].max())} for f in features
        } if n else {},
    }
    result: dict[str, Any] = {
        "attempted_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attempt_version": version,
        "features": features,
        "target": TARGET,
        "summary": summary,
        "requirements": {"min_labels": MIN_LABELS, "min_sessions": MIN_GROUPS},
    }

    if n < MIN_LABELS or n_groups < MIN_GROUPS:
        result["status"] = "insufficient_data"
        result["message"] = (
            f"Need at least {MIN_LABELS} labelled rows from {MIN_GROUPS}+ sessions; "
            f"have {n} rows from {n_groups} session(s)."
        )
        _write_json(models_dir / LAST_TRAINING_FILE, result)
        return result

    X = df[features].to_numpy(dtype=float)
    y = df[TARGET].to_numpy(dtype=float)
    groups = df[GROUP].to_numpy()

    splitter = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=RANDOM_SEED)
    train_idx, test_idx = next(splitter.split(X, y, groups))
    if len(test_idx) < MIN_TEST_ROWS or len(train_idx) < MIN_LABELS * 0.5:
        result["status"] = "insufficient_data"
        result["message"] = "The grouped split left too few rows on one side; collect more sessions."
        _write_json(models_dir / LAST_TRAINING_FILE, result)
        return result

    X_train, X_test, y_train, y_test = X[train_idx], X[test_idx], y[train_idx], y[test_idx]

    candidates: dict[str, Any] = {
        "baseline_mean": DummyRegressor(strategy="mean"),
        "decision_tree": DecisionTreeRegressor(max_depth=4, min_samples_leaf=3, random_state=RANDOM_SEED),
    }
    if n >= RANDOM_FOREST_MIN_LABELS:
        candidates["random_forest"] = RandomForestRegressor(
            n_estimators=200, max_depth=6, min_samples_leaf=3, random_state=RANDOM_SEED, n_jobs=1
        )

    metrics: dict[str, dict[str, float]] = {}
    predictions: dict[str, np.ndarray] = {}
    for name, model in candidates.items():
        model.fit(X_train, y_train)
        pred = np.clip(model.predict(X_test), 1, 5)
        predictions[name] = pred
        metrics[name] = _metrics(y_test, pred)

    baseline_mae = metrics["baseline_mean"]["mae"]
    best_name = min((k for k in metrics if k != "baseline_mean"), key=lambda k: metrics[k]["mae"])
    beats_baseline = metrics[best_name]["mae"] < baseline_mae

    result.update({
        "split": {
            "method": "GroupShuffleSplit by session",
            "test_size": 0.25,
            "random_state": RANDOM_SEED,
            "train_rows": int(len(train_idx)),
            "test_rows": int(len(test_idx)),
            "train_sessions": int(len(set(groups[train_idx]))),
            "test_sessions": int(len(set(groups[test_idx]))),
        },
        "metrics": metrics,
        "best_candidate": best_name,
        "beats_baseline": beats_baseline,
        "test_predictions": [
            {"actual": float(a), "predicted": round(float(p), 3), "baseline": round(float(b), 3)}
            for a, p, b in zip(y_test, predictions[best_name], predictions["baseline_mean"])
        ],
        "limitations": LIMITATIONS,
        "sklearn_version": sklearn.__version__,
    })

    if not beats_baseline:
        result["status"] = "no_improvement"
        result["message"] = (
            f"Best model ({best_name}, MAE {metrics[best_name]['mae']}) did not beat the baseline "
            f"(MAE {baseline_mae}). Nothing deployed."
        )
        _write_json(models_dir / LAST_TRAINING_FILE, result)
        return result

    final = candidates[best_name].__class__(**candidates[best_name].get_params())
    final.fit(X, y)
    models_dir.mkdir(parents=True, exist_ok=True)
    model_file = f"comfort_{version}.joblib"
    joblib.dump(final, models_dir / model_file)

    result["status"] = "deployed"
    result["model_version"] = version
    result["model_file"] = model_file
    result["algorithm"] = best_name
    result["sha256"] = file_sha256(models_dir / model_file)
    result["refit_on_all_rows"] = True

    if plot:
        result["plot_file"] = _plot(models_dir, version, y_test, predictions[best_name], best_name)

    _write_json(models_dir / LAST_TRAINING_FILE, result)
    _write_json(models_dir / CURRENT_FILE, result)
    return result


def _plot(models_dir: Path, version: str, actual: np.ndarray, predicted: np.ndarray, name: str) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return None
    fig, ax = plt.subplots(figsize=(4.5, 4.5))
    ax.scatter(actual, predicted, alpha=0.7)
    ax.plot([1, 5], [1, 5], linestyle="--", linewidth=1)
    ax.set_xlim(0.8, 5.2)
    ax.set_ylim(0.8, 5.2)
    ax.set_xlabel("Actual rating")
    ax.set_ylabel("Predicted rating")
    ax.set_title(f"{name} - held-out sessions")
    fig.tight_layout()
    out = f"actual_vs_predicted_{version}.png"
    fig.savefig(models_dir / out, dpi=120)
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    parser.add_argument("--with-motion", action="store_true", help="also use the PIR motion flag as a feature")
    parser.add_argument("--plot", action="store_true", help="save an actual-vs-predicted PNG")
    parser.add_argument("--publish", action="store_true",
                        help="also save the result in the database from .env (so Render uses the model too)")
    args = parser.parse_args(argv)

    if not args.dataset.is_file():
        print(f"error: {args.dataset} not found. Run `python -m ml.prepare_dataset --db data/smartbuddy.db` first.",
              file=sys.stderr)
        return 2

    df, _ = clean(pd.read_csv(args.dataset, dtype=str))
    result = train(df, args.models_dir, args.with_motion, args.dataset.name, args.plot)
    printable = {k: v for k, v in result.items() if k not in {"test_predictions", "limitations"}}
    print(json.dumps(printable, indent=2))
    if args.publish:
        try:
            publish(result, args.models_dir)
        except Exception as exc:
            print(f"error: could not save to the database ({type(exc).__name__})", file=sys.stderr)
            return 1
        print("saved to the database" + (" and set as the active model" if result["status"] == "deployed" else ""))
    return 0 if result["status"] in {"deployed", "no_improvement", "insufficient_data"} else 1


def publish(result: dict[str, Any], models_dir: Path) -> None:
    from backend.config import load_settings
    from backend.database import open_database

    from .store import save_attempt, save_model

    settings = load_settings()
    db = open_database(settings)
    try:
        db.init()
        with db.transaction() as conn:
            save_attempt(conn, result)
            if result["status"] == "deployed":
                save_model(conn, result, models_dir)
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
