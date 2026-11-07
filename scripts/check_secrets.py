from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_IGNORES = [
    ".env", "secrets.h", "docs/", "dashboard/tests/", "*.db", "*.db-wal", "*.db-shm",
    "node_modules/", ".venv/", "__pycache__/", "dashboard/ml/models/*", "*.log",
]
SENSITIVE_NAMES = {".env", "secrets.h"}
SENSITIVE_SUFFIXES = {".db", ".db-wal", ".db-shm", ".joblib", ".sqlite", ".sqlite3"}
SKIP_DIRS = {"node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build", ".pytest_cache"}

PATTERNS = {
    "password hash": re.compile(r"scrypt\$\d+\$\d+\$\d+\$[A-Za-z0-9+/=]{16,}\$[A-Za-z0-9+/=]{20,}"),
    "private key": re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "device key hash line": re.compile(r"^DEVICE_KEYS=[a-z0-9-]+:[0-9a-f]{64}", re.M),
    "database url with password": re.compile(r"postgres(ql)?://[^:\s/]+:(?![<\[])[^@\s]{6,}@"),
    "supabase secret key": re.compile(r"sb_secret_[A-Za-z0-9_-]{20,}"),
}


def main() -> int:
    problems: list[str] = []

    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for pattern in REQUIRED_IGNORES:
        if pattern not in ignore:
            problems.append(f".gitignore is missing: {pattern}")

    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.name in SENSITIVE_NAMES or path.suffix in SENSITIVE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pat in PATTERNS.items():
            if pat.search(text):
                problems.append(f"{path.relative_to(ROOT)}: looks like it contains a {label}")

    if (ROOT / ".git").exists():
        try:
            tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.splitlines()
        except (OSError, subprocess.CalledProcessError):
            tracked = []
        for f in tracked:
            p = Path(f)
            if p.name in SENSITIVE_NAMES or p.suffix in SENSITIVE_SUFFIXES:
                problems.append(f"tracked by git but should not be: {f}")

    if problems:
        print("Problems found:")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("No obvious secrets found and .gitignore covers the sensitive files.")
    print("(This is a pattern check, not a guarantee. Review diffs before you commit.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
