from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)

MIGRATIONS: list[str] = [
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
        created_at TEXT NOT NULL
    );

    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY,
        token_hash TEXT NOT NULL UNIQUE,
        csrf_token TEXT NOT NULL,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
    );
    CREATE INDEX ix_sessions_user ON sessions(user_id);

    CREATE TABLE sensor_readings (
        id INTEGER PRIMARY KEY,
        device_id TEXT NOT NULL,
        boot_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 0),
        measured_at TEXT NOT NULL,
        measured_ms INTEGER NOT NULL,
        device_timestamp TEXT,
        received_at TEXT NOT NULL,
        timestamp_trusted INTEGER NOT NULL CHECK (timestamp_trusted IN (0, 1)),
        uptime_ms INTEGER CHECK (uptime_ms IS NULL OR uptime_ms >= 0),
        temperature_c REAL CHECK (temperature_c IS NULL OR temperature_c BETWEEN -40 AND 80),
        humidity_pct REAL CHECK (humidity_pct IS NULL OR humidity_pct BETWEEN 0 AND 100),
        illuminance_lux REAL CHECK (illuminance_lux IS NULL OR illuminance_lux BETWEEN 0 AND 120000),
        motion_detected INTEGER CHECK (motion_detected IS NULL OR motion_detected IN (0, 1)),
        gas_adc INTEGER CHECK (gas_adc IS NULL OR gas_adc BETWEEN 0 AND 4095),
        gas_warning_local INTEGER NOT NULL CHECK (gas_warning_local IN (0, 1)),
        dht_status TEXT NOT NULL,
        bh1750_status TEXT NOT NULL,
        pir_status TEXT NOT NULL,
        mq2_status TEXT NOT NULL,
        fan_on INTEGER,
        light_on INTEGER,
        buzzer_on INTEGER,
        valid INTEGER NOT NULL CHECK (valid IN (0, 1)),
        out_of_order INTEGER NOT NULL DEFAULT 0 CHECK (out_of_order IN (0, 1)),
        is_simulated INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
        UNIQUE (device_id, boot_id, sequence)
    );
    CREATE INDEX ix_readings_time ON sensor_readings(measured_ms);
    CREATE INDEX ix_readings_device_time ON sensor_readings(device_id, measured_ms);
    CREATE INDEX ix_readings_real_valid ON sensor_readings(is_simulated, valid);

    CREATE TABLE ingest_rejections (
        id INTEGER PRIMARY KEY,
        received_at TEXT NOT NULL,
        device_id TEXT,
        reason TEXT NOT NULL CHECK (reason IN ('invalid', 'duplicate', 'unauthorized', 'too_large', 'rate_limited'))
    );
    CREATE INDEX ix_rejections_reason ON ingest_rejections(reason);

    CREATE TABLE device_status (
        device_id TEXT PRIMARY KEY,
        is_simulated INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
        last_seen_at TEXT,
        last_boot_id TEXT,
        fan_on INTEGER,
        light_on INTEGER,
        buzzer_on INTEGER,
        gas_warning_local INTEGER NOT NULL DEFAULT 0,
        state_reported_at TEXT
    );

    CREATE TABLE device_events (
        id INTEGER PRIMARY KEY,
        device_id TEXT NOT NULL,
        target TEXT NOT NULL CHECK (target IN ('fan', 'light', 'buzzer', 'alarm', 'all')),
        state TEXT NOT NULL CHECK (state IN ('on', 'off', 'mute')),
        source TEXT NOT NULL CHECK (source IN ('user', 'rule', 'ml', 'safety', 'system')),
        requested_by TEXT,
        reason TEXT,
        status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'acked', 'rejected', 'expired', 'superseded')),
        created_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        sent_at TEXT,
        acked_at TEXT,
        ack_result TEXT CHECK (ack_result IS NULL OR ack_result IN ('applied', 'rejected', 'expired')),
        ack_reason TEXT,
        observed_fan INTEGER,
        observed_light INTEGER,
        observed_buzzer INTEGER
    );
    CREATE INDEX ix_events_device_status ON device_events(device_id, status);
    CREATE INDEX ix_events_created ON device_events(created_at);

    CREATE TABLE comfort_feedback (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
        reading_id INTEGER REFERENCES sensor_readings(id) ON DELETE SET NULL,
        device_id TEXT,
        temperature_c REAL,
        humidity_pct REAL,
        illuminance_lux REAL,
        motion_detected INTEGER,
        context_age_s REAL,
        context_simulated INTEGER NOT NULL CHECK (context_simulated IN (0, 1)),
        note TEXT CHECK (note IS NULL OR length(note) <= 200)
    );
    CREATE INDEX ix_feedback_created ON comfort_feedback(created_at);

    CREATE TABLE ml_predictions (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        model_version TEXT NOT NULL,
        reading_id INTEGER REFERENCES sensor_readings(id) ON DELETE SET NULL,
        predicted_comfort REAL NOT NULL,
        temperature_c REAL,
        humidity_pct REAL,
        illuminance_lux REAL,
        motion_detected INTEGER
    );
    CREATE INDEX ix_predictions_created ON ml_predictions(created_at);

    CREATE TABLE settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        updated_by TEXT
    );
    """,
    """
    CREATE TABLE sensor_readings_new (
        id INTEGER PRIMARY KEY,
        device_id TEXT NOT NULL,
        boot_id TEXT NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 0),
        measured_at TEXT NOT NULL,
        measured_ms INTEGER NOT NULL,
        device_timestamp TEXT,
        received_at TEXT NOT NULL,
        timestamp_trusted INTEGER NOT NULL CHECK (timestamp_trusted IN (0, 1)),
        uptime_ms INTEGER CHECK (uptime_ms IS NULL OR uptime_ms >= 0),
        temperature_c REAL CHECK (temperature_c IS NULL OR temperature_c BETWEEN -40 AND 80),
        humidity_pct REAL CHECK (humidity_pct IS NULL OR humidity_pct BETWEEN 0 AND 100),
        light_pct REAL CHECK (light_pct IS NULL OR light_pct BETWEEN 0 AND 100),
        ldr_raw INTEGER CHECK (ldr_raw IS NULL OR ldr_raw BETWEEN 0 AND 4095),
        illuminance_lux REAL CHECK (illuminance_lux IS NULL OR illuminance_lux BETWEEN 0 AND 120000),
        motion_detected INTEGER CHECK (motion_detected IS NULL OR motion_detected IN (0, 1)),
        gas_adc INTEGER CHECK (gas_adc IS NULL OR gas_adc BETWEEN 0 AND 4095),
        gas_warning_local INTEGER NOT NULL CHECK (gas_warning_local IN (0, 1)),
        dht_status TEXT NOT NULL,
        ldr_status TEXT,
        pir_status TEXT NOT NULL,
        mq2_status TEXT NOT NULL,
        fan_on INTEGER,
        light_on INTEGER,
        buzzer_on INTEGER,
        valid INTEGER NOT NULL CHECK (valid IN (0, 1)),
        out_of_order INTEGER NOT NULL DEFAULT 0 CHECK (out_of_order IN (0, 1)),
        is_simulated INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
        UNIQUE (device_id, boot_id, sequence)
    );
    INSERT INTO sensor_readings_new (
        id, device_id, boot_id, sequence, measured_at, measured_ms, device_timestamp, received_at,
        timestamp_trusted, uptime_ms, temperature_c, humidity_pct, light_pct, ldr_raw, illuminance_lux,
        motion_detected, gas_adc, gas_warning_local, dht_status, ldr_status, pir_status, mq2_status,
        fan_on, light_on, buzzer_on, valid, out_of_order, is_simulated)
    SELECT
        id, device_id, boot_id, sequence, measured_at, measured_ms, device_timestamp, received_at,
        timestamp_trusted, uptime_ms, temperature_c, humidity_pct, NULL, NULL, illuminance_lux,
        motion_detected, gas_adc, gas_warning_local, dht_status, NULL, pir_status, mq2_status,
        fan_on, light_on, buzzer_on, valid, out_of_order, is_simulated
    FROM sensor_readings;
    DROP TABLE sensor_readings;
    ALTER TABLE sensor_readings_new RENAME TO sensor_readings;
    CREATE INDEX ix_readings_time ON sensor_readings(measured_ms);
    CREATE INDEX ix_readings_device_time ON sensor_readings(device_id, measured_ms);
    CREATE INDEX ix_readings_real_valid ON sensor_readings(is_simulated, valid);

    ALTER TABLE comfort_feedback ADD COLUMN light_pct REAL;
    ALTER TABLE ml_predictions ADD COLUMN light_pct REAL;
    """,
    """
    ALTER TABLE sensor_readings ADD COLUMN rain_raw INTEGER;
    ALTER TABLE sensor_readings ADD COLUMN rain_filtered INTEGER;
    ALTER TABLE sensor_readings ADD COLUMN rain_status TEXT
        CHECK (rain_status IN ('initializing', 'dry', 'rain', 'error'));
    ALTER TABLE sensor_readings ADD COLUMN window_state TEXT
        CHECK (window_state IN ('open', 'closed', 'moving', 'unknown'));
    ALTER TABLE sensor_readings ADD COLUMN servo_angle INTEGER CHECK (servo_angle BETWEEN 0 AND 180);
    ALTER TABLE sensor_readings ADD COLUMN window_auto INTEGER;

    ALTER TABLE device_status ADD COLUMN rain_status TEXT;
    ALTER TABLE device_status ADD COLUMN rain_changed_at TEXT;
    ALTER TABLE device_status ADD COLUMN window_state TEXT;
    ALTER TABLE device_status ADD COLUMN window_changed_at TEXT;
    """,
]


PG_BASE_VERSION = 3

PG_SCHEMA = """
CREATE TABLE users (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
    created_at TEXT NOT NULL
);

CREATE TABLE sessions (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    csrf_token TEXT NOT NULL,
    user_id BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1))
);
CREATE INDEX ix_sessions_user ON sessions(user_id);

CREATE TABLE sensor_readings (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    device_id TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    sequence BIGINT NOT NULL CHECK (sequence >= 0),
    measured_at TEXT NOT NULL,
    measured_ms BIGINT NOT NULL,
    device_timestamp TEXT,
    received_at TEXT NOT NULL,
    timestamp_trusted INTEGER NOT NULL CHECK (timestamp_trusted IN (0, 1)),
    uptime_ms BIGINT CHECK (uptime_ms IS NULL OR uptime_ms >= 0),
    temperature_c DOUBLE PRECISION CHECK (temperature_c IS NULL OR temperature_c BETWEEN -40 AND 80),
    humidity_pct DOUBLE PRECISION CHECK (humidity_pct IS NULL OR humidity_pct BETWEEN 0 AND 100),
    light_pct DOUBLE PRECISION CHECK (light_pct IS NULL OR light_pct BETWEEN 0 AND 100),
    ldr_raw INTEGER CHECK (ldr_raw IS NULL OR ldr_raw BETWEEN 0 AND 4095),
    illuminance_lux DOUBLE PRECISION CHECK (illuminance_lux IS NULL OR illuminance_lux BETWEEN 0 AND 120000),
    motion_detected INTEGER CHECK (motion_detected IS NULL OR motion_detected IN (0, 1)),
    gas_adc INTEGER CHECK (gas_adc IS NULL OR gas_adc BETWEEN 0 AND 4095),
    gas_warning_local INTEGER NOT NULL CHECK (gas_warning_local IN (0, 1)),
    dht_status TEXT NOT NULL,
    ldr_status TEXT,
    pir_status TEXT NOT NULL,
    mq2_status TEXT NOT NULL,
    fan_on INTEGER,
    light_on INTEGER,
    buzzer_on INTEGER,
    valid INTEGER NOT NULL CHECK (valid IN (0, 1)),
    out_of_order INTEGER NOT NULL DEFAULT 0 CHECK (out_of_order IN (0, 1)),
    is_simulated INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
    rain_raw INTEGER,
    rain_filtered INTEGER,
    rain_status TEXT CHECK (rain_status IN ('initializing', 'dry', 'rain', 'error')),
    window_state TEXT CHECK (window_state IN ('open', 'closed', 'moving', 'unknown')),
    servo_angle INTEGER CHECK (servo_angle BETWEEN 0 AND 180),
    window_auto INTEGER,
    UNIQUE (device_id, boot_id, sequence)
);
CREATE INDEX ix_readings_time ON sensor_readings(measured_ms);
CREATE INDEX ix_readings_device_time ON sensor_readings(device_id, measured_ms);
CREATE INDEX ix_readings_real_valid ON sensor_readings(is_simulated, valid);

CREATE TABLE ingest_rejections (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    received_at TEXT NOT NULL,
    device_id TEXT,
    reason TEXT NOT NULL CHECK (reason IN ('invalid', 'duplicate', 'unauthorized', 'too_large', 'rate_limited'))
);
CREATE INDEX ix_rejections_reason ON ingest_rejections(reason);

CREATE TABLE device_status (
    device_id TEXT PRIMARY KEY,
    is_simulated INTEGER NOT NULL CHECK (is_simulated IN (0, 1)),
    last_seen_at TEXT,
    last_boot_id TEXT,
    fan_on INTEGER,
    light_on INTEGER,
    buzzer_on INTEGER,
    gas_warning_local INTEGER NOT NULL DEFAULT 0,
    state_reported_at TEXT,
    rain_status TEXT,
    rain_changed_at TEXT,
    window_state TEXT,
    window_changed_at TEXT
);

CREATE TABLE device_events (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    device_id TEXT NOT NULL,
    target TEXT NOT NULL CHECK (target IN ('fan', 'light', 'buzzer', 'alarm', 'all')),
    state TEXT NOT NULL CHECK (state IN ('on', 'off', 'mute')),
    source TEXT NOT NULL CHECK (source IN ('user', 'rule', 'ml', 'safety', 'system')),
    requested_by TEXT,
    reason TEXT,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'acked', 'rejected', 'expired', 'superseded')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    sent_at TEXT,
    acked_at TEXT,
    ack_result TEXT CHECK (ack_result IS NULL OR ack_result IN ('applied', 'rejected', 'expired')),
    ack_reason TEXT,
    observed_fan INTEGER,
    observed_light INTEGER,
    observed_buzzer INTEGER
);
CREATE INDEX ix_events_device_status ON device_events(device_id, status);
CREATE INDEX ix_events_created ON device_events(created_at);

CREATE TABLE comfort_feedback (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    created_at TEXT NOT NULL,
    user_id BIGINT REFERENCES users(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    reading_id BIGINT REFERENCES sensor_readings(id) ON DELETE SET NULL,
    device_id TEXT,
    temperature_c DOUBLE PRECISION,
    humidity_pct DOUBLE PRECISION,
    illuminance_lux DOUBLE PRECISION,
    motion_detected INTEGER,
    context_age_s DOUBLE PRECISION,
    context_simulated INTEGER NOT NULL CHECK (context_simulated IN (0, 1)),
    note TEXT CHECK (note IS NULL OR length(note) <= 200),
    light_pct DOUBLE PRECISION
);
CREATE INDEX ix_feedback_created ON comfort_feedback(created_at);

CREATE TABLE ml_predictions (
    id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    created_at TEXT NOT NULL,
    model_version TEXT NOT NULL,
    reading_id BIGINT REFERENCES sensor_readings(id) ON DELETE SET NULL,
    predicted_comfort DOUBLE PRECISION NOT NULL,
    temperature_c DOUBLE PRECISION,
    humidity_pct DOUBLE PRECISION,
    illuminance_lux DOUBLE PRECISION,
    motion_detected INTEGER,
    light_pct DOUBLE PRECISION
);
CREATE INDEX ix_predictions_created ON ml_predictions(created_at);

CREATE TABLE settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
"""

# later postgres migrations go here, one per sqlite migration after v3
PG_MIGRATIONS: list[str] = []

PG_TABLES = ("users", "sessions", "sensor_readings", "ingest_rejections", "device_status", "device_events",
             "comfort_feedback", "ml_predictions", "settings", "schema_version")

# supabase exposes public tables through its REST api, so lock them to the backend only
PG_LOCKDOWN = """
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY['%s'] LOOP
        EXECUTE format('ALTER TABLE %%I ENABLE ROW LEVEL SECURITY', t);
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
            EXECUTE format('REVOKE ALL ON %%I FROM anon', t);
        END IF;
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
            EXECUTE format('REVOKE ALL ON %%I FROM authenticated', t);
        END IF;
    END LOOP;
END $$;
""" % "','".join(PG_TABLES)


def to_pg_sql(sql: str) -> str:
    out = []
    quoted = False
    for ch in sql:
        if ch == "'":
            quoted = not quoted
        if not quoted and ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


class Row:
    __slots__ = ("_index", "_values")

    def __init__(self, index: dict[str, int], values):
        self._index = index
        self._values = values

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def __len__(self) -> int:
        return len(self._values)

    def __iter__(self):
        return iter(self._values)

    def keys(self) -> list[str]:
        return list(self._index)


def _row_factory(cursor):
    desc = cursor.description
    if desc is None:
        return tuple
    index = {col.name: i for i, col in enumerate(desc)}
    return lambda values: Row(index, values)


class PgCursor:
    def __init__(self, cur):
        self._cur = cur

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)


class PgConnection:
    def __init__(self, raw):
        self.raw = raw

    def execute(self, sql: str, params=()) -> PgCursor:
        cur = self.raw.cursor(row_factory=_row_factory)
        cur.execute(to_pg_sql(sql), tuple(params))
        return PgCursor(cur)


class PostgresDatabase:
    dialect = "postgres"

    def __init__(self, url: str, pool_size: int = 4):
        self.url = url
        self.pool_size = pool_size
        self._pool = None
        self._pool_lock = threading.Lock()
        self._write_lock = threading.RLock()

    def _get_pool(self):
        with self._pool_lock:
            if self._pool is None:
                from psycopg_pool import ConnectionPool

                # prepare_threshold=None keeps it working behind the supabase pooler
                self._pool = ConnectionPool(
                    self.url, min_size=1, max_size=self.pool_size, timeout=15, open=True,
                    kwargs={"prepare_threshold": None, "connect_timeout": 10, "application_name": "smartbuddy"},
                )
            return self._pool

    def close(self) -> None:
        with self._pool_lock:
            if self._pool is not None:
                self._pool.close()
                self._pool = None

    @contextmanager
    def session(self) -> Iterator[PgConnection]:
        with self._get_pool().connection() as raw:
            yield PgConnection(raw)

    @contextmanager
    def transaction(self) -> Iterator[PgConnection]:
        # one writer at a time, same as BEGIN IMMEDIATE on sqlite
        with self._write_lock:
            with self._get_pool().connection() as raw:
                with raw.transaction():
                    yield PgConnection(raw)

    def init(self) -> int:
        with self._write_lock, self._get_pool().connection() as raw:
            with raw.transaction():
                raw.execute("SELECT pg_advisory_xact_lock(724001)")
                raw.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
                row = raw.execute("SELECT MAX(version) FROM schema_version").fetchone()
                version = row[0] if row and row[0] is not None else 0
                if version == 0:
                    log.info("creating postgres schema v%d", PG_BASE_VERSION)
                    raw.execute(PG_SCHEMA)
                    version = PG_BASE_VERSION
                    raw.execute("INSERT INTO schema_version (version) VALUES (%s)", (version,))
                for index in range(version - PG_BASE_VERSION, len(PG_MIGRATIONS)):
                    log.info("applying postgres migration %d", PG_BASE_VERSION + index + 1)
                    raw.execute(PG_MIGRATIONS[index])
                    version = PG_BASE_VERSION + index + 1
                    raw.execute("UPDATE schema_version SET version = %s", (version,))
                raw.execute(PG_LOCKDOWN)
            return version

    def ping(self) -> bool:
        try:
            with self.session() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False


def open_database(settings):
    if settings.database_url:
        return PostgresDatabase(settings.database_url)
    return Database(settings.database_path)


class Database:
    dialect = "sqlite"

    def __init__(self, path: Path):
        self.path = Path(path)

    def close(self) -> None:
        pass

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @contextmanager
    def session(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        conn = self.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    def init(self) -> int:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = self.connect()
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            for index in range(version, len(MIGRATIONS)):
                log.info("applying database migration %d", index + 1)
                conn.execute("PRAGMA foreign_keys = OFF")
                conn.executescript("BEGIN;\n" + MIGRATIONS[index] + f"\nPRAGMA user_version = {index + 1};\nCOMMIT;")
                broken = conn.execute("PRAGMA foreign_key_check").fetchall()
                conn.execute("PRAGMA foreign_keys = ON")
                if broken:
                    raise sqlite3.IntegrityError(f"migration {index + 1} left {len(broken)} broken foreign keys")
            return conn.execute("PRAGMA user_version").fetchone()[0]
        finally:
            conn.close()

    def ping(self) -> bool:
        try:
            with self.session() as conn:
                conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str, updated_at: str, updated_by: str | None) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at, updated_by) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at, "
        "updated_by = excluded.updated_by",
        (key, value, updated_at, updated_by),
    )
