from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

from .automation import DEFAULT_MODE, AutomationEngine
from .config import Settings
from .database import Database, PostgresDatabase, get_setting, set_setting, open_database
from .safety import GasMonitor
from .schemas import OperatingMode
from .security import RateLimiter
from .services.ml_service import MlService
from .timeutil import to_iso, utc_now
from .ws_hub import LiveHub

MODE_KEY = "operating_mode"


@dataclass
class AppContext:
    settings: Settings
    db: Database | PostgresDatabase
    hub: LiveHub
    gas: GasMonitor
    automation: AutomationEngine
    ml: MlService
    login_user_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(5, 300))
    login_ip_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(20, 300))
    device_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(240, 60))
    unauth_device_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(30, 60))
    command_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(30, 60))
    feedback_limiter: RateLimiter = field(default_factory=lambda: RateLimiter(20, 60))

    @classmethod
    def build(cls, settings: Settings) -> "AppContext":
        return cls(
            settings=settings,
            db=open_database(settings),
            hub=LiveHub(),
            gas=GasMonitor(settings.gas_warning_adc, settings.gas_clear_adc),
            automation=AutomationEngine(settings),
            ml=MlService(settings.models_dir),
        )

    def get_mode(self, conn: sqlite3.Connection) -> OperatingMode:
        raw = get_setting(conn, MODE_KEY)
        try:
            return OperatingMode(raw) if raw else DEFAULT_MODE
        except ValueError:
            return DEFAULT_MODE

    def set_mode(self, conn: sqlite3.Connection, mode: OperatingMode, by: str | None) -> None:
        set_setting(conn, MODE_KEY, mode.value, to_iso(utc_now()), by)
