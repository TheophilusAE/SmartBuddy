from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ml.common import (
    FORECAST_FILE_RE, LAST_TRAINING_FILE, MAX_CONTEXT_AGE_S, MIN_GROUPS, MIN_LABELS, MODEL_FILE_RE,
)
from ml.inference import ComfortModel, ModelCache
from ml.recommend import recommend
from ml.store import active_model_ref, fetch_model, load_attempt, restore_to_dir, save_attempt, save_model

from ..timeutil import to_iso, utc_now

log = logging.getLogger(__name__)

PREDICTION_LOG_INTERVAL_S = 60
DB_CHECK_INTERVAL_S = 30

USABLE_WHERE = (
    "context_simulated = 0 AND temperature_c IS NOT NULL AND humidity_pct IS NOT NULL AND light_pct IS NOT NULL "
    "AND context_age_s IS NOT NULL AND context_age_s <= ?"
)


class TrainingBusy(Exception):
    pass


def _load_forecast(folder: Path):
    from ml.forecast import load_forecast

    return load_forecast(folder)


class MlService:
    def __init__(self, models_dir: Path, db=None):
        self.models_dir = models_dir
        self.forecast_dir = models_dir / "forecast"
        self.db = db
        self.cache = ModelCache(models_dir)
        self.forecast_cache = ModelCache(self.forecast_dir, loader=_load_forecast)
        self._last_logged = 0.0
        self._train_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._next_check = 0.0
        self._db_versions: dict[str, Optional[str]] = {}
        self.sync_errors: dict[str, Optional[str]] = {}

    def _sync_kind(self, kind: str, folder: Path, file_re) -> None:
        with self.db.session() as conn:
            ref = active_model_ref(conn, kind)
            if ref is None or ref[0] == self._db_versions.get(kind):
                return
            found = fetch_model(conn, ref[0])
        if found is None:
            return
        blob, meta, sha = found
        restore_to_dir(blob, meta, sha, folder, file_re)
        self._db_versions[kind] = ref[0]
        self.sync_errors[kind] = None
        log.info("loaded %s model %s from the database", kind, ref[0])

    def _sync_from_db(self) -> None:
        if self.db is None or time.monotonic() < self._next_check:
            return
        if not self._sync_lock.acquire(blocking=False):
            return
        try:
            self._next_check = time.monotonic() + DB_CHECK_INTERVAL_S
            for kind, folder, file_re in (("comfort", self.models_dir, MODEL_FILE_RE),
                                          ("forecast", self.forecast_dir, FORECAST_FILE_RE)):
                try:
                    self._sync_kind(kind, folder, file_re)
                except ValueError as exc:
                    self.sync_errors[kind] = str(exc)
                except Exception as exc:
                    self.sync_errors[kind] = "could not read the model from the database"
                    log.warning("%s model sync failed: %s", kind, type(exc).__name__)
        finally:
            self._sync_lock.release()

    def get_model(self) -> Optional[ComfortModel]:
        self._sync_from_db()
        return self.cache.get()

    def get_forecast_model(self):
        self._sync_from_db()
        return self.forecast_cache.get()

    @property
    def model_available(self) -> bool:
        return self.get_model() is not None

    def _last_training(self, conn=None, kind: str = "comfort") -> Optional[dict[str, Any]]:
        if conn is not None:
            last = load_attempt(conn, kind)
            if last is not None:
                return last
        folder = self.forecast_dir if kind == "forecast" else self.models_dir
        path = folder / LAST_TRAINING_FILE
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    def status(self, conn: sqlite3.Connection) -> dict[str, Any]:
        model = self.get_model()
        usable = conn.execute(f"SELECT COUNT(*) FROM comfort_feedback WHERE {USABLE_WHERE}",
                              (MAX_CONTEXT_AGE_S,)).fetchone()[0]
        sessions = conn.execute(
            f"SELECT COUNT(*) FROM (SELECT DISTINCT user_id, substr(created_at, 1, 10) FROM comfort_feedback "
            f"WHERE {USABLE_WHERE}) t", (MAX_CONTEXT_AGE_S,)
        ).fetchone()[0]
        last = self._last_training(conn)
        fc = self.get_forecast_model()
        return {
            "model_available": model is not None,
            "model_version": model.version if model else None,
            "algorithm": model.algorithm if model else None,
            "load_error": self.sync_errors.get("comfort") or self.cache.error,
            "forecast_available": fc is not None,
            "forecast_version": fc.version if fc else None,
            "usable_feedback": usable,
            "usable_sessions": sessions,
            "min_labels": MIN_LABELS,
            "min_sessions": MIN_GROUPS,
            "last_training": None if last is None else {
                "status": last.get("status"),
                "attempted_at": last.get("attempted_at"),
                "message": last.get("message"),
            },
        }

    def evaluation(self, conn=None) -> dict[str, Any]:
        model = self.get_model()
        fc = self.get_forecast_model()
        return {
            "deployed": model.metadata if model else None,
            "last_attempt": self._last_training(conn),
            "forecast": {
                "deployed": fc.metadata if fc else None,
                "last_attempt": self._last_training(conn, "forecast"),
                "load_error": self.sync_errors.get("forecast") or self.forecast_cache.error,
            },
        }

    def forecast(self, device_id: Optional[str] = None) -> dict[str, Any]:
        model = self.get_forecast_model()
        if model is None or self.db is None:
            return {"available": False, "reason": "No forecast model trained yet"}
        from ml.forecast import latest_features

        with self.db.session() as conn:
            feats = latest_features(conn, device_id)
        if feats is None:
            return {"available": False, "reason": "Needs the last few minutes of live readings"}
        try:
            pred = model.predict(feats)
        except ValueError:
            return {"available": False, "reason": "Recent readings are incomplete"}
        meta = model.metadata
        best = (meta.get("best_candidate") or {}).get("temperature_c")
        rmse = ((meta.get("metrics") or {}).get("temperature_c") or {}).get(best, {}).get("rmse")
        return {
            "available": True,
            "model_version": model.version,
            "horizon_min": meta.get("horizon_min"),
            "uncertainty_c": rmse,
            "based_on": feats["at"],
            "now": {"temperature_c": round(feats["temperature_c"], 2), "humidity_pct": round(feats["humidity_pct"], 2)},
            "forecast": pred,
        }

    def train_forecast_now(self, horizon_min: int) -> dict[str, Any]:
        if self.db is None:
            raise RuntimeError("no database")
        if not self._train_lock.acquire(blocking=False):
            raise TrainingBusy()
        try:
            from ml.forecast import load_readings, train_forecast

            with self.db.session() as conn:
                readings = load_readings(conn)
            result = train_forecast(readings, self.forecast_dir, horizon_min)
            with self.db.transaction() as conn:
                save_attempt(conn, result, "forecast")
                if result["status"] == "deployed":
                    save_model(conn, result, self.forecast_dir, "forecast")
            if result["status"] == "deployed":
                self._db_versions["forecast"] = result["model_version"]
                self.sync_errors["forecast"] = None
            return {k: v for k, v in result.items() if k != "test_series"}
        finally:
            self._train_lock.release()

    def train_now(self) -> dict[str, Any]:
        if self.db is None:
            raise RuntimeError("no database")
        if not self._train_lock.acquire(blocking=False):
            raise TrainingBusy()
        try:
            # pandas/sklearn only load when someone trains, keeps render's memory low
            from ml.prepare_dataset import clean, from_connection
            from ml.train_model import train

            with self.db.session() as conn:
                raw = from_connection(conn)
            df, _ = clean(raw)
            result = train(df, self.models_dir, dataset_name="database")
            with self.db.transaction() as conn:
                save_attempt(conn, result)
                if result["status"] == "deployed":
                    save_model(conn, result, self.models_dir)
            if result["status"] == "deployed":
                self._db_versions["comfort"] = result["model_version"]
                self.sync_errors["comfort"] = None
            return {k: v for k, v in result.items() if k != "test_predictions"}
        finally:
            self._train_lock.release()

    def predict(self, reading: dict[str, Any]) -> tuple[Optional[float], Optional[str]]:
        model = self.get_model()
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
