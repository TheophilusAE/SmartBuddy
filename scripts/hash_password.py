"""Password hash for dashboard/.env.

    python scripts/hash_password.py
    python scripts/hash_password.py --viewer
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "dashboard"))

from backend.security import hash_password  # noqa: E402

MIN_LENGTH = 10


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--viewer", action="store_true", help="print VIEWER_PASSWORD_HASH instead")
    args = parser.parse_args()
    var = "VIEWER_PASSWORD_HASH" if args.viewer else "ADMIN_PASSWORD_HASH"

    pw = getpass.getpass("New password: ")
    if len(pw) < MIN_LENGTH:
        print(f"Use at least {MIN_LENGTH} characters.", file=sys.stderr)
        return 1
    if getpass.getpass("Repeat password: ") != pw:
        print("Passwords don't match.", file=sys.stderr)
        return 1
    print("\nPut this line in dashboard/.env:\n")
    print(f"{var}={hash_password(pw)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
