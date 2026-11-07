# SmartBuddy

**AIoT smart home companion for personalised environmental comfort prediction and gas/smoke indication monitoring.**

An ESP32 measures temperature, humidity, light, motion, rain and an MQ-2 gas/smoke indication, and switches a fan,
an LED, a buzzer and a servo that closes a miniature window when it rains. A FastAPI backend stores everything in Supabase (cloud Postgres) or a local SQLite file and serves a React dashboard. You rate how
comfortable the room feels (1–5), and a small ML model learns to estimate that rating from the conditions.

> The MQ-2 is an uncalibrated hobby sensor. SmartBuddy's gas indication is experimental and **not** a certified
> smoke, fire or gas detector.

## Academic objectives

1. Continuous acquisition of **≥ 1,000 valid, timestamped real sensor records** (tracked live in the dashboard and
   by `scripts/collect_status.py`; simulated data never counts).
2. Remote monitoring and control through a web dashboard, with device acknowledgements.
3. A supervised ML model (baseline vs decision tree vs random forest, MAE/RMSE, grouped split) trained on **real
   user comfort ratings**, with an honest "insufficient data" state until enough ratings exist.
4. Rule-based safety that is independent of ML.
5. Security-conscious design (authentication, input validation, least exposure, documented residual risks).

## Repository layout

```
.
├── iot/                    ESP32 firmware (Arduino IDE sketch) + library list
│   └── firmware/smartbuddy_esp32/New_Code/New_Code.ino   (sketch; Wi-Fi login in gitignored secrets.h)
├── dashboard/
│   ├── backend/            FastAPI + Supabase/Postgres (or SQLite)
│   ├── frontend/           React + TypeScript + Vite + Tailwind
│   ├── ml/                 dataset prep, training, evaluation, inference
│   ├── data/               database + datasets (gitignored contents)
│   └── tests/              pytest: backend, ml, security
├── docs/                   architecture, wiring, protocol, data dictionary, tests, security
└── scripts/                key/hash generators, simulator, smoke test, secret check, start scripts
```

Firmware and web application are deliberately separate. The firmware needs only Arduino IDE; the dashboard
needs Python and Node.

## How the parts talk

HTTP, no MQTT broker.
- The firmware (`New_Code.ino`) runs its own fan/LED/buzzer/window rules and POSTs a reading to the backend
  over Wi-Fi every 2 s (`POST /api/v1/device/readings`, device key in the gitignored `secrets.h`).
- Without Wi-Fi, `scripts/serial_bridge.py` can forward the same data from the USB serial CSV instead.
- The browser uses REST plus a WebSocket for live updates.
- The dashboard is **monitor-only**: it shows what the firmware switched, but can't switch anything itself.

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DEVICE_PROTOCOL.md](docs/DEVICE_PROTOCOL.md).

## Hardware

ESP32 DevKit V1 · DHT22 · LDR · HC-SR501 PIR · MQ-2 module (with a 10 k / 15 k divider) · DC fan with a
logic-level MOSFET driver + flyback diode · ordinary LED + 220–330 Ω · active buzzer · optional SSD1306 OLED ·
raindrop sensor module · SG90 servo on a separate regulated 5 V supply.

| Signal | GPIO |
|---|---|
| DHT22 data | 5 |
| I²C SDA / SCL (OLED) | 21 / 22 |
| PIR out | 27 |
| MQ-2 AO (via divider) | 34 |
| LDR | 35 |
| Fan driver | 25 |
| LED | 4 |
| Buzzer (active low) | 19 |
| Raindrop sensor AO | 32 |
| SG90 servo signal | 33 |

Full wiring, power and safety notes: [docs/WIRING.md](docs/WIRING.md).

### Rain detection & automatic window

The raindrop sensor (AO on GPIO 32) is averaged over 8 samples. Rain for 2 s closes the window (servo to 90°),
10 seconds of dry readings open it again (0°). If the sensor reading gets stuck at 0 for 30 s it's reported as an
error and the window **keeps its position**. The last position is saved on the ESP32, so a restart doesn't make
the servo jump. All of this runs on the ESP32, so it works with the dashboard closed. The dashboard shows rain
status, raw/filtered values, window state, servo angle and when it last changed (Home and Devices pages).

Wiring, the servo power supply and calibration: [iot/README.md](iot/README.md#rain-sensor-and-window-servo).
This is a miniature demo model, not a weatherproofing or safety device.

## Quick start

Prerequisites: Arduino IDE 2.x, Python 3.11+, Node.js 20+, Git. No cloud accounts.

1. **Backend**: see [dashboard/README.md](dashboard/README.md):
   ```powershell
   cd dashboard
   python -m venv .venv
   .\.venv\Scripts\pip install -r requirements-dev.txt
   copy .env.example .env
   .\.venv\Scripts\python ..\scripts\hash_password.py
   .\.venv\Scripts\python ..\scripts\gen_device_key.py sb-esp32-01
   # paste both outputs into .env
   .\.venv\Scripts\python -m backend.main
   ```
2. **Frontend**:
   ```powershell
   cd dashboard\frontend
   npm install
   npm run dev       # http://127.0.0.1:5173
   ```
3. **Firmware**: see [iot/README.md](iot/README.md). Open `iot/firmware/smartbuddy_esp32/New_Code/New_Code.ino`
   and Verify/Upload in Arduino IDE. The firmware holds no credentials.
4. **Serial bridge**: with the ESP32 plugged in over USB and the Arduino Serial Monitor closed:
   ```powershell
   $env:SMARTBUDDY_DEVICE_KEY = "<key printed by gen_device_key.py>"
   dashboard\.venv\Scripts\python scripts\serial_bridge.py --port COM5   # --list-ports to find it
   ```
   The backend stays on `127.0.0.1`, so nothing needs to be opened on your network.

No hardware yet? Use the labelled simulator ([dashboard/README.md §6](dashboard/README.md)).

## Data collection

Leave the ESP32 and the bridge running. The firmware prints a row every 2 s and the bridge forwards each one, so
1,000 uninterrupted readings take about 33 min 20 s. Expect longer because of unplugged cables, ESP32 restarts
and DHT22 read failures (a reading is valid only with temperature, humidity and light level). Progress is on the Overview page and in
`python scripts/collect_status.py`. Export the CSV from History as evidence. The procedure is in
[docs/TEST_PLAN.md §5](docs/TEST_PLAN.md).

1,000 sensor readings ≠ 1,000 training samples: a training sample needs a human comfort rating.

## ML workflow

1. Rate comfort on the **Comfort** page on several different days, in varied conditions.
2. `python -m ml.prepare_dataset` (from `dashboard/`; reads the same database as the backend)
3. `python -m ml.train_model --plot`
4. View results on the **ML evaluation** page.

Below 30 ratings / 2 sessions, training refuses and the dashboard says so. A model that doesn't beat the
mean baseline isn't deployed. No metrics are shown that weren't actually computed.

## Operating modes and safety

`MANUAL`, `RULE_BASED`, `ML_RECOMMENDATION` (default, never switches anything) and `ML_AUTOMATIC` (off unless
explicitly enabled and a validated model exists). Gas handling runs on the device and in `backend/safety.py`,
independent of ML. A gas warning never starts the fan automatically; starting it by hand during a warning
needs explicit confirmation. The emergency stop switches everything off. If the device loses the backend
for 30 s, it switches fan and LED off itself.

## Testing and security

- `cd dashboard; .\.venv\Scripts\python -m pytest`
- `python scripts/smoke_test.py`: ~60 end-to-end HTTP checks against a throwaway server
- `python scripts/check_secrets.py` before every commit
- `pip-audit` and `npm audit`: see [docs/SECURITY.md](docs/SECURITY.md)
- Plans: [docs/TEST_PLAN.md](docs/TEST_PLAN.md), [docs/SECURITY_TEST_PLAN.md](docs/SECURITY_TEST_PLAN.md)

## Known limitations

- Device ↔ backend traffic is plain HTTP on the LAN (TLS option documented, not implemented).
- MQ-2 values are raw ADC counts, uncalibrated, and vary per module.
- The PIR detects infrared change, not people.
- Acknowledgements confirm GPIO levels, not physical motion of the fan.
- The window state is the angle the ESP32 commanded. There's no sensor that confirms the window moved.
- The raindrop sensor thresholds are defaults and need calibrating for your module.
- The comfort model only reflects the people who rated, in the rooms they rated. Small datasets give unstable metrics.
- Single-process backend: the rate limits and live hub are in memory.

More in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) and [docs/SECURITY.md](docs/SECURITY.md).
