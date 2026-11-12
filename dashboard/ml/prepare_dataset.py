"""Builds the comfort dataset from the ratings in the database (or a CSV).

    python -m ml.prepare_dataset                  (the database in .env, SQLite or Supabase)
    python -m ml.prepare_dataset --db data/smartbuddy.db
    python -m ml.prepare_dataset --csv data/raw/my_labels.csv
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import pandas as pd

from .common import (
    BASE_FEATURES, DATASET_COLUMNS, DEFAULT_DATASET, FEATURE_RANGES, GROUP, MAX_CONTEXT_AGE_S, TARGET, TARGET_RANGE,
    TIME,
)

MAX_CSV_BYTES = 20 * 1024 * 1024


FEEDBACK_COLUMNS = ["created_at", "user_id", "temperature_c", "humidity_pct", "light_pct", "motion_detected",
                    "rating", "context_simulated"]


def _feedback_query(include_simulated: bool) -> str:
    query = (
        f"SELECT {', '.join(FEEDBACK_COLUMNS)} FROM comfort_feedback WHERE temperature_c IS NOT NULL "
        "AND humidity_pct IS NOT NULL AND light_pct IS NOT NULL AND context_age_s IS NOT NULL AND context_age_s <= ?"
    )
    if not include_simulated:
        query += " AND context_simulated = 0"
    return query


def from_database(db_path: Path, include_simulated: bool = False) -> pd.DataFrame:
    uri = f"file:{db_path.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        rows = conn.execute(_feedback_query(include_simulated), (MAX_CONTEXT_AGE_S,)).fetchall()
    finally:
        conn.close()
    return _to_dataset(pd.DataFrame([tuple(r) for r in rows], columns=FEEDBACK_COLUMNS))


def from_connection(conn, include_simulated: bool = False) -> pd.DataFrame:
    rows = conn.execute(_feedback_query(include_simulated), (MAX_CONTEXT_AGE_S,)).fetchall()
    return _to_dataset(pd.DataFrame([tuple(r) for r in rows], columns=FEEDBACK_COLUMNS))


def from_configured_database(include_simulated: bool = False) -> pd.DataFrame:
    from backend.config import load_settings
    from backend.database import open_database

    db = open_database(load_settings())
    try:
        with db.session() as conn:
            return from_connection(conn, include_simulated)
    finally:
        db.close()


def _to_dataset(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame({
        TIME: df["created_at"],
        GROUP: df["user_id"].fillna(0).astype(int).astype(str) + "-" + df["created_at"].str.slice(0, 10),
        "temperature_c": df["temperature_c"],
        "humidity_pct": df["humidity_pct"],
        "light_pct": df["light_pct"],
        "motion_detected": df["motion_detected"],
        TARGET: df["rating"],
        "source": df["context_simulated"].map({0: "device", 1: "simulator"}),
    })
    return out


def from_csv(path: Path) -> pd.DataFrame:
    if path.stat().st_size > MAX_CSV_BYTES:
        raise ValueError(f"{path.name} is larger than {MAX_CSV_BYTES // (1024 * 1024)} MB")
    df = pd.read_csv(path, dtype=str, keep_default_na=True, na_values=[""], encoding="utf-8")
    df.columns = [c.strip() for c in df.columns]
    required = [TIME, GROUP, *BASE_FEATURES, TARGET]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing required columns: {', '.join(missing)}")
    unexpected = [c for c in df.columns if c not in DATASET_COLUMNS]
    if unexpected:
        raise ValueError(f"CSV has unexpected columns: {', '.join(unexpected)}")
    if "source" not in df.columns:
        df["source"] = "external"
    if "motion_detected" not in df.columns:
        df["motion_detected"] = None
    return df[DATASET_COLUMNS]


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    report = {"rows_in": int(len(df))}
    df = df.copy()

    for col in [*BASE_FEATURES, "motion_detected", TARGET]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df[TIME] = pd.to_datetime(df[TIME], utc=True, errors="coerce")
    df[GROUP] = df[GROUP].astype(str).str.slice(0, 64)

    before = len(df)
    df = df.dropna(subset=[TIME, *BASE_FEATURES, TARGET])
    report["dropped_missing"] = before - len(df)

    before = len(df)
    mask = pd.Series(True, index=df.index)
    for col in BASE_FEATURES:
        lo, hi = FEATURE_RANGES[col]
        mask &= df[col].between(lo, hi)
    lo, hi = TARGET_RANGE
    mask &= df[TARGET].between(lo, hi) & (df[TARGET] == df[TARGET].round())
    motion = df["motion_detected"]
    mask &= motion.isna() | motion.isin([0, 1])
    df = df[mask]
    report["dropped_out_of_range"] = before - len(df)

    before = len(df)
    df = df.drop_duplicates(subset=[TIME, GROUP, *BASE_FEATURES, TARGET])
    report["dropped_duplicates"] = before - len(df)

    df[TARGET] = df[TARGET].astype(int)
    df = df.sort_values(TIME).reset_index(drop=True)
    df[TIME] = df[TIME].dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    report["rows_out"] = int(len(df))
    report["sessions"] = int(df[GROUP].nunique())
    report["rating_counts"] = {str(k): int(v) for k, v in df[TARGET].value_counts().sort_index().items()}
    report["sources"] = {str(k): int(v) for k, v in df["source"].value_counts().items()}
    return df, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--db", type=Path, help="SmartBuddy SQLite database (default: the database in .env)")
    src.add_argument("--csv", type=Path, help="external labelled CSV (validated, never executed)")
    parser.add_argument("--out", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--include-simulated", action="store_true")
    args = parser.parse_args(argv)

    try:
        if args.csv:
            raw = from_csv(args.csv)
        elif args.db:
            raw = from_database(args.db, args.include_simulated)
        else:
            raw = from_configured_database(args.include_simulated)
    except (ValueError, sqlite3.Error, FileNotFoundError, pd.errors.ParserError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: could not read the database ({type(exc).__name__})", file=sys.stderr)
        return 2

    df, report = clean(raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    report["output"] = str(args.out)
    print(json.dumps(report, indent=2))
    if report["rows_out"] == 0:
        print("No usable labelled rows yet. Collect comfort feedback from the dashboard first.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
