# SmartBuddy firmware (ESP32, Arduino IDE)

The firmware in use is **`firmware/smartbuddy_esp32/New_Code/New_Code.ino`** (v1.3.0).

- Sensors: DHT22 (temperature/humidity), LDR (light level %), HC-SR501 PIR, MQ-2 gas/smoke indication, optional SSD1306 OLED.
- Its own rules switch the fan, LED and buzzer (below). The dashboard can't switch them.
- Every 2 s it sends a reading to the dashboard backend over **Wi-Fi + HTTP POST**. The rules keep running
  when there's no Wi-Fi.
- It still prints the same data on USB serial, so `scripts/serial_bridge.py` works as a fallback.

```
ESP32 --Wi-Fi, HTTP POST--> laptop: backend (port 8000) --REST + WebSocket--> dashboard
```

Wiring: [`docs/WIRING.md`](../docs/WIRING.md). Data format: [`docs/DEVICE_PROTOCOL.md`](../docs/DEVICE_PROTOCOL.md).

## Pins (New_Code.ino)

| Part | GPIO | Notes |
|---|---|---|
| LED | 4 | Through 220–330 Ω, active HIGH |
| DHT22 data | 5 | Strapping pin: must be HIGH at boot. Keep the 10 kΩ pull-up to 3.3 V |
| Buzzer | 19 | **Active LOW** (`BUZZER_ACTIVE_LEVEL = LOW`) |
| OLED SDA / SCL | 21 / 22 | Auto-swapped if the OLED answers the other way round |
| PIR out | 27 | |
| MQ-2 AO | 34 | Through the 10 k / 15 k divider |
| LDR | 35 | LDR module AO, or LDR + 10 kΩ divider |
| Fan driver | 25 | MOSFET gate only, never the fan directly |
| Raindrop sensor AO | 32 | Module powered from 3.3 V so AO stays below 3.3 V |
| SG90 servo signal | 33 | Servo power from a separate regulated 5 V, GND shared with the ESP32 |

## Firmware rules

| Output | Rule |
|---|---|
| Fan | On above 26.0 °C (from 26.1 °C), off at ≤ 25.5 °C, holds in between or if the DHT22 is unavailable |
| LED | On when light ≤ 30 %, off at ≥ 40 %, holds in between |
| Buzzer | 500 ms on/off pattern while the MQ-2 alarm is active: filtered ADC > 1800 for 3 s (after the 120 s warm-up), clears below 1700 after at least 5 s |
| Window (servo) | Closes (90°) after 2 s of rain, opens (0°) after 10 s dry. Holds its position while the rain sensor is starting or has an error |

The gas alarm never switches the fan on. The thresholds are constants at the top of `New_Code.ino`. If you
change the MQ-2 ones, also change `GAS_WARNING_ADC` / `GAS_CLEAR_ADC` in `dashboard/.env` so the dashboard
warning matches.

## 1. Libraries

See [`libraries.md`](libraries.md): the ESP32 board package plus DHT sensor library, Adafruit Unified Sensor,
Adafruit GFX and Adafruit SSD1306.

## 2. Wi-Fi settings (secrets.h)

The sketch needs a `secrets.h` next to `New_Code.ino`. It's gitignored because it holds your Wi-Fi password and
the device key. Without it the sketch doesn't compile and says so.

Easiest way, from the project root:
```powershell
dashboard\.venv\Scripts\python scripts\make_firmware_secrets.py --ssid "YourWifiName"
```
It asks for the Wi-Fi password, fills in this laptop's IP address and the device key from
`dashboard/.env.bridge-key`, and checks the key against `dashboard/.env`.

By hand: copy `secrets.example.h` to `secrets.h` and fill in all six values.

- The ESP32 only joins **2.4 GHz** Wi-Fi. A phone hotspot works. Networks with a username and password login page
  (eduroam, hotel Wi-Fi) don't.
- The laptop has to be on the same network. `BACKEND_HOST` is the laptop's IPv4 address there (`ipconfig`). If
  the laptop gets a new address, update `secrets.h` and upload again.

## 3. Compile and upload

1. *File → Open…* → `iot/firmware/smartbuddy_esp32/New_Code/New_Code.ino`.
2. *Tools → Board → esp32 → **ESP32 Dev Module***, and *Tools → Port* → your COM port.
3. **Verify** (✓), then **Upload** (→). If upload hangs on `Connecting...`, hold **BOOT**.
4. *Tools → Serial Monitor* at **115200**. After the start-up banner you should see
   `[NET] Wi-Fi connected, IP ...` and then `[NET] Backend reachable, sending readings (HTTP 201)`.
   The OLED's System page shows `Link OK -55dBm` (or `no Wi-Fi` / `no server`).

## 4. Let the ESP32 reach the backend

On the laptop, once:

1. In `dashboard/.env` set `HOST=0.0.0.0` (it's `127.0.0.1` by default, which only the laptop itself can reach).
   Keep `LAN_DEVICE_ONLY=true`: other machines then only get the device endpoints, not the dashboard or login.
2. Mark your Wi-Fi as a **Private** network: *Settings → Network & internet → Wi-Fi → (your network) → Private*.
3. Allow port 8000 from your local network only (PowerShell **as Administrator**):
   ```powershell
   New-NetFirewallRule -DisplayName "SmartBuddy backend (LAN)" -Direction Inbound -Protocol TCP `
     -LocalPort 8000 -RemoteAddress LocalSubnet -Profile Private -Action Allow
   ```
4. Restart the backend. It logs a warning that it's reachable from the network, which is expected.

Check it from the laptop: `http://<laptop IP>:8000/api/v1/health` should return `{"status":"ok",...}`.

## 5. Fallback: USB serial bridge

No Wi-Fi available? Plug the ESP32 into the laptop and run the bridge instead. It reads the CSV and sends
the same readings to `127.0.0.1`, so `HOST` can stay `127.0.0.1`. Don't run it while the ESP32 is also on
Wi-Fi, or every reading is stored twice.

```powershell
$env:SMARTBUDDY_DEVICE_KEY = Get-Content dashboard\.env.bridge-key
dashboard\.venv\Scripts\python scripts\serial_bridge.py --port COM4
```
Close the Arduino Serial Monitor first; only one program can use the port.

## Behaviour you should know about

- **Safe boot:** fan, LED and buzzer are set OFF first in `setup()`. The LED blinks 3 times as a self-test.
- **Warm-up:** PIR 60 s, MQ-2 120 s. The dashboard shows "warming up" instead of values during that time.
- **Sensor errors** are reported as errors with no value (DHT22 after 3 failed reads, MQ-2 if it reads ~0
  for 30 s). They're never filled in with guesses.
- **No connection needed:** the rules and the gas alarm keep running without Wi-Fi or the backend.
  Up to 2 minutes of readings are queued and sent once the backend is back.
- **MQ-2** values are relative ADC counts. This is **not** ppm and **not** a certified gas or smoke detector.
- **LDR** light % is relative (0 = dark, 100 = bright), not lux. If covering the LDR makes Light% go *up*, flip
  `LDR_INVERT`.
- **PIR** reports infrared change, not "a person is present".

## Rain sensor and window servo

### Wiring

| Part | Pin | Connect to |
|---|---|---|
| Raindrop module | VCC | **3V3** (check your module works at 3.3 V; most LM393 boards do) |
| | GND | GND |
| | AO | **GPIO 32** |
| | DO | not connected |
| SG90 servo | Red | **+5 V of a separate regulated supply**, never the ESP32's 3V3 pin |
| | Brown | GND of that supply, **also connected to ESP32 GND** |
| | Orange / yellow | **GPIO 33** |

The SG90 can pull 500–700 mA when it starts or stalls. Powering it from the ESP32 board causes brown-out resets,
which is why it gets its own 5 V supply. A 470–1000 µF capacitor across the servo's 5 V and GND smooths the
spikes. The module runs on 3.3 V, so AO can't go above the ESP32's 3.3 V limit.

### Calibrate before relying on it

The thresholds are guesses until you check them against your own module:

1. Upload, open the Serial Monitor at 115200 and type `h` + Send for the detailed report. The `Rain` line shows
   `raw` and `avg`.
2. Note `avg` with the sensor plate **dry**, then put a few drops of water on it and note `avg` again.
3. Most modules read **lower when wet** (dry ≈ 3500–4095, wet ≈ 1000–2500). If yours reads higher when wet, set
   `RAIN_WHEN_LOW = false`.
4. Put `RAIN_ON_ADC` a bit on the dry side of your wet value, and `RAIN_OFF_ADC` a few hundred counts further
   towards dry. The gap between them is the hysteresis: readings in between change nothing.
5. If your dry plate reads ~0 with `RAIN_WHEN_LOW = false`, the stuck-at-zero error check would trigger: set
   `RAIN_ERROR_LOW_ADC` to `-1` to switch it off. `RAIN_ERROR_HIGH_ADC = 4096` means the stuck-high check is
   off, because a dry module often sits at 4095.

### Servo angles

`WINDOW_OPEN_ANGLE = 0` and `WINDOW_CLOSED_ANGLE = 90` are starting points. Test with the window linkage
disconnected first, then adjust the two constants until the window really closes and opens without the servo
straining (a buzzing servo at the end position is pushing against something). If the servo doesn't reach the
ends, adjust `SERVO_MIN_US` / `SERVO_MAX_US` (500 / 2400 µs by default).

### Timing and behaviour

| Constant | Default | Meaning |
|---|---|---|
| `RAIN_CONFIRM_MS` | 2000 | Rain must be seen this long before the status changes to rain |
| `DRY_CONFIRM_MS` | 2000 | Same for dry |
| `WINDOW_REOPEN_DRY_MS` | 10000 | Dry for this long before the window opens again |
| `RAIN_ERROR_MS` | 30000 | Reading stuck at a limit this long = sensor error |
| `WINDOW_AUTO_ENABLED` | true | `false` keeps the window where it is |
| `SERVO_STEP_MS` | 15 | 1° per step, so 90° takes about 1.4 s |

- The servo only moves when the target changes. It never re-sends a position it's already at.
- On a sensor error or while the sensor is starting, the window stays where it is. It's never opened because
  of an error.
- The last position is saved in the ESP32's flash after each move. At start-up the servo is sent to that position
  (or to closed on the very first start).
- The window state on the dashboard is the angle the ESP32 sent. There's no sensor that confirms the window
  physically moved.
- The OLED has a fifth page, *Rain/window*. The serial table has `Rain` and `Window` columns, and the CSV has
  five extra columns at the end (see `docs/DEVICE_PROTOCOL.md`).

## Common errors

| Symptom | Fix |
|---|---|
| `secrets.h is missing` when compiling | Run `scripts/make_firmware_secrets.py`, or copy `secrets.example.h` to `secrets.h` |
| `[NET] Still no Wi-Fi` | Wrong name/password, or a 5 GHz-only network. Use 2.4 GHz (a phone hotspot works) |
| `[NET] HTTP -1: backend not reachable` | Backend not running, `HOST` still `127.0.0.1`, firewall rule missing, network marked Public, or the laptop IP changed |
| `[NET] HTTP 401` | `DEVICE_KEY` in `secrets.h` doesn't match `DEVICE_KEYS` in `.env`. Restart the backend after editing `.env` |
| `[NET] HTTP 403` | `DEVICE_ID` in `secrets.h` isn't the device the key was made for |
| Bridge: `can't open COM4` | Close the Arduino Serial Monitor; check the port with `--list-ports` |
| Dashboard "Device offline" | No reading for 15 s: check the Serial Monitor for `[NET]` lines |
| Buzzer sounds constantly | Active-high buzzer on an active-low setting. Set `BUZZER_ACTIVE_LEVEL = HIGH` |
| ESP32 resets when the window moves | Servo powered from the ESP32. Give it its own 5 V supply (shared GND) and a 470 µF capacitor |
| Window opens/closes at the wrong time | Calibrate the rain thresholds (see *Rain sensor and window servo*) |
| Board won't boot with DHT22 attached | GPIO5 is a strapping pin. Check the pull-up, or move DHT to another GPIO and change `DHT_PIN` |

More in [`docs/TROUBLESHOOTING.md`](../docs/TROUBLESHOOTING.md).
