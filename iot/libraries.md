# Arduino libraries

For `firmware/smartbuddy_esp32/New_Code/New_Code.ino`. All of these come from the official Arduino Library
Manager index.

| Library (Library Manager name) | Author | Version on the dev PC | Used for |
|---|---|---|---|
| **esp32** board package | Espressif Systems | 3.3.12 | Core, `Wire`, ADC, `WiFi`, `HTTPClient` |
| DHT sensor library | Adafruit | 1.4.7 | DHT22 |
| Adafruit Unified Sensor | Adafruit | 1.1.15 | Dependency of the DHT library |
| Adafruit GFX Library | Adafruit | 1.13.0 | OLED drawing |
| Adafruit SSD1306 | Adafruit | 2.5.17 | OLED driver |
| Adafruit BusIO | Adafruit | 1.17.4 | Dependency of GFX/SSD1306 |

BH1750 and ArduinoJson aren't needed (the LDR is read with `analogRead`, and the JSON is built with `snprintf`). If they're
still installed from an earlier version of the project, they're harmless and can be removed in the Library Manager.

On the laptop side, the serial bridge needs **pyserial**. It's in `dashboard/requirements.txt`, so installing
the dashboard requirements covers it.

## Install in Arduino IDE 2.x

1. **Board package:** *File → Preferences → Additional boards manager URLs*, add
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`.
   Then *Tools → Board → Boards Manager*, search **esp32** (by Espressif Systems) and install it.
2. **Libraries:** *Sketch → Include Library → Manage Libraries…*. Search each name above and click *Install*.
   When asked "Install all dependencies?", choose **Install all**.

## Install with arduino-cli (optional)

```powershell
$cli = "$env:LOCALAPPDATA\Programs\Arduino IDE\resources\app\lib\backend\resources\arduino-cli.exe"
& $cli lib install "DHT sensor library" "Adafruit Unified Sensor" "Adafruit GFX Library" "Adafruit SSD1306"
& $cli compile --fqbn esp32:esp32:esp32 iot\firmware\smartbuddy_esp32\New_Code
```
