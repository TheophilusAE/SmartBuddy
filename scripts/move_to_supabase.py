"""Copies everything from the local SQLite database into the Supabase/Postgres database in DATABASE_URL.

    dashboard\\.venv\\Scripts\\python scripts\\move_to_supabase.py

Stop the backend first. The SQLite file is only read, never changed.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))

from backend.config import load_settings  # noqa: E402
from backend.database import MIGRATIONS, PostgresDatabase  # noqa: E402

# parents before children because of the foreign keys. sessions are skipped, you just log in again
TABLES = ["users", "sensor_readings", "ingest_rejections", "device_status", "device_events",
          "comfort_feedback", "ml_predictions", "settings"]
MUST_BE_EMPTY = ["sensor_readings", "ingest_rejections", "device_events", "comfort_feedback", "ml_predictions"]
KEEP_EXISTING = {"users": "username", "device_status": "device_id", "settings": "key"}
ID_TABLES = ["users", "sessions", "sensor_readings", "ingest_rejections", "device_events",
             "comfort_feedback", "ml_predictions"]
BATCH = 500


def pg_columns(conn, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = ? ORDER BY ordinal_position", (table,)).fetchall()
    return [r[0] for r in rows]


def copy_table(src: sqlite3.Connection, conn, table: str, user_map: dict[int, int]) -> int:
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
    missing = [c for c in cols if c not in pg_columns(conn, table)]
    if missing:
        raise SystemExit(f"{table}: Postgres is missing columns {missing}. Is the schema up to date?")
    if table == "users":
        cols = [c for c in cols if c != "id"]

    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders})"
    if table in KEEP_EXISTING:
        sql += f" ON CONFLICT ({KEEP_EXISTING[table]}) DO NOTHING"

    user_col = cols.index("user_id") if table == "comfort_feedback" else None
    rows = src.execute(f"SELECT {', '.join(cols)} FROM {table} ORDER BY 1").fetchall()
    batch = []
    with conn.raw.cursor() as cur:
        for row in rows:
            values = list(row)
            if user_col is not None and values[user_col] is not None:
                values[user_col] = user_map.get(values[user_col])
            batch.append(values)
            if len(batch) >= BATCH:
                cur.executemany(sql, batch)
                batch = []
        if batch:
            cur.executemany(sql, batch)
    return len(rows)


def summary(conn) -> tuple:
    return tuple(conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(measured_ms), 0), "
        "SUM(CASE WHEN is_simulated = 0 AND valid = 1 THEN 1 ELSE 0 END) FROM sensor_readings").fetchone())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sqlite", type=Path, help="SQLite file to copy (default: DATABASE_PATH from dashboard/.env)")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.database_url:
        print("DATABASE_URL is not set in dashboard/.env. Add your Supabase connection string first.", file=sys.stderr)
        return 1
    path = args.sqlite or settings.database_path
    if not path.is_file():
        print(f"No SQLite database at {path}.", file=sys.stderr)
        return 1

    src = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    version = src.execute("PRAGMA user_version").fetchone()[0]
    if version != len(MIGRATIONS):
        print(f"{path.name} is at schema v{version}, expected v{len(MIGRATIONS)}. "
              "Start the backend once without DATABASE_URL to upgrade it, then try again.", file=sys.stderr)
        return 1

    db = PostgresDatabase(settings.database_url)
    try:
        print("Connecting to Postgres and creating the tables if needed...")
        db.init()
        with db.transaction() as conn:
            busy = [t for t in MUST_BE_EMPTY if conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]]
            if busy:
                print(f"Postgres already has data in: {', '.join(busy)}. Nothing was copied.\n"
                      "This script only fills an empty database.", file=sys.stderr)
                return 1

            counts = {}
            for table in TABLES:
                user_map: dict[int, int] = {}
                if table == "comfort_feedback":
                    old = {r[0]: r[1] for r in src.execute("SELECT id, username FROM users")}
                    new = {r[0]: r[1] for r in conn.execute("SELECT username, id FROM users").fetchall()}
                    user_map = {i: new[u] for i, u in old.items() if u in new}
                counts[table] = copy_table(src, conn, table, user_map)
                print(f"  {table:<18} {counts[table]:>7} rows")

            for table in ID_TABLES:
                conn.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                             f"COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)")

            before = tuple(src.execute(
                "SELECT COUNT(*), COALESCE(SUM(measured_ms), 0), "
                "SUM(CASE WHEN is_simulated = 0 AND valid = 1 THEN 1 ELSE 0 END) FROM sensor_readings").fetchone())
            after = summary(conn)
            if before != after:
                raise SystemExit(f"Check failed, rolling back. SQLite {before} vs Postgres {after}")
    finally:
        src.close()
        db.close()

    print(f"\nDone. {after[0]} readings copied ({after[2]} valid real), totals match the SQLite file.")
    print(f"The SQLite file is unchanged: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
