from __future__ import annotations

import hashlib
import re
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = DASHBOARD_DIR / "ml" / "models"
PROCESSED_DIR = DASHBOARD_DIR / "data" / "processed"
DEFAULT_DATASET = PROCESSED_DIR / "comfort_dataset.csv"

BASE_FEATURES = ["temperature_c", "humidity_pct", "light_pct"]
OPTIONAL_FEATURES = ["motion_detected"]
TARGET = "comfort_rating"
GROUP = "session_id"
TIME = "recorded_at"

DATASET_COLUMNS = [TIME, GROUP, *BASE_FEATURES, *OPTIONAL_FEATURES, TARGET, "source"]

FEATURE_RANGES = {
    "temperature_c": (-40.0, 80.0),
    "humidity_pct": (0.0, 100.0),
    "light_pct": (0.0, 100.0),
    "motion_detected": (0.0, 1.0),
}
TARGET_RANGE = (1, 5)

MAX_CONTEXT_AGE_S = 120
MIN_LABELS = 30
MIN_GROUPS = 2
RANDOM_FOREST_MIN_LABELS = 60
RANDOM_SEED = 42

MODEL_FILE_RE = re.compile(r"^comfort_v\d{8}-\d{6}\.joblib$")
FORECAST_FILE_RE = re.compile(r"^forecast_v\d{8}-\d{6}\.joblib$")
CURRENT_FILE = "current.json"
LAST_TRAINING_FILE = "last_training.json"

COMFORT_SCALE = {
    1: "Very uncomfortable",
    2: "Uncomfortable",
    3: "Neutral",
    4: "Comfortable",
    5: "Very comfortable",
}


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
