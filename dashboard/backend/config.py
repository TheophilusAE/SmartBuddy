from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
DEFAULT_ENV_FILE = DASHBOARD_DIR / ".env"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DEVICE_ID_RE = re.compile(r"^[a-z0-9-]{3,32}$")


class ConfigError(RuntimeError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _parse_keys(raw: str, name: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in filter(None, (p.strip() for p in raw.split(","))):
        device_id, sep, digest = item.partition(":")
        device_id, digest = device_id.strip(), digest.strip().lower()
        if not sep or not _DEVICE_ID_RE.match(device_id) or not _SHA256_RE.match(digest):
            raise ConfigError(f"{name} has a malformed entry (expected device-id:sha256hex)")
        result[digest] = device_id
    return result


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _float(env: dict[str, str], key: str, default: float) -> float:
    raw = env.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be a number") from exc


@dataclass
class Settings:
    app_env: str = "production"
    host: str = "127.0.0.1"
    port: int = 8000
    database_path: Path = DASHBOARD_DIR / "data" / "smartbuddy.db"
    database_url: str = field(default="", repr=False)
    models_dir: Path = DASHBOARD_DIR / "ml" / "models"
    frontend_dist: Path = DASHBOARD_DIR / "frontend" / "dist"
    cors_origins: list[str] = field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://127.0.0.1:8000",
            "http://localhost:8000",
        ]
    )

    admin_username: str = "admin"
    admin_password_hash: str = ""
    viewer_username: str = ""
    viewer_password_hash: str = ""
    session_hours: float = 8.0
    cookie_secure: bool = False

    device_keys: dict[str, str] = field(default_factory=dict)
    simulator_keys: dict[str, str] = field(default_factory=dict)
    allow_simulator: bool = False

    command_ttl_s: float = 10.0
    device_offline_s: float = 15.0
    clock_skew_s: float = 300.0

    gas_warning_adc: int = 1800
    gas_clear_adc: int = 1700

    fan_on_temp_c: float = 26.1
    fan_off_temp_c: float = 25.5
    light_on_pct: float = 30.0
    light_off_pct: float = 40.0
    motion_hold_s: float = 300.0
    automation_cooldown_s: float = 60.0

    enable_ml_automatic: bool = False

    device_control_enabled: bool = False

    lan_device_only: bool = True

    on_render: bool = False

    @property
    def is_loopback_only(self) -> bool:
        return self.host in {"127.0.0.1", "localhost", "::1"}

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    @property
    def database_kind(self) -> str:
        return "postgres" if self.database_url else "sqlite"

    def validate(self) -> None:
        if self.app_env not in {"production", "development"}:
            raise ConfigError("APP_ENV must be 'production' or 'development'")
        if self.database_url and not re.match(r"^postgres(ql)?://\S+$", self.database_url):
            raise ConfigError("DATABASE_URL must be a postgresql://... connection string")
        if self.on_render:
            # render wipes the disk on every deploy, a sqlite file there would lose data
            if not self.database_url:
                raise ConfigError("DATABASE_URL is required on Render")
            if not self.cookie_secure:
                raise ConfigError("COOKIE_SECURE must be true on Render (the site is HTTPS)")
        if any(o.strip() == "*" for o in self.cors_origins):
            raise ConfigError("CORS_ORIGINS must list explicit origins, '*' is not allowed")
        for origin in self.cors_origins:
            if not re.match(r"^https?://[A-Za-z0-9.\-]+(:\d+)?$", origin):
                raise ConfigError(f"CORS_ORIGINS entry is not a plain origin: {origin!r}")
        overlap = set(self.device_keys) & set(self.simulator_keys)
        if overlap:
            raise ConfigError("The same key hash appears in DEVICE_KEYS and SIMULATOR_KEYS")
        if not self.gas_clear_adc < self.gas_warning_adc:
            raise ConfigError("GAS_CLEAR_ADC must be lower than GAS_WARNING_ADC")
        if not self.fan_off_temp_c < self.fan_on_temp_c:
            raise ConfigError("FAN_OFF_TEMP_C must be lower than FAN_ON_TEMP_C")
        if not self.light_on_pct < self.light_off_pct:
            raise ConfigError("LIGHT_ON_PCT must be lower than LIGHT_OFF_PCT")


def _resolve_path(raw: str | None, default: Path) -> Path:
    if not raw:
        return default
    p = Path(raw)
    return p if p.is_absolute() else (DASHBOARD_DIR / p).resolve()


def load_settings(env_file: Path | None = DEFAULT_ENV_FILE, overrides: dict[str, str] | None = None) -> Settings:
    choice = os.environ.get("SMARTBUDDY_ENV_FILE")
    if choice:
        env_file = None if choice.lower() == "none" else Path(choice)
    env: dict[str, str] = {}
    if env_file is not None:
        env.update(read_env_file(env_file))
    env.update({k: v for k, v in os.environ.items() if k.isupper()})
    if overrides:
        env.update(overrides)

    s = Settings()
    s.app_env = env.get("APP_ENV", s.app_env).strip().lower()
    s.host = env.get("HOST", s.host)
    try:
        s.port = int(env.get("PORT", s.port))
    except ValueError as exc:
        raise ConfigError("PORT must be an integer") from exc
    s.database_path = _resolve_path(env.get("DATABASE_PATH"), s.database_path)
    s.database_url = env.get("DATABASE_URL", "").strip()
    s.models_dir = _resolve_path(env.get("MODELS_DIR"), s.models_dir)
    s.frontend_dist = _resolve_path(env.get("FRONTEND_DIST"), s.frontend_dist)
    if env.get("CORS_ORIGINS"):
        s.cors_origins = [o.strip().rstrip("/") for o in env["CORS_ORIGINS"].split(",") if o.strip()]
    # render sets these itself; the site's own https address has to be an allowed origin
    s.on_render = bool(env.get("RENDER"))
    render_url = env.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if render_url and render_url not in s.cors_origins:
        s.cors_origins.append(render_url)

    s.admin_username = env.get("ADMIN_USERNAME", s.admin_username)
    s.admin_password_hash = env.get("ADMIN_PASSWORD_HASH", "")
    s.viewer_username = env.get("VIEWER_USERNAME", "")
    s.viewer_password_hash = env.get("VIEWER_PASSWORD_HASH", "")
    s.session_hours = _float(env, "SESSION_HOURS", s.session_hours)
    s.cookie_secure = _bool(env.get("COOKIE_SECURE"), s.cookie_secure)

    s.device_keys = _parse_keys(env.get("DEVICE_KEYS", ""), "DEVICE_KEYS")
    s.simulator_keys = _parse_keys(env.get("SIMULATOR_KEYS", ""), "SIMULATOR_KEYS")
    s.allow_simulator = _bool(env.get("ALLOW_SIMULATOR"), s.allow_simulator)

    s.command_ttl_s = _float(env, "COMMAND_TTL_S", s.command_ttl_s)
    s.device_offline_s = _float(env, "DEVICE_OFFLINE_S", s.device_offline_s)
    s.gas_warning_adc = int(_float(env, "GAS_WARNING_ADC", s.gas_warning_adc))
    s.gas_clear_adc = int(_float(env, "GAS_CLEAR_ADC", s.gas_clear_adc))
    s.fan_on_temp_c = _float(env, "FAN_ON_TEMP_C", s.fan_on_temp_c)
    s.fan_off_temp_c = _float(env, "FAN_OFF_TEMP_C", s.fan_off_temp_c)
    s.light_on_pct = _float(env, "LIGHT_ON_PCT", s.light_on_pct)
    s.light_off_pct = _float(env, "LIGHT_OFF_PCT", s.light_off_pct)
    s.motion_hold_s = _float(env, "MOTION_HOLD_S", s.motion_hold_s)
    s.automation_cooldown_s = _float(env, "AUTOMATION_COOLDOWN_S", s.automation_cooldown_s)
    s.enable_ml_automatic = _bool(env.get("ENABLE_ML_AUTOMATIC"), False)
    s.device_control_enabled = _bool(env.get("DEVICE_CONTROL_ENABLED"), False)
    s.lan_device_only = _bool(env.get("LAN_DEVICE_ONLY"), not s.on_render)

    s.validate()
    return s
