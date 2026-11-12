from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .common import CURRENT_FILE, MODEL_FILE_RE, file_sha256

ATTEMPT_KEYS = {"comfort": "ml_last_training", "forecast": "ml_last_forecast"}
MAX_MODEL_BYTES = 20 * 1024 * 1024
KEEP_OLD_MODELS = 5


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def save_attempt(conn, result: dict[str, Any], kind: str = "comfort") -> None:
    from backend.database import set_setting

    set_setting(conn, ATTEMPT_KEYS[kind], json.dumps(result), _now(), "ml")


def load_attempt(conn, kind: str = "comfort") -> Optional[dict[str, Any]]:
    from backend.database import get_setting

    raw = get_setting(conn, ATTEMPT_KEYS[kind])
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def save_model(conn, result: dict[str, Any], models_dir: Path, kind: str = "comfort") -> None:
    path = models_dir / result["model_file"]
    blob = path.read_bytes()
    if len(blob) > MAX_MODEL_BYTES:
        raise ValueError("model file is too large to store")
    if hashlib.sha256(blob).hexdigest() != result["sha256"]:
        raise ValueError("model file changed after training")
    conn.execute("UPDATE ml_models SET active = 0 WHERE active = 1 AND kind = ?", (kind,))
    conn.execute(
        "INSERT INTO ml_models (created_at, model_version, algorithm, sha256, size_bytes, metadata, model_blob, active, "
        "kind) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (_now(), result["model_version"], result.get("algorithm"), result["sha256"], len(blob),
         json.dumps(result), blob, kind),
    )
    conn.execute(
        "DELETE FROM ml_models WHERE active = 0 AND kind = ? AND id NOT IN "
        "(SELECT id FROM ml_models WHERE active = 0 AND kind = ? ORDER BY id DESC LIMIT ?)",
        (kind, kind, KEEP_OLD_MODELS),
    )


def active_model_ref(conn, kind: str = "comfort") -> Optional[tuple[str, str]]:
    row = conn.execute(
        "SELECT model_version, sha256 FROM ml_models WHERE active = 1 AND kind = ? ORDER BY id DESC LIMIT 1", (kind,)
    ).fetchone()
    return (row["model_version"], row["sha256"]) if row else None


def fetch_model(conn, version: str) -> Optional[tuple[bytes, dict[str, Any], str]]:
    row = conn.execute(
        "SELECT model_blob, metadata, sha256 FROM ml_models WHERE model_version = ?", (version,)
    ).fetchone()
    if not row:
        return None
    return bytes(row["model_blob"]), json.loads(row["metadata"]), row["sha256"]


def restore_to_dir(blob: bytes, meta: dict[str, Any], sha256: str, models_dir: Path,
                   file_re: re.Pattern = MODEL_FILE_RE) -> None:
    name = str(meta.get("model_file", ""))
    if not file_re.match(name):
        raise ValueError("model file name in the database is not one this project produces")
    if len(blob) > MAX_MODEL_BYTES:
        raise ValueError("model in the database is too large")
    if hashlib.sha256(blob).hexdigest() != sha256 or meta.get("sha256") != sha256:
        raise ValueError("model hash in the database does not match")

    models_dir.mkdir(parents=True, exist_ok=True)
    path = models_dir / name
    if not path.is_file() or file_sha256(path) != sha256:
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(blob)
        tmp.replace(path)
    current = models_dir / CURRENT_FILE
    tmp = current.with_suffix(".tmp")
    tmp.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    tmp.replace(current)
