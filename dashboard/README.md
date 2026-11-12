# SmartBuddy dashboard (backend, frontend, ML)

```
dashboard/
├── backend/      FastAPI app (python -m backend.main)
├── frontend/     React + TypeScript + Vite + Tailwind
├── ml/           dataset prep, training, evaluation, inference
├── data/         SQLite DB (created on first start) + datasets
├── tests/        pytest suites
├── requirements.txt / requirements-dev.txt
└── .env.example  copy to .env
```

All commands below are run from the `dashboard/` folder unless stated otherwise. Paths in `.env` are resolved
relative to `dashboard/`, so it doesn't matter where you start the server from.

## Prerequisites

- Python 3.11+ (developed with 3.12)
- Node.js 20+ (developed with 22) and npm
- No MQTT broker: the device uses HTTP

## 1. Python environment

```powershell
cd dashboard
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements-dev.txt     # or requirements.txt without test tools
```

## 2. Configuration

```powershell
copy .env.example .env
.\.venv\Scripts\python ..\scripts\hash_password.py          # -> ADMIN_PASSWORD_HASH=...
.\.venv\Scripts\python ..\scripts\gen_device_key.py sb-esp32-01   # -> DEVICE_KEYS=... + key for the serial bridge
```
Paste both lines into `.env`. Optional: `hash_password.py --viewer` for a read-only account (also set `VIEWER_USERNAME`).

Keep `HOST=127.0.0.1`. The ESP32 (New_Code.ino) has no Wi-Fi: it's plugged into this laptop over USB, and
`scripts/serial_bridge.py` forwards its readings to the backend locally (see [`../iot/README.md`](../iot/README.md)).
Keep the device key printed by `gen_device_key.py` for the bridge (`$env:SMARTBUDDY_DEVICE_KEY`).

The dashboard is monitor-only (`DEVICE_CONTROL_ENABLED=false`): the firmware's own rules switch the fan, LED and
buzzer, and the command endpoints return 409.

## 3. Database

Nothing to do for SQLite: the schema is created/migrated automatically on startup (`PRAGMA user_version` migrations
in `backend/database.py`). The file is `data/smartbuddy.db` and survives restarts.
To start fresh, stop the backend and delete `data/smartbuddy.db*`.

**Supabase (optional):** set `DATABASE_URL` in `.env` and the backend uses that Postgres database instead. The
tables are created on startup, and `scripts/move_to_supabase.py` copies the existing SQLite data over once.

**Hosting on Render (optional):** with the data in Supabase, the backend + built dashboard can run on Render's
free plan so the laptop isn't needed (`render.yaml` in the repo root).

## 4. Start the backend

```powershell
.\.venv\Scripts\python -m backend.main
```
or `powershell -ExecutionPolicy Bypass -File ..\scripts\start_backend.ps1`.
Check it at http://127.0.0.1:8000/api/v1/health → `{"status":"ok"}`.

## 5. Start the frontend

```powershell
cd frontend
npm install        # first time; creates package-lock.json. Afterwards use: npm ci
npm run dev
```
Open http://127.0.0.1:5173 and sign in. Vite proxies `/api` and `/ws` to the backend.

**Production build:** `npm run build` writes `frontend/dist/`. When that folder exists, the backend serves the app
itself at http://127.0.0.1:8000 (same origin, CSP applied), so Vite isn't needed.

## 6. Try it without hardware (labelled simulator)

```powershell
.\.venv\Scripts\python ..\scripts\gen_device_key.py sim-01 --simulator
```
Add `SIMULATOR_KEYS=sim-01:<hash>` and `ALLOW_SIMULATOR=true` to `.env`, restart the backend, then:
```powershell
.\.venv\Scripts\python ..\scripts\simulate_device.py --device-id sim-01 --key <key>
```
Everything it sends is stored with `is_simulated = 1`, badged "Simulated data" in the UI, and excluded from the
real-reading count, CSV exports (unless asked for) and ML training. Set `ALLOW_SIMULATOR=false` again for real collection.

## 7. Tests, audits, builds

```powershell
.\.venv\Scripts\python -m pytest                      # backend + ml + security
.\.venv\Scripts\python ..\scripts\smoke_test.py       # end-to-end against a throwaway server
.\.venv\Scripts\python ..\scripts\check_secrets.py
.\.venv\Scripts\pip-audit -r requirements.txt
cd frontend
npm run typecheck
npm run lint
npm run build
npm audit
```

## 8. ML workflow

```powershell
.\.venv\Scripts\python -m ml.prepare_dataset                            # -> data/processed/comfort_dataset.csv
.\.venv\Scripts\python -m ml.train_model --plot --publish                # -> ml/models/ + database
.\.venv\Scripts\python -m ml.evaluate_model --dataset path\to\new_ratings.csv
.\.venv\Scripts\python -m ml.forecast --horizon 5 --publish                # room forecast -> ml/models/forecast/ + database
```
- Admins can also press **Train now** on the ML evaluation page (`POST /api/v1/ml/train`). It does the same
  thing on the server, on Render too.
- Training refuses to run with fewer than 30 ratings or fewer than 2 sessions (user × day). That's the expected
  result until you've collected enough feedback.
- A model is deployed only if it beats the mean-predicting baseline on held-out sessions.
- The deployed model is saved in the `ml_models` table. Every backend checks it every 30 s, writes it to
  `ml/models/` (local copy) and loads it after the hash check. Without `--publish` the CLI only writes
  `ml/models/`, and a model in the database wins over it.
- An external labelled CSV can be imported with `--csv data/raw/file.csv` after you've checked its source and
  licence. Required columns: `recorded_at, session_id, temperature_c, humidity_pct, light_pct, comfort_rating` (optional `motion_detected`, `source`).

## API overview

| Method | Path | Who |
|---|---|---|
| GET | `/api/v1/health`, `/api/v1/ready` | anyone |
| POST | `/api/v1/auth/login`, `/auth/logout`; GET `/auth/me` | |
| GET | `/api/v1/readings/latest`, `/readings`, `/readings/series`, `/stats` | signed in |
| GET | `/api/v1/readings/export.csv` | admin |
| GET | `/api/v1/devices/state`, `/devices/commands`, `/devices/commands/{id}` | signed in |
| POST | `/api/v1/devices/commands`, `/devices/emergency-stop`, `/devices/alarm/mute` | admin + CSRF |
| GET / PUT | `/api/v1/mode` | signed in / admin + CSRF |
| GET | `/api/v1/warnings` | signed in |
| GET / POST | `/api/v1/feedback` | signed in (+ CSRF for POST) |
| GET | `/api/v1/ml/status`, `/ml/evaluation`, `/ml/advice` | signed in |
| POST | `/api/v1/ml/train` | admin + CSRF |
| GET | `/api/v1/ml/forecast` | signed in |
| POST | `/api/v1/ml/forecast/train?horizon=5` | admin + CSRF |
| POST/GET | `/api/v1/device/readings`, `/device/commands`, `/device/acks` | device key |
| WS | `/ws/live` | signed in, allowed Origin |

Range queries take ISO-8601 `start`/`end` with a timezone, default to the last 24 h and are capped at 31 days.
Pages are at most 500 rows.
