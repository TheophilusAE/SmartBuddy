"""Test the deployed model on another labelled CSV.

    python -m ml.evaluate_model --dataset data/processed/new_ratings.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from .common import MODELS_DIR, TARGET
from .inference import ModelUnavailable, load_model
from .prepare_dataset import clean


def evaluate(df: pd.DataFrame, models_dir: Path = MODELS_DIR) -> dict:
    model = load_model(models_dir)
    df = df.dropna(subset=model.features)
    if len(df) == 0:
        return {"status": "no_rows", "model_version": model.version}

    y = df[TARGET].to_numpy(dtype=float)
    pred = np.array([model.predict(row) for row in df[model.features].to_dict("records")])

    counts = model.metadata.get("summary", {}).get("rating_counts", {})
    total = sum(counts.values())
    train_mean = sum(int(k) * v for k, v in counts.items()) / total if total else 3.0
    base = np.full_like(y, train_mean)

    return {
        "status": "ok",
        "model_version": model.version,
        "rows": int(len(df)),
        "model": {
            "mae": round(float(mean_absolute_error(y, pred)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 4),
        },
        "baseline_training_mean": {
            "value": round(train_mean, 3),
            "mae": round(float(mean_absolute_error(y, base)), 4),
            "rmse": round(float(np.sqrt(mean_squared_error(y, base))), 4),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--models-dir", type=Path, default=MODELS_DIR)
    args = parser.parse_args(argv)
    try:
        df, _ = clean(pd.read_csv(args.dataset, dtype=str))
        print(json.dumps(evaluate(df, args.models_dir), indent=2))
    except ModelUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
