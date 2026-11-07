from __future__ import annotations

import json
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import joblib
import numpy as np

from .common import CURRENT_FILE, FEATURE_RANGES, MODEL_FILE_RE, MODELS_DIR, file_sha256


class ModelUnavailable(Exception):
    pass


@dataclass
class ComfortModel:
    version: str
    algorithm: str
    features: list[str]
    estimator: Any
    metadata: dict[str, Any]

    def predict(self, values: dict[str, Any]) -> float:
        row = []
        for name in self.features:
            v = values.get(name)
            if isinstance(v, bool):
                v = float(v)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                raise ValueError(f"feature {name} is missing or not a number")
            lo, hi = FEATURE_RANGES[name]
            if not lo <= v <= hi:
                raise ValueError(f"feature {name}={v} is outside {lo}..{hi}")
            row.append(float(v))
        pred = float(self.estimator.predict(np.array([row]))[0])
        return round(min(5.0, max(1.0, pred)), 2)


def read_metadata(models_dir: Path = MODELS_DIR) -> Optional[dict[str, Any]]:
    path = models_dir / CURRENT_FILE
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def load_model(models_dir: Path = MODELS_DIR) -> ComfortModel:
    meta = read_metadata(models_dir)
    if not meta or meta.get("status") != "deployed":
        raise ModelUnavailable("no deployed model")

    name = str(meta.get("model_file", ""))
    if not MODEL_FILE_RE.match(name):
        raise ModelUnavailable("model file name in metadata is not one this project produces")
    path = (models_dir / name).resolve()
    if path.parent != models_dir.resolve() or not path.is_file():
        raise ModelUnavailable("model file missing")
    if file_sha256(path) != meta.get("sha256"):
        raise ModelUnavailable("model file hash does not match its metadata - refusing to load")

    features = meta.get("features")
    if not isinstance(features, list) or not all(f in FEATURE_RANGES for f in features):
        raise ModelUnavailable("unexpected feature list in metadata")

    estimator = joblib.load(path)
    return ComfortModel(meta["model_version"], meta.get("algorithm", "?"), features, estimator, meta)


class ModelCache:
    def __init__(self, models_dir: Path = MODELS_DIR):
        self.models_dir = models_dir
        self._lock = threading.Lock()
        self._mtime: Optional[float] = None
        self._model: Optional[ComfortModel] = None
        self.error: Optional[str] = None

    def get(self) -> Optional[ComfortModel]:
        path = self.models_dir / CURRENT_FILE
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = None
        with self._lock:
            if mtime != self._mtime:
                self._mtime = mtime
                self._model = None
                self.error = None
                if mtime is not None:
                    try:
                        self._model = load_model(self.models_dir)
                    except ModelUnavailable as exc:
                        self.error = str(exc)
                    except Exception:
                        self.error = "model could not be loaded"
            return self._model
