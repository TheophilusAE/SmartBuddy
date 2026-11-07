from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ml.common import LAST_TRAINING_FILE, MIN_GROUPS, MIN_LABELS
from ml.inference import ModelCache
from ml.recommend import recommend

from ..timeutil import to_iso, utc_now

PREDICTION_LOG_INTERVAL_S = 60


class MlService:
    def __init__(self, models_dir: Path):
        self.models_dir = models_dir
        self.cache = ModelCache(models_dir)
        self._last_logged = 0.0

    @property
    def model_available(self) -> bool:
        return self.cache.get() is not None

    def _last_training(self) -> Optional[dict[str, Any]]:
        path = self.models_dir / LAST_TRAINING_FILE
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def status(self, conn: sqlite3.Connection) -> dict[str, Any]:
        model = self.cache.get()
        usable = conn.execute(
            "SELECT COUNT(*) FROM comfort_feedback WHERE context_simulated = 0 AND temperature_c IS NOT NULL AND light_pct IS NOT NULL"
        ).fetchone()[0]
        last = self._last_training()
        return {
            "model_available": model is not None,
            "model_version": model.version if model else None,
            "algorithm": model.algorithm if model else None,
            "load_error": self.cache.error,
            "usable_feedback": usable,
            "min_labels": MIN_LABELS,
            "min_sessions": MIN_GROUPS,
            "last_training": None if last is None else {
                "status": last.get("status"),
                "attempted_at": last.get("attempted_at"),
                "message": last.get("message"),
            },
        }

    def evaluation(self) -> dict[str, Any]:
        model = self.cache.get()
        last = self._last_training()
        return {
            "deployed": model.metadata if model else None,
            "last_attempt": last,
        }

    def predict(self, reading: dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
        model = self.cache.get()
        if model is None:
            return None, None
        try:
            return model.predict(reading), model.version
        except ValueError:
            return None, model.version

    def advise(self, reading: Optional[dict[str, Any]]) -> dict[str, Any]:
        if reading is None:
            return {"available": False, "reason": "No sensor reading yet"}
        estimate, version = self.predict(reading)
        advice = recommend(reading, estimate)
        advice.update({
            "available": True,
            "estimate": estimate,
            "model_version": version,
            "based_on_reading_id": reading["id"],
            "based_on_simulated_data": reading["is_simulated"],
        })
        return advice

    def maybe_log_prediction(self, conn: sqlite3.Connection, reading: dict[str, Any]) -> Optional[float]:
        if reading.get("is_simulated") or not reading.get("valid"):
            return None
        now = time.monotonic()
        if now - self._last_logged < PREDICTION_LOG_INTERVAL_S:
            return None
        estimate, version = self.predict(reading)
        if estimate is None or version is None:
            return None
        self._last_logged = now
        conn.execute(
            "INSERT INTO ml_predictions (created_at, model_version, reading_id, predicted_comfort, temperature_c, "
            "humidity_pct, light_pct, motion_detected) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (to_iso(utc_now()), version, reading["id"], estimate, reading["temperature_c"], reading["humidity_pct"],
             reading["light_pct"],
             None if reading["motion_detected"] is None else int(reading["motion_detected"])),
        )
        return estimate
