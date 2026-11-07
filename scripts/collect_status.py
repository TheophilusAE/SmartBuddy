"""How many real readings are in the database so far.

    python scripts/collect_status.py              (the database the backend uses, from dashboard/.env)
    python scripts/collect_status.py --db dashboard/data/smartbuddy.db
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "dashboard"))

from backend.config import load_settings  # noqa: E402
from backend.database import Database, open_database  # noqa: E402
from backend.services.readings_service import collection_stats  # noqa: E402

TARGET = 1000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, help="read this SQLite file instead")
    args = parser.parse_args()

    if args.db:
        if not args.db.is_file():
            print(f"No database at {args.db}. Start the backend once to create it.", file=sys.stderr)
            return 1
        db = Database(args.db)
        where = str(args.db)
    else:
        settings = load_settings()
        db = open_database(settings)
        where = "Supabase/Postgres (DATABASE_URL)" if settings.database_url else str(settings.database_path)

    try:
        with db.session() as conn:
            s = collection_stats(conn)
            boots = conn.execute(
                "SELECT COUNT(DISTINCT boot_id) FROM sensor_readings WHERE is_simulated = 0").fetchone()[0]
            feedback = conn.execute("SELECT COUNT(*) FROM comfort_feedback WHERE context_simulated = 0").fetchone()[0]
    finally:
        db.close()

    rejected = {k[len("rejected_"):]: v for k, v in s.items() if k.startswith("rejected_") and v}
    valid = s["real_valid_readings"]
    print(f"Database            : {where}")
    print(f"Valid real readings : {valid} / {TARGET} ({min(100, valid / TARGET * 100):.1f}%)")
    print(f"  with device clock : {s['real_valid_trusted_time']}")
    print(f"All real readings   : {s['real_readings']}")
    print(f"Simulated (excluded): {s['simulated_readings']}")
    print(f"First / last real   : {s['first_real_at']} / {s['last_real_at']} (UTC)")
    print(f"Device boots seen   : {boots}")
    print(f"Rejected messages   : {rejected or 'none'}")
    print(f"Comfort ratings     : {feedback} (real context)")
    if valid >= TARGET:
        print("\nThe 1,000 valid real readings requirement is met. Export a CSV from the dashboard as evidence.")
    else:
        remaining = TARGET - valid
        print(f"\n{remaining} more needed - about {remaining * 2 / 60:.0f} minutes at 2 s per reading without gaps.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
