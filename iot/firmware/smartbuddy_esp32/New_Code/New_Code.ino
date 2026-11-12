// SmartBuddy ESP32 firmware v1.4.0 (board: ESP32 Dev Module, serial 115200)
// serial commands: t = table, h = report, c = csv, b = report + csv, ? = help

#include <Arduino.h>
#include <Wire.h>
#include <stdarg.h>
#include <esp_system.h>
#include <DHT.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <NetworkClientSecure.h>
#include <time.h>
#include <Preferences.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "secrets.h is missing: copy secrets.example.h to secrets.h in this folder and fill it in (see iot/README.md)."
#endif

// old secrets.h files have no BACKEND_HTTPS, they talk plain http to the laptop
#ifndef BACKEND_HTTPS
#define BACKEND_HTTPS 0
#endif
#define BACKEND_SCHEME (BACKEND_HTTPS ? "https" : "http")

#define LED_PIN 4
#define DHT_PIN 5    // strapping pin, needs the 10k pull-up
#define BUZZER_PIN 19

#define I2C_SDA 21
#define I2C_SCL 22

#define PIR_PIN 27
#define MQ2_PIN 34
#define LDR_PIN 35
#define FAN_PIN 25   // MOSFET gate, not the fan itself
#define RAIN_PIN 32
#define SERVO_PIN 33  // SG90 signal, the servo itself runs on the external 5V

#define DHT_TYPE DHT22

#define OLED_WIDTH         128
#define OLED_HEIGHT        64
#define OLED_RESET_PIN     -1
#define OLED_I2C_ADDRESS   0x3C

#define FIRMWARE_VERSION "1.5.0-wifi-https-rain"

enum SerialOutputMode : uint8_t {
  SERIAL_HUMAN_READABLE = 0,
  SERIAL_CSV            = 1,
  SERIAL_BOTH           = 2,
  SERIAL_DATA_TABLE     = 3
};
constexpr SerialOutputMode DEFAULT_SERIAL_MODE = SERIAL_DATA_TABLE;
constexpr uint32_t SERIAL_BAUD = 115200;
constexpr uint8_t  TABLE_HEADER_EVERY_ROWS = 20;

constexpr uint32_t I2C_CLOCK_HZ   = 100000;
constexpr uint16_t I2C_TIMEOUT_MS = 50;

constexpr uint8_t       OLED_CONTRAST         = 0x20;
constexpr unsigned long OLED_POSTINIT_WAIT_MS = 50;

constexpr bool          LED_SELFTEST_ENABLED = true;
constexpr uint8_t       LED_SELFTEST_BLINKS  = 3;
constexpr unsigned long LED_SELFTEST_MS      = 200;

constexpr bool    LDR_INVERT        = true;   // flip if light % goes up when covered
constexpr uint8_t LDR_FILTER_WINDOW = 8;

constexpr unsigned long DHT_INTERVAL_MS         = 2000;
constexpr unsigned long LDR_INTERVAL_MS         = 250;
constexpr unsigned long PIR_INTERVAL_MS         = 100;
constexpr unsigned long MQ2_INTERVAL_MS         = 250;
constexpr unsigned long OLED_REFRESH_MS         = 1000;
constexpr unsigned long OLED_PAGE_MS            = 4000;
constexpr unsigned long HUMAN_PRINT_INTERVAL_MS = 2000;
constexpr unsigned long CSV_INTERVAL_MS         = 2000;
constexpr unsigned long OLED_RETRY_MS           = 10000;

constexpr unsigned long NET_SEND_INTERVAL_MS = 2000;
constexpr uint16_t      NET_HTTP_TIMEOUT_MS  = BACKEND_HTTPS ? 8000 : 3000;
constexpr unsigned long NET_RETRY_MS         = 5000;
constexpr unsigned long NET_WIFI_REJOIN_MS   = 30000;
constexpr uint8_t       NET_QUEUE_LEN        = 60;

constexpr unsigned long PIR_WARMUP_MS = 60000;
constexpr unsigned long MQ2_WARMUP_MS = 120000;

constexpr float FAN_ON_TEMP_C  = 26.1f;   // above 26.0 C
constexpr float FAN_OFF_TEMP_C = 25.5f;

constexpr float LED_ON_PCT  = 30.0f;
constexpr float LED_OFF_PCT = 40.0f;

constexpr int           MQ2_ALARM_THRESHOLD  = 420;    // raw ADC, not ppm. clean-air baseline 112 on 2026-11-12
constexpr int           MQ2_ALARM_HYSTERESIS = 100;
constexpr unsigned long MQ2_ALARM_CONFIRM_MS = 3000;
constexpr unsigned long MQ2_ALARM_MIN_ON_MS  = 5000;
constexpr uint8_t       MQ2_FILTER_WINDOW    = 8;

constexpr bool          MQ2_LOW_SIGNAL_CHECK_ENABLED = true;
constexpr int           MQ2_LOW_SIGNAL_RAW           = 5;
constexpr unsigned long MQ2_LOW_SIGNAL_TIME_MS       = 30000;

constexpr unsigned long RAIN_INTERVAL_MS    = 250;
constexpr uint8_t       RAIN_FILTER_WINDOW  = 8;
constexpr bool          RAIN_WHEN_LOW       = true;    // most modules read lower when wet, check yours
constexpr int           RAIN_ON_ADC         = 2500;
constexpr int           RAIN_OFF_ADC        = 2800;
constexpr unsigned long RAIN_CONFIRM_MS     = 2000;
constexpr unsigned long DRY_CONFIRM_MS      = 2000;
constexpr int           RAIN_ERROR_LOW_ADC  = 5;       // stuck at 0 = AO shorted or module unpowered
constexpr int           RAIN_ERROR_HIGH_ADC = 4096;    // 4096 = check off, a dry module can sit at 4095
constexpr unsigned long RAIN_ERROR_MS       = 30000;

constexpr bool          WINDOW_AUTO_ENABLED  = true;
constexpr int           WINDOW_OPEN_ANGLE    = 0;
constexpr int           WINDOW_CLOSED_ANGLE  = 90;
constexpr unsigned long WINDOW_REOPEN_DRY_MS = 10000;
constexpr unsigned long SERVO_STEP_MS        = 15;      // 1 degree per step
constexpr int           SERVO_MIN_US         = 500;
constexpr int           SERVO_MAX_US         = 2400;

constexpr unsigned long BUZZER_ON_MS  = 500;
constexpr unsigned long BUZZER_OFF_MS = 500;

constexpr uint8_t FAN_ACTIVE_LEVEL    = HIGH;
constexpr uint8_t LED_ACTIVE_LEVEL    = HIGH;
constexpr uint8_t BUZZER_ACTIVE_LEVEL = LOW;   // buzzer module is active low

constexpr uint8_t DHT_MAX_CONSECUTIVE_FAILS = 3;
constexpr float   DHT_MIN_VALID_TEMP_C      = -40.0f;
constexpr float   DHT_MAX_VALID_TEMP_C      = 80.0f;
constexpr float   DHT_MIN_VALID_HUM         = 0.0f;
constexpr float   DHT_MAX_VALID_HUM         = 100.0f;

static_assert(FAN_ON_TEMP_C > FAN_OFF_TEMP_C, "Fan ON threshold must be above OFF threshold");
static_assert(LED_OFF_PCT > LED_ON_PCT, "LED OFF % must be above LED ON %");
static_assert(MQ2_ALARM_HYSTERESIS < MQ2_ALARM_THRESHOLD, "Hysteresis must be below threshold");
static_assert(MQ2_FILTER_WINDOW > 0 && LDR_FILTER_WINDOW > 0, "Filter windows must be > 0");
static_assert(RAIN_FILTER_WINDOW > 0, "Filter windows must be > 0");
static_assert(RAIN_WHEN_LOW ? RAIN_OFF_ADC > RAIN_ON_ADC : RAIN_OFF_ADC < RAIN_ON_ADC,
              "RAIN_OFF_ADC must be on the dry side of RAIN_ON_ADC");
static_assert(WINDOW_OPEN_ANGLE >= 0 && WINDOW_OPEN_ANGLE <= 180 &&
              WINDOW_CLOSED_ANGLE >= 0 && WINDOW_CLOSED_ANGLE <= 180, "Servo angles are 0-180");
static_assert(WINDOW_OPEN_ANGLE != WINDOW_CLOSED_ANGLE, "Open and closed angles must differ");

constexpr uint8_t OLED_PAGE_COUNT = 5;

enum SensorState : uint8_t {
  SENSOR_INITIALIZING = 0,
  SENSOR_WARMING_UP,
  SENSOR_READY,
  SENSOR_ERROR
};

enum Mq2Indication : uint8_t {
  MQ2_IND_WARMING = 0,
  MQ2_IND_NORMAL,
  MQ2_IND_ALERT,
  MQ2_IND_ERROR
};

struct DhtData {
  SensorState   state            = SENSOR_INITIALIZING;
  bool          currentValid     = false;
  float         temperatureC     = NAN;
  float         humidityPct      = NAN;
  bool          hasLastValid     = false;
  float         lastValidTempC   = NAN;
  float         lastValidHumPct  = NAN;
  unsigned long lastValidMs      = 0;
  uint16_t      consecutiveFails = 0;
  uint32_t      totalReads       = 0;
  uint32_t      totalFails       = 0;
  bool          newSinceCsv      = false;
};

struct LdrData {
  SensorState state      = SENSOR_INITIALIZING;
  bool        hasSample  = false;
  int         raw        = 0;
  int         buffer[LDR_FILTER_WINDOW] = {0};
  uint8_t     index      = 0;
  uint8_t     count      = 0;
  long        sum        = 0;
  int         filtered   = 0;
  bool        filterFull = false;
  float       percent    = NAN;
};

struct PirData {
  SensorState   state         = SENSOR_INITIALIZING;
  bool          initialized   = false;
  bool          motion        = false;
  bool          hasMotionEver = false;
  unsigned long lastMotionMs  = 0;
  unsigned long lastChangeMs  = 0;
  unsigned long warmupStartMs = 0;
  uint32_t      motionEvents  = 0;
};

struct Mq2Data {
  SensorState   state             = SENSOR_INITIALIZING;
  Mq2Indication indication        = MQ2_IND_WARMING;
  bool          hasSample         = false;
  int           raw               = 0;
  uint32_t      pinMilliVolts     = 0;
  int           buffer[MQ2_FILTER_WINDOW] = {0};
  uint8_t       index             = 0;
  uint8_t       count             = 0;
  long          sum               = 0;
  int           filtered          = 0;
  bool          filterFull        = false;
  unsigned long warmupStartMs     = 0;
  bool          warmupAnnounced   = false;
  bool          lowSignalActive   = false;
  unsigned long lowSignalSinceMs  = 0;
  uint32_t      sampleCount       = 0;
  bool          aboveActive       = false;
  unsigned long aboveSinceMs      = 0;
};

enum RainStatus : uint8_t {
  RAIN_INITIALIZING = 0,
  RAIN_DRY,
  RAIN_WET,
  RAIN_ERROR
};

enum WindowState : uint8_t {
  WINDOW_UNKNOWN = 0,
  WINDOW_OPEN,
  WINDOW_CLOSED,
  WINDOW_MOVING
};

struct RainData {
  RainStatus    status         = RAIN_INITIALIZING;
  bool          hasSample      = false;
  int           raw            = 0;
  int           buffer[RAIN_FILTER_WINDOW] = {0};
  uint8_t       index          = 0;
  uint8_t       count          = 0;
  long          sum            = 0;
  int           filtered       = 0;
  bool          filterFull     = false;
  RainStatus    pending        = RAIN_INITIALIZING;
  unsigned long pendingSinceMs = 0;
  bool          onRail         = false;
  unsigned long railSinceMs    = 0;
  unsigned long changedMs      = 0;
};

struct WindowData {
  bool          attached   = false;
  int           angle      = -1;
  int           target     = -1;
  unsigned long lastStepMs = 0;
  char          reason[48] = "Startup";
};

DhtData dhtData;
LdrData ldrData;
PirData pirData;
Mq2Data mq2Data;
RainData rainData;
WindowData win;
Preferences prefs;

enum NetSensorStatus : uint8_t { NET_OK = 0, NET_ERROR, NET_WARMING_UP };

struct NetReading {
  uint32_t sequence;
  uint32_t uptimeMs;
  float    temperatureC;
  float    humidityPct;
  float    lightPct;
  int16_t  ldrRaw;
  bool     motion;
  int16_t  gasAdc;
  bool     gasWarning;
  bool     fanOn;
  bool     ledOn;
  uint8_t  dht, ldr, pir, mq2;
  bool     rainHasRaw;
  bool     rainHasFiltered;
  int16_t  rainRaw;
  int16_t  rainFiltered;
  uint8_t  rainStatus;
  uint8_t  windowState;
  int16_t  servoAngle;
};

struct NetLogLine {
  char text[96];
};

struct NetStatus {
  volatile bool     started       = false;
  volatile bool     wifiConnected = false;
  volatile bool     backendOk     = false;
  volatile bool     clockSynced   = false;
  volatile int8_t   rssi          = 0;
  uint32_t          sent          = 0;
  uint32_t          rejected      = 0;
  uint32_t          dropped       = 0;
  volatile int      lastHttpCode  = 0;
};
NetStatus     net;
QueueHandle_t netQueue    = nullptr;
QueueHandle_t netLogQueue = nullptr;
uint32_t      netSequence = 0;

struct ActuatorData {
  bool          fanOn          = false;
  bool          ledOn          = false;
  bool          alarmActive    = false;
  bool          buzzerOutputOn = false;
  unsigned long alarmStartMs   = 0;
  char          fanReason[64]  = "Startup default: OFF";
  char          ledReason[64]  = "Startup default: OFF";
};
ActuatorData act;

struct OledData {
  bool          ok             = false;
  uint8_t       page           = 0;
  unsigned long lastPageMs     = 0;
  unsigned long lastRetryMs    = 0;
  unsigned long initMs         = 0;
  uint32_t      dropCount      = 0;
  bool          failReported   = false;
};
OledData oled;

DHT              dht(DHT_PIN, DHT_TYPE);
Adafruit_SSD1306 display(OLED_WIDTH, OLED_HEIGHT, &Wire, OLED_RESET_PIN);

uint8_t i2cSda = I2C_SDA;
uint8_t i2cScl = I2C_SCL;

SerialOutputMode serialMode = DEFAULT_SERIAL_MODE;
unsigned long bootMs               = 0;
unsigned long tPir                 = 0;
unsigned long tMq2                 = 0;
unsigned long tDht                 = 0;
unsigned long tLdr                 = 0;
unsigned long tOled                = 0;
unsigned long tHuman               = 0;
unsigned long tCsv                 = 0;
unsigned long tNet                 = 0;
unsigned long tRain                = 0;
uint32_t      csvRowsTotal         = 0;
uint32_t      csvRowsValid         = 0;
uint16_t      tableRowsSinceHeader = 0;

void initializeSensors();
void initializeDisplay();
void initializeActuators();
void ledSelfTest();
bool i2cProbe(uint8_t addr);
bool startI2C(uint8_t sda, uint8_t scl);
void setupI2CBus();
void readDHT22();
void readLDR();
void readPIR();
void readMQ2();
void updateMq2Filter();
void updateMq2State();
void handleFanAutomation();
void handleLEDAutomation();
void handleMQ2Alarm();
void updateBuzzer();
void updateOLED();
void drawHeader(const char* title);
void drawRow(int16_t y, const char* label, const char* value, bool highlight);
void printRight(int16_t y, const char* text, uint8_t size);
void drawDegreeC(int16_t x, int16_t y);
void drawPageAlarm();
const char* shortState(SensorState s);
void drawPageEnvironment();
void drawPageSensors();
void drawPageActuators();
void drawPageSystem();
void printHumanReadableData();
void printDataTable();
void printCSVHeader();
void printCSVData();
void printStartupInformation();
void printResetReason();
void printHelp();
void handleSerialCommands();
void setSerialMode(SerialOutputMode m);
void setFan(bool on);
void setLed(bool on);
void setBuzzerOutput(bool on);
void initializeNetwork();
void queueReading();
void printNetLog();
void netShortStatus(char* buf, size_t len);
void initializeWindow();
void readRain();
void setRainStatus(RainStatus s);
void handleWindowAutomation();
void moveWindow(int angle);
bool servoAttach(int angle);
void servoWrite(int angle);
void updateServo();
WindowState windowState();
const char* rainStatusName(RainStatus s);
const char* windowStateName(WindowState w);
void drawPageWindow();
bool isDue(unsigned long &lastMs, unsigned long intervalMs);
void diag(const char* level, const char* fmt, ...);
const char* stateName(SensorState s);
const char* mq2IndicationName(Mq2Indication i);
const char* modeName(SerialOutputMode m);
const char* onOff(bool b);
const char* automationStatus();
const char* sensorStatusText(SensorState s, unsigned long warmLeftMs, char* buf, size_t len);
uint8_t levelFor(bool on, uint8_t activeLevel);
void formatUptime(unsigned long ms, char* buf, size_t len);
unsigned long remainingMs(unsigned long startMs, unsigned long durationMs);
bool dhtUsable();
bool lightUsable();
bool pirUsable();

bool isDue(unsigned long &lastMs, unsigned long intervalMs) {
  unsigned long now = millis();
  if (now - lastMs >= intervalMs) {
    lastMs += intervalMs;
    if (now - lastMs >= intervalMs) lastMs = now;
    return true;
  }
  return false;
}

void diag(const char* level, const char* fmt, ...) {
  if (serialMode == SERIAL_CSV) return;
  char msg[256];
  va_list args;
  va_start(args, fmt);
  vsnprintf(msg, sizeof(msg), fmt, args);
  va_end(args);
  Serial.printf("[%10lu ms] [%s] %s\n", (unsigned long)millis(), level, msg);
}

const char* stateName(SensorState s) {
  switch (s) {
    case SENSOR_INITIALIZING: return "INITIALIZING";
    case SENSOR_WARMING_UP:   return "WARMING_UP";
    case SENSOR_READY:        return "READY";
    case SENSOR_ERROR:        return "ERROR";
  }
  return "UNKNOWN";
}

const char* mq2IndicationName(Mq2Indication i) {
  switch (i) {
    case MQ2_IND_WARMING: return "WARMING";
    case MQ2_IND_NORMAL:  return "NORMAL";
    case MQ2_IND_ALERT:   return "ALERT";
    case MQ2_IND_ERROR:   return "ERROR";
  }
  return "UNKNOWN";
}

const char* modeName(SerialOutputMode m) {
  switch (m) {
    case SERIAL_HUMAN_READABLE: return "SERIAL_HUMAN_READABLE";
    case SERIAL_CSV:            return "SERIAL_CSV";
    case SERIAL_BOTH:           return "SERIAL_BOTH";
    case SERIAL_DATA_TABLE:     return "SERIAL_DATA_TABLE";
  }
  return "UNKNOWN";
}

const char* onOff(bool b) { return b ? "ON" : "OFF"; }

const char* sensorStatusText(SensorState s, unsigned long warmLeftMs, char* buf, size_t len) {
  switch (s) {
    case SENSOR_READY: return "OK";
    case SENSOR_ERROR: return "ERROR";
    case SENSOR_WARMING_UP:
      if (warmLeftMs > 0) {
        snprintf(buf, len, "WARMING (%lus left)", warmLeftMs / 1000UL + 1);
        return buf;
      }
      return "WARMING";
    default: return "STARTING";
  }
}

uint8_t levelFor(bool on, uint8_t activeLevel) {
  if (on) return activeLevel;
  return (activeLevel == HIGH) ? LOW : HIGH;
}

void formatUptime(unsigned long ms, char* buf, size_t len) {
  unsigned long s = ms / 1000UL;
  unsigned long d = s / 86400UL; s %= 86400UL;
  unsigned long h = s / 3600UL;  s %= 3600UL;
  unsigned long m = s / 60UL;    s %= 60UL;
  if (d > 0) snprintf(buf, len, "%lud %02lu:%02lu:%02lu", d, h, m, s);
  else       snprintf(buf, len, "%02lu:%02lu:%02lu", h, m, s);
}

unsigned long remainingMs(unsigned long startMs, unsigned long durationMs) {
  unsigned long elapsed = millis() - startMs;
  return (elapsed >= durationMs) ? 0UL : (durationMs - elapsed);
}

bool dhtUsable()   { return dhtData.state == SENSOR_READY && dhtData.currentValid; }
bool lightUsable() { return ldrData.state == SENSOR_READY && !isnan(ldrData.percent); }
bool pirUsable()   { return pirData.state == SENSOR_READY && pirData.initialized; }

bool i2cProbe(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void initializeActuators() {
  pinMode(FAN_PIN, OUTPUT);
  digitalWrite(FAN_PIN, levelFor(false, FAN_ACTIVE_LEVEL));
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, levelFor(false, LED_ACTIVE_LEVEL));
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, levelFor(false, BUZZER_ACTIVE_LEVEL));
  act.fanOn = false;
  act.ledOn = false;
  act.alarmActive = false;
  act.buzzerOutputOn = false;
}

void ledSelfTest() {
  if (!LED_SELFTEST_ENABLED) return;
  diag("INFO", "LED self-test on GPIO%d: %u blinks now.", LED_PIN, (unsigned)LED_SELFTEST_BLINKS);
  for (uint8_t i = 0; i < LED_SELFTEST_BLINKS; i++) {
    digitalWrite(LED_PIN, levelFor(true, LED_ACTIVE_LEVEL));
    delay(LED_SELFTEST_MS);
    digitalWrite(LED_PIN, levelFor(false, LED_ACTIVE_LEVEL));
    delay(LED_SELFTEST_MS);
  }
  diag("INFO", "If the LED did NOT blink: check LED polarity, 220-330 ohm resistor, GND, "
               "GPIO%d, or set LED_ACTIVE_LEVEL to LOW for an active-low module.", LED_PIN);
}

bool startI2C(uint8_t sda, uint8_t scl) {
  Wire.begin(sda, scl);
  Wire.setClock(I2C_CLOCK_HZ);
  Wire.setTimeOut(I2C_TIMEOUT_MS);
  return i2cProbe(OLED_I2C_ADDRESS);
}

void setupI2CBus() {
  if (startI2C(I2C_SDA, I2C_SCL)) {
    i2cSda = I2C_SDA; i2cScl = I2C_SCL;
  } else {
    Wire.end();
    if (startI2C(I2C_SCL, I2C_SDA)) {
      i2cSda = I2C_SCL; i2cScl = I2C_SDA;
      diag("WARN", "OLED found with SDA/SCL swapped. Using SDA=GPIO%d, SCL=GPIO%d.", i2cSda, i2cScl);
    } else {
      Wire.end();
      startI2C(I2C_SDA, I2C_SCL);
      i2cSda = I2C_SDA; i2cScl = I2C_SCL;
      diag("WARN", "No OLED found at 0x%02X on GPIO21/22 (either order). Running without display.",
           OLED_I2C_ADDRESS);
    }
  }
  diag("INFO", "I2C bus: SDA=GPIO%d, SCL=GPIO%d, %lu Hz.", i2cSda, i2cScl, (unsigned long)I2C_CLOCK_HZ);
}

void initializeSensors() {
  setupI2CBus();

  analogReadResolution(12);

  dht.begin();
  dhtData.state = SENSOR_INITIALIZING;
  diag("INFO", "DHT22 started on GPIO%d. First reading in %lu ms.", DHT_PIN, DHT_INTERVAL_MS);

  analogSetPinAttenuation(LDR_PIN, ADC_11db);
  ldrData.state = SENSOR_INITIALIZING;
  diag("INFO", "LDR on GPIO%d (%s). LED ON <= %.0f %%, OFF >= %.0f %%.",
       LDR_PIN, LDR_INVERT ? "inverted: module AO" : "normal: divider",
       LED_ON_PCT, LED_OFF_PCT);

  pinMode(PIR_PIN, INPUT_PULLDOWN);
  pirData.state = SENSOR_WARMING_UP;
  pirData.warmupStartMs = millis();
  diag("INFO", "PIR on GPIO%d. Warm-up: %lu s.", PIR_PIN, PIR_WARMUP_MS / 1000UL);

  analogSetPinAttenuation(MQ2_PIN, ADC_11db);
  mq2Data.state = SENSOR_WARMING_UP;
  mq2Data.indication = MQ2_IND_WARMING;
  mq2Data.warmupStartMs = millis();
  diag("INFO", "MQ-2 on GPIO%d. Warm-up: %lu s. Threshold: %d raw ADC (not ppm).",
       MQ2_PIN, MQ2_WARMUP_MS / 1000UL, MQ2_ALARM_THRESHOLD);
}

void initializeDisplay() {
  unsigned long now = millis();
  oled.lastRetryMs = now;

  if (!i2cProbe(OLED_I2C_ADDRESS)) {
    oled.ok = false;
    if (!oled.failReported) {
      diag("ERROR", "OLED not answering at 0x%02X. Firmware continues without display; retrying every %lu s.",
           OLED_I2C_ADDRESS, OLED_RETRY_MS / 1000UL);
      oled.failReported = true;
    }
    return;
  }

  display.begin(SSD1306_SWITCHCAPVCC, OLED_I2C_ADDRESS, true, false);
  display.ssd1306_command(SSD1306_SETCONTRAST);
  display.ssd1306_command(OLED_CONTRAST);

  display.cp437(true);
  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(4, 0);
  display.print("SmartBuddy");
  display.setTextSize(1);
  display.setCursor(4, 28);
  display.print("Starting sensors...");
  display.setCursor(4, 44);
  display.print("Please wait");
  display.display();

  delay(OLED_POSTINIT_WAIT_MS);
  if (!i2cProbe(OLED_I2C_ADDRESS)) {
    oled.ok = false;
    oled.dropCount++;
    diag("ERROR", "OLED stopped responding after its first frame (drop #%lu). Check OLED VCC/GND.",
         (unsigned long)oled.dropCount);
    oled.failReported = true;
    return;
  }

  oled.ok = true;
  oled.failReported = false;
  oled.page = 0;
  oled.lastPageMs = now;
  oled.initMs = millis();
  diag("INFO", "SSD1306 OLED initialized at 0x%02X.", OLED_I2C_ADDRESS);
}

void readDHT22() {
  unsigned long now = millis();
  float t = dht.readTemperature(false, true);
  float h = dht.readHumidity(false);
  dhtData.totalReads++;

  bool nanErr = isnan(t) || isnan(h);
  bool ok = !nanErr &&
            t >= DHT_MIN_VALID_TEMP_C && t <= DHT_MAX_VALID_TEMP_C &&
            h >= DHT_MIN_VALID_HUM && h <= DHT_MAX_VALID_HUM;

  if (ok) {
    dhtData.temperatureC     = t;
    dhtData.humidityPct      = h;
    dhtData.currentValid     = true;
    dhtData.hasLastValid     = true;
    dhtData.lastValidTempC   = t;
    dhtData.lastValidHumPct  = h;
    dhtData.lastValidMs      = now;
    dhtData.consecutiveFails = 0;
    dhtData.newSinceCsv      = true;
    if (dhtData.state != SENSOR_READY) {
      dhtData.state = SENSOR_READY;
      diag("INFO", "DHT22 READY (%.1f C, %.1f %%).", t, h);
    }
  } else {
    dhtData.totalFails++;
    dhtData.consecutiveFails++;
    dhtData.currentValid = false;
    dhtData.temperatureC = NAN;
    dhtData.humidityPct  = NAN;
    if (dhtData.state != SENSOR_ERROR) {
      if (nanErr) diag("WARN", "DHT22 read failed (NaN). Consecutive failures: %u", (unsigned)dhtData.consecutiveFails);
      else        diag("WARN", "DHT22 out-of-range reading rejected (T=%.1f, H=%.1f).", t, h);
      if (dhtData.consecutiveFails >= DHT_MAX_CONSECUTIVE_FAILS) {
        dhtData.state = SENSOR_ERROR;
        diag("ERROR", "DHT22 marked ERROR after %u failures. Check GPIO5 wiring, 10k pull-up, power.",
             (unsigned)dhtData.consecutiveFails);
      }
    }
  }
}

void readLDR() {
  int raw = analogRead(LDR_PIN);
  ldrData.raw = raw;
  ldrData.hasSample = true;

  if (ldrData.count == LDR_FILTER_WINDOW) {
    ldrData.sum -= ldrData.buffer[ldrData.index];
  } else {
    ldrData.count++;
  }
  ldrData.buffer[ldrData.index] = raw;
  ldrData.sum += raw;
  ldrData.index = (uint8_t)((ldrData.index + 1) % LDR_FILTER_WINDOW);
  ldrData.filtered = (int)(ldrData.sum / ldrData.count);
  ldrData.filterFull = (ldrData.count == LDR_FILTER_WINDOW);

  float pct = ldrData.filtered * 100.0f / 4095.0f;
  if (LDR_INVERT) pct = 100.0f - pct;
  ldrData.percent = pct;

  if (ldrData.filterFull && ldrData.state != SENSOR_READY) {
    ldrData.state = SENSOR_READY;
    diag("INFO", "LDR READY (light %.1f %%, raw avg %d).", pct, ldrData.filtered);
  }
}

void readPIR() {
  unsigned long now = millis();
  bool motion = (digitalRead(PIR_PIN) == HIGH);

  if (pirData.state == SENSOR_WARMING_UP && (now - pirData.warmupStartMs >= PIR_WARMUP_MS)) {
    pirData.state = SENSOR_READY;
    diag("INFO", "PIR warm-up complete. PIR READY.");
  }

  if (motion) {
    pirData.lastMotionMs = now;
    pirData.hasMotionEver = true;
  }

  if (!pirData.initialized || motion != pirData.motion) {
    if (pirData.initialized) {
      const char* note = (pirData.state == SENSOR_WARMING_UP) ? " (PIR still warming up)" : "";
      if (motion) {
        pirData.motionEvents++;
        diag("EVENT", "Motion DETECTED%s", note);
      } else {
        diag("EVENT", "Motion ended (PIR output LOW)%s", note);
      }
    }
    pirData.motion = motion;
    pirData.lastChangeMs = now;
    pirData.initialized = true;
  }
}

void readMQ2() {
  mq2Data.raw = analogRead(MQ2_PIN);
  mq2Data.pinMilliVolts = analogReadMilliVolts(MQ2_PIN);
  mq2Data.hasSample = true;
  mq2Data.sampleCount++;
  updateMq2Filter();
  updateMq2State();
}

void updateMq2Filter() {
  if (!mq2Data.hasSample) return;
  if (mq2Data.count == MQ2_FILTER_WINDOW) {
    mq2Data.sum -= mq2Data.buffer[mq2Data.index];
  } else {
    mq2Data.count++;
  }
  mq2Data.buffer[mq2Data.index] = mq2Data.raw;
  mq2Data.sum += mq2Data.raw;
  mq2Data.index = (uint8_t)((mq2Data.index + 1) % MQ2_FILTER_WINDOW);
  mq2Data.filtered = (int)(mq2Data.sum / mq2Data.count);
  mq2Data.filterFull = (mq2Data.count == MQ2_FILTER_WINDOW);
}

void updateMq2State() {
  unsigned long now = millis();
  bool warmDone = (now - mq2Data.warmupStartMs >= MQ2_WARMUP_MS);

  if (!warmDone) {
    mq2Data.state = SENSOR_WARMING_UP;
    return;
  }

  if (!mq2Data.warmupAnnounced) {
    mq2Data.warmupAnnounced = true;
    diag("INFO", "MQ-2 warm-up timer finished (%lu s). Readings are UNCALIBRATED relative ADC values, not ppm.",
         MQ2_WARMUP_MS / 1000UL);
  }

  bool lowNow = MQ2_LOW_SIGNAL_CHECK_ENABLED && mq2Data.filterFull &&
                mq2Data.filtered <= MQ2_LOW_SIGNAL_RAW;
  if (lowNow) {
    if (!mq2Data.lowSignalActive) {
      mq2Data.lowSignalActive = true;
      mq2Data.lowSignalSinceMs = now;
    }
  } else {
    mq2Data.lowSignalActive = false;
  }
  bool lowFault = mq2Data.lowSignalActive && (now - mq2Data.lowSignalSinceMs >= MQ2_LOW_SIGNAL_TIME_MS);

  SensorState newState;
  if (lowFault)                newState = SENSOR_ERROR;
  else if (mq2Data.filterFull) newState = SENSOR_READY;
  else                         newState = SENSOR_WARMING_UP;

  if (newState != mq2Data.state) {
    if (newState == SENSOR_ERROR) {
      diag("ERROR", "MQ-2 signal stuck near 0 for %lu s. Check AO wiring, 5V heater supply, divider, common GND.",
           MQ2_LOW_SIGNAL_TIME_MS / 1000UL);
    } else if (newState == SENSOR_READY) {
      diag("INFO", "MQ-2 READY (filtered ADC %d).", mq2Data.filtered);
    }
    mq2Data.state = newState;
  }
}

void setFan(bool on) {
  if (on == act.fanOn) return;
  act.fanOn = on;
  digitalWrite(FAN_PIN, levelFor(on, FAN_ACTIVE_LEVEL));
  diag("RULE", "Fan switched %s (%s)", onOff(on), act.fanReason);
}

void setLed(bool on) {
  if (on == act.ledOn) return;
  act.ledOn = on;
  digitalWrite(LED_PIN, levelFor(on, LED_ACTIVE_LEVEL));
  diag("RULE", "LED switched %s on GPIO%d (pin %s) (%s)", onOff(on), LED_PIN,
       levelFor(on, LED_ACTIVE_LEVEL) == HIGH ? "HIGH" : "LOW", act.ledReason);
}

void setBuzzerOutput(bool on) {
  act.buzzerOutputOn = on;
  digitalWrite(BUZZER_PIN, levelFor(on, BUZZER_ACTIVE_LEVEL));
}

void handleFanAutomation() {
  if (!dhtUsable()) {
    snprintf(act.fanReason, sizeof(act.fanReason), "HOLD %s: DHT22 reading unavailable", onOff(act.fanOn));
    return;
  }
  float t = dhtData.temperatureC;
  if (t >= FAN_ON_TEMP_C) {
    snprintf(act.fanReason, sizeof(act.fanReason), "ON: %.1f C >= %.1f C", t, FAN_ON_TEMP_C);
    setFan(true);
  } else if (t <= FAN_OFF_TEMP_C) {
    snprintf(act.fanReason, sizeof(act.fanReason), "OFF: %.1f C <= %.1f C", t, FAN_OFF_TEMP_C);
    setFan(false);
  } else {
    snprintf(act.fanReason, sizeof(act.fanReason), "HOLD %s: %.1f C in %.1f-%.1f C band",
             onOff(act.fanOn), t, FAN_OFF_TEMP_C, FAN_ON_TEMP_C);
  }
}

void handleLEDAutomation() {
  if (!lightUsable()) {
    snprintf(act.ledReason, sizeof(act.ledReason), "HOLD %s: LDR not ready", onOff(act.ledOn));
    return;
  }
  float pct = ldrData.percent;
  if (pct <= LED_ON_PCT) {
    snprintf(act.ledReason, sizeof(act.ledReason), "ON: light %.1f %% <= %.0f %%", pct, LED_ON_PCT);
    setLed(true);
  } else if (pct >= LED_OFF_PCT) {
    snprintf(act.ledReason, sizeof(act.ledReason), "OFF: light %.1f %% >= %.0f %%", pct, LED_OFF_PCT);
    setLed(false);
  } else {
    snprintf(act.ledReason, sizeof(act.ledReason), "HOLD %s: light %.1f %% in %.0f-%.0f %% band",
             onOff(act.ledOn), pct, LED_ON_PCT, LED_OFF_PCT);
  }
}

void handleMQ2Alarm() {
  unsigned long now = millis();
  bool above = (mq2Data.state == SENSOR_READY) && mq2Data.filterFull &&
               (mq2Data.filtered > MQ2_ALARM_THRESHOLD);

  if (!act.alarmActive) {
    if (above) {
      if (!mq2Data.aboveActive) {
        mq2Data.aboveActive = true;
        mq2Data.aboveSinceMs = now;
        diag("WARN", "MQ-2 above threshold (%d > %d). Confirming for %lu ms before alarm...",
             mq2Data.filtered, MQ2_ALARM_THRESHOLD, MQ2_ALARM_CONFIRM_MS);
      }
      if (now - mq2Data.aboveSinceMs >= MQ2_ALARM_CONFIRM_MS) {
        act.alarmActive = true;
        act.alarmStartMs = now;
        diag("ALERT", "MQ-2 THRESHOLD ALERT: filtered ADC %d > %d for %lu ms. "
                      "Relative sensor alert, NOT confirmed gas leakage. Check the area manually.",
             mq2Data.filtered, MQ2_ALARM_THRESHOLD, MQ2_ALARM_CONFIRM_MS);
      }
    } else {
      if (mq2Data.aboveActive) diag("INFO", "MQ-2 dropped below threshold before confirmation. No alarm.");
      mq2Data.aboveActive = false;
    }
  } else {
    int clearLevel = MQ2_ALARM_THRESHOLD - MQ2_ALARM_HYSTERESIS;
    bool belowClear = mq2Data.filterFull && mq2Data.filtered < clearLevel;
    bool minOnDone  = (now - act.alarmStartMs >= MQ2_ALARM_MIN_ON_MS);
    if (belowClear && minOnDone) {
      act.alarmActive = false;
      mq2Data.aboveActive = false;
      diag("INFO", "MQ-2 threshold alert cleared: filtered ADC %d < %d.", mq2Data.filtered, clearLevel);
    }
  }

  if (act.alarmActive)                    mq2Data.indication = MQ2_IND_ALERT;
  else if (mq2Data.state == SENSOR_ERROR) mq2Data.indication = MQ2_IND_ERROR;
  else if (mq2Data.state == SENSOR_READY) mq2Data.indication = MQ2_IND_NORMAL;
  else                                    mq2Data.indication = MQ2_IND_WARMING;
}

void updateBuzzer() {
  if (!act.alarmActive) {
    if (act.buzzerOutputOn) setBuzzerOutput(false);
    return;
  }
  unsigned long period = BUZZER_ON_MS + BUZZER_OFF_MS;
  unsigned long phase  = (millis() - act.alarmStartMs) % period;
  bool shouldBeOn = (phase < BUZZER_ON_MS);
  if (shouldBeOn != act.buzzerOutputOn) setBuzzerOutput(shouldBeOn);
}

const char* automationStatus() {
  if (act.alarmActive) return "MQ2 ALERT ACTIVE";
  bool fanHold = !dhtUsable();
  bool ledHold = !lightUsable();
  if (fanHold && ledHold) return "HOLD: DHT+LDR N/A";
  if (fanHold)            return "PARTIAL: DHT N/A";
  if (ledHold)            return "PARTIAL: LDR N/A";
  if (mq2Data.state == SENSOR_ERROR) return "AUTO (MQ2 ERROR)";
  if (mq2Data.state != SENSOR_READY) return "AUTO (MQ2 WARMING)";
  return "AUTO OK";
}

const char* rainStatusName(RainStatus s) {
  switch (s) {
    case RAIN_INITIALIZING: return "INITIALIZING";
    case RAIN_DRY:          return "DRY";
    case RAIN_WET:          return "RAIN";
    case RAIN_ERROR:        return "ERROR";
  }
  return "UNKNOWN";
}

const char* windowStateName(WindowState w) {
  switch (w) {
    case WINDOW_OPEN:    return "OPEN";
    case WINDOW_CLOSED:  return "CLOSED";
    case WINDOW_MOVING:  return "MOVING";
    case WINDOW_UNKNOWN: return "UNKNOWN";
  }
  return "UNKNOWN";
}

void initializeWindow() {
  analogSetPinAttenuation(RAIN_PIN, ADC_11db);
  diag("INFO", "Rain sensor on GPIO%d: rain when avg %s %d, dry when %s %d.", RAIN_PIN,
       RAIN_WHEN_LOW ? "<=" : ">=", RAIN_ON_ADC, RAIN_WHEN_LOW ? ">=" : "<=", RAIN_OFF_ADC);

  prefs.begin("smartbuddy", false);
  int saved = prefs.getInt("win_angle", -1);
  bool known = saved == WINDOW_OPEN_ANGLE || saved == WINDOW_CLOSED_ANGLE;
  int start = known ? saved : WINDOW_CLOSED_ANGLE;
  win.target = start;
  if (servoAttach(start)) {
    diag("INFO", "Window servo on GPIO%d at %d deg (%s).", SERVO_PIN, start,
         known ? "last saved position" : "no saved position, starting closed");
  }
  if (!known) prefs.putInt("win_angle", start);
}

bool servoAttach(int angle) {
  if (!ledcAttach(SERVO_PIN, 50, 14)) {
    diag("ERROR", "Servo PWM on GPIO%d could not start. Window stays where it is.", SERVO_PIN);
    return false;
  }
  win.attached = true;
  servoWrite(angle);
  return true;
}

void servoWrite(int angle) {
  uint32_t us = SERVO_MIN_US + (uint32_t)(SERVO_MAX_US - SERVO_MIN_US) * (uint32_t)angle / 180UL;
  ledcWrite(SERVO_PIN, us * (1UL << 14) / 20000UL);   // 14-bit duty, 20 ms period
  win.angle = angle;
}

WindowState windowState() {
  if (!win.attached || win.angle < 0) return WINDOW_UNKNOWN;
  if (win.angle != win.target)        return WINDOW_MOVING;
  if (win.angle == WINDOW_CLOSED_ANGLE) return WINDOW_CLOSED;
  if (win.angle == WINDOW_OPEN_ANGLE)   return WINDOW_OPEN;
  return WINDOW_UNKNOWN;
}

void setRainStatus(RainStatus s) {
  rainData.status = s;
  rainData.pending = s;
  rainData.changedMs = millis();
  if (s == RAIN_WET)      diag("RAIN", "Rain detected (sensor avg %d).", rainData.filtered);
  else if (s == RAIN_DRY) diag("RAIN", "Dry (sensor avg %d).", rainData.filtered);
}

void readRain() {
  unsigned long now = millis();
  int raw = analogRead(RAIN_PIN);
  rainData.raw = raw;
  rainData.hasSample = true;

  if (rainData.count == RAIN_FILTER_WINDOW) {
    rainData.sum -= rainData.buffer[rainData.index];
  } else {
    rainData.count++;
  }
  rainData.buffer[rainData.index] = raw;
  rainData.sum += raw;
  rainData.index = (uint8_t)((rainData.index + 1) % RAIN_FILTER_WINDOW);
  rainData.filtered = (int)(rainData.sum / rainData.count);
  rainData.filterFull = (rainData.count == RAIN_FILTER_WINDOW);
  if (!rainData.filterFull) return;

  int f = rainData.filtered;
  if (f <= RAIN_ERROR_LOW_ADC || f >= RAIN_ERROR_HIGH_ADC) {
    if (!rainData.onRail) {
      rainData.onRail = true;
      rainData.railSinceMs = now;
    }
    if (rainData.status != RAIN_ERROR && now - rainData.railSinceMs >= RAIN_ERROR_MS) {
      setRainStatus(RAIN_ERROR);
      diag("ERROR", "Rain sensor stuck at %d for %lu s. Check AO on GPIO%d, 3.3V and GND. Window holds.",
           f, RAIN_ERROR_MS / 1000UL, RAIN_PIN);
    }
    if (rainData.status == RAIN_ERROR) return;
  } else {
    rainData.onRail = false;
    if (rainData.status == RAIN_ERROR) {
      setRainStatus(RAIN_INITIALIZING);
      diag("INFO", "Rain sensor reading normal again (avg %d).", f);
    }
  }

  bool wet = RAIN_WHEN_LOW ? f <= RAIN_ON_ADC : f >= RAIN_ON_ADC;
  bool dry = RAIN_WHEN_LOW ? f >= RAIN_OFF_ADC : f <= RAIN_OFF_ADC;
  RainStatus want = rainData.status;
  if (wet) {
    want = RAIN_WET;
  } else if (dry) {
    want = RAIN_DRY;
  } else if (rainData.status == RAIN_INITIALIZING) {
    int mid = (RAIN_ON_ADC + RAIN_OFF_ADC) / 2;
    want = (RAIN_WHEN_LOW ? f < mid : f > mid) ? RAIN_WET : RAIN_DRY;
  }

  if (want == rainData.status) {
    rainData.pending = want;
    return;
  }
  if (want != rainData.pending) {
    rainData.pending = want;
    rainData.pendingSinceMs = now;
  }
  unsigned long need = (want == RAIN_WET) ? RAIN_CONFIRM_MS : DRY_CONFIRM_MS;
  if (now - rainData.pendingSinceMs >= need) setRainStatus(want);
}

void moveWindow(int angle) {
  win.target = angle;
  if (!win.attached && !servoAttach(angle)) return;
  diag("WINDOW", "%s window (%s).", angle == WINDOW_CLOSED_ANGLE ? "Closing" : "Opening", win.reason);
}

void handleWindowAutomation() {
  if (!WINDOW_AUTO_ENABLED) return;
  unsigned long now = millis();
  if (rainData.status == RAIN_WET) {
    if (win.target != WINDOW_CLOSED_ANGLE) {
      snprintf(win.reason, sizeof(win.reason), "rain detected");
      moveWindow(WINDOW_CLOSED_ANGLE);
    }
  } else if (rainData.status == RAIN_DRY) {
    if (win.target != WINDOW_OPEN_ANGLE && now - rainData.changedMs >= WINDOW_REOPEN_DRY_MS) {
      snprintf(win.reason, sizeof(win.reason), "dry for %lu s", WINDOW_REOPEN_DRY_MS / 1000UL);
      moveWindow(WINDOW_OPEN_ANGLE);
    }
  }
}

void updateServo() {
  if (!win.attached || win.target < 0 || win.angle == win.target) return;
  unsigned long now = millis();
  if (now - win.lastStepMs < SERVO_STEP_MS) return;
  win.lastStepMs = now;
  servoWrite(win.angle + (win.target > win.angle ? 1 : -1));
  if (win.angle == win.target) {
    prefs.putInt("win_angle", win.angle);
    diag("WINDOW", "Window %s (servo at %d deg).", win.angle == WINDOW_CLOSED_ANGLE ? "closed" : "open", win.angle);
  }
}

constexpr int16_t OLED_BODY_Y = 19;
bool oledInverted = false;

const char* shortState(SensorState s) {
  switch (s) {
    case SENSOR_READY:      return "OK";
    case SENSOR_WARMING_UP: return "WARM";
    case SENSOR_ERROR:      return "ERROR";
    default:                return "START";
  }
}

void printRight(int16_t y, const char* text, uint8_t size) {
  int16_t w = (int16_t)(strlen(text) * 6 * size);
  display.setTextSize(size);
  display.setCursor(OLED_WIDTH - w, y);
  display.print(text);
}

void drawRow(int16_t y, const char* label, const char* value, bool highlight) {
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, y);
  display.print(label);
  int16_t w = (int16_t)(strlen(value) * 6);
  if (highlight) {
    display.fillRoundRect(OLED_WIDTH - w - 6, y - 2, w + 6, 11, 2, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
    display.setCursor(OLED_WIDTH - w - 3, y);
    display.print(value);
    display.setTextColor(SSD1306_WHITE);
  } else {
    display.setCursor(OLED_WIDTH - w, y);
    display.print(value);
  }
}

void drawDegreeC(int16_t x, int16_t y) {
  display.drawCircle(x + 2, y + 2, 2, SSD1306_WHITE);
  display.setTextSize(2);
  display.setCursor(x + 6, y);
  display.print("C");
}

void drawHeader(const char* title) {
  display.setTextSize(1);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 4);
  display.print(title);
  for (uint8_t i = 0; i < OLED_PAGE_COUNT; i++) {
    int16_t cx = OLED_WIDTH - 4 - (OLED_PAGE_COUNT - 1 - i) * 9;
    if (i == oled.page) display.fillCircle(cx, 7, 3, SSD1306_WHITE);
    else                display.drawCircle(cx, 7, 2, SSD1306_WHITE);
  }
}

void drawPageEnvironment() {
  drawHeader("Room");
  char buf[16];

  display.setTextSize(1);
  display.setCursor(0, OLED_BODY_Y);
  display.print("Temp");
  printRight(OLED_BODY_Y, "Humidity", 1);

  display.setTextSize(2);
  display.setCursor(0, 30);
  if (dhtUsable()) {
    snprintf(buf, sizeof(buf), "%.1f", dhtData.temperatureC);
    display.print(buf);
    drawDegreeC((int16_t)(strlen(buf) * 12) + 1, 30);
    snprintf(buf, sizeof(buf), "%.0f%%", dhtData.humidityPct);
    printRight(30, buf, 2);
  } else {
    display.print("--.-");
    printRight(30, "--%", 2);
  }

  if (lightUsable()) snprintf(buf, sizeof(buf), "Light %.0f%%", ldrData.percent);
  else               snprintf(buf, sizeof(buf), "Light --");
  display.setTextSize(1);
  display.setCursor(0, 55);
  display.print(buf);

  const char* mot = !pirData.initialized ? "--"
                  : pirData.state == SENSOR_WARMING_UP ? "wait"
                  : pirData.motion ? "YES" : "no";
  snprintf(buf, sizeof(buf), "Motion %s", mot);
  printRight(55, buf, 1);
}

void drawPageSensors() {
  drawHeader("Gas / smoke");
  char buf[24];

  display.setTextSize(1);
  display.setCursor(0, OLED_BODY_Y);
  display.print("MQ-2 level (avg)");

  display.setTextSize(2);
  display.setCursor(0, 30);
  if (mq2Data.count > 0) display.print(mq2Data.filtered);
  else                   display.print("--");

  const char* status = mq2Data.indication == MQ2_IND_ALERT   ? "ALERT"
                     : mq2Data.indication == MQ2_IND_ERROR   ? "ERROR"
                     : mq2Data.indication == MQ2_IND_WARMING ? "WARM-UP"
                     : "NORMAL";
  bool loud = mq2Data.indication == MQ2_IND_ALERT || mq2Data.indication == MQ2_IND_ERROR;
  int16_t w = (int16_t)(strlen(status) * 6);
  if (loud) {
    display.fillRoundRect(OLED_WIDTH - w - 6, 32, w + 6, 11, 2, SSD1306_WHITE);
    display.setTextColor(SSD1306_BLACK);
  }
  display.setTextSize(1);
  display.setCursor(OLED_WIDTH - w - (loud ? 3 : 0), 34);
  display.print(status);
  display.setTextColor(SSD1306_WHITE);

  unsigned long left = remainingMs(mq2Data.warmupStartMs, MQ2_WARMUP_MS);
  if (left > 0) snprintf(buf, sizeof(buf), "Warm-up %lus left", left / 1000UL + 1);
  else          snprintf(buf, sizeof(buf), "Alarm above %d", MQ2_ALARM_THRESHOLD);
  display.setCursor(0, 55);
  display.print(buf);
}

void drawPageActuators() {
  drawHeader("Outputs");
  drawRow(OLED_BODY_Y + 1, "Fan", act.fanOn ? "ON" : "OFF", act.fanOn);
  drawRow(OLED_BODY_Y + 13, "LED", act.ledOn ? "ON" : "OFF", act.ledOn);
  drawRow(OLED_BODY_Y + 25, "Buzzer", act.alarmActive ? "ALARM" : "OFF", act.alarmActive);
  display.setTextSize(1);
  display.setCursor(0, 56);
  display.print(automationStatus());
}

void drawPageWindow() {
  drawHeader("Rain/window");
  char buf[16];

  display.setTextSize(1);
  display.setCursor(0, OLED_BODY_Y);
  display.print("Rain sensor");
  if (rainData.count > 0) snprintf(buf, sizeof(buf), "avg %d", rainData.filtered);
  else                    snprintf(buf, sizeof(buf), "avg --");
  printRight(OLED_BODY_Y, buf, 1);

  const char* rs = rainData.status == RAIN_WET   ? "RAIN"
                 : rainData.status == RAIN_DRY   ? "DRY"
                 : rainData.status == RAIN_ERROR ? "ERROR"
                 : "WAIT";
  display.setTextSize(2);
  display.setCursor(0, 30);
  display.print(rs);

  WindowState ws = windowState();
  if (ws != WINDOW_UNKNOWN) snprintf(buf, sizeof(buf), "%d deg", win.angle);
  else                      snprintf(buf, sizeof(buf), "-- deg");
  printRight(34, buf, 1);

  drawRow(56, "Window", windowStateName(ws), ws == WINDOW_CLOSED || ws == WINDOW_MOVING);
}

void drawPageSystem() {
  drawHeader("System");
  char buf[24];
  display.setTextSize(1);

  snprintf(buf, sizeof(buf), "DHT %s", shortState(dhtData.state));
  display.setCursor(0, OLED_BODY_Y);
  display.print(buf);
  snprintf(buf, sizeof(buf), "LDR %s", shortState(ldrData.state));
  printRight(OLED_BODY_Y, buf, 1);

  snprintf(buf, sizeof(buf), "PIR %s", shortState(pirData.state));
  display.setCursor(0, OLED_BODY_Y + 12);
  display.print(buf);
  snprintf(buf, sizeof(buf), "MQ2 %s", shortState(mq2Data.state));
  printRight(OLED_BODY_Y + 12, buf, 1);

  char up[20];
  formatUptime(millis() - bootMs, up, sizeof(up));
  drawRow(OLED_BODY_Y + 25, "Uptime", up, false);
  char link[16];
  netShortStatus(link, sizeof(link));
  drawRow(56, "Link", link, !net.backendOk);
}

void drawPageAlarm() {
  char buf[16];
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(10, 0);
  display.print("GAS ALERT");

  display.setTextSize(1);
  display.setCursor(0, OLED_BODY_Y + 4);
  display.print("MQ-2 level");
  snprintf(buf, sizeof(buf), "%d", mq2Data.filtered);
  printRight(OLED_BODY_Y, buf, 2);

  display.setTextSize(1);
  display.setCursor(0, 43);
  display.print("Check the room now.");
  display.setCursor(0, 55);
  display.print("Not a certified alarm");
}

void updateOLED() {
  unsigned long now = millis();

  if (!oled.ok) {
    if (now - oled.lastRetryMs >= OLED_RETRY_MS) initializeDisplay();
    return;
  }

  if (!i2cProbe(OLED_I2C_ADDRESS)) {
    oled.ok = false;
    oled.lastRetryMs = now;
    oled.dropCount++;
    if (!oled.failReported) {
      diag("ERROR", "OLED stopped responding %lu ms after init (drop #%lu). Retrying every %lu s.",
           now - oled.initMs, (unsigned long)oled.dropCount, OLED_RETRY_MS / 1000UL);
      oled.failReported = true;
    }
    return;
  }

  if (now - oled.lastPageMs >= OLED_PAGE_MS) {
    oled.page = (uint8_t)((oled.page + 1) % OLED_PAGE_COUNT);
    oled.lastPageMs = now;
  }

  display.clearDisplay();
  if (act.alarmActive) {
    drawPageAlarm();
    oledInverted = !oledInverted;
  } else {
    oledInverted = false;
    switch (oled.page) {
      case 0: drawPageEnvironment(); break;
      case 1: drawPageSensors();     break;
      case 2: drawPageActuators();   break;
      case 3: drawPageWindow();      break;
      default: drawPageSystem();     break;
    }
  }
  display.invertDisplay(oledInverted);
  display.display();
}

void printStartupInformation() {
  if (serialMode == SERIAL_CSV) return;
  Serial.println();
  Serial.println("=====================================================================");
  Serial.println(" SMARTBUDDY — STANDALONE RULE-BASED MODE");
  Serial.println("=====================================================================");
  Serial.printf(" Firmware     : %s\n", FIRMWARE_VERSION);
  Serial.printf(" Chip         : %s rev %d, %d core(s), %lu MHz\n",
                ESP.getChipModel(), (int)ESP.getChipRevision(), (int)ESP.getChipCores(),
                (unsigned long)ESP.getCpuFreqMHz());
  Serial.printf(" Serial mode  : %s\n", modeName(serialMode));
  Serial.printf(" Connectivity : Wi-Fi '%s' -> HTTP POST %s://%s:%u/api/v1/device/readings\n",
                WIFI_SSID, BACKEND_SCHEME, BACKEND_HOST, (unsigned)BACKEND_PORT);
  Serial.println("                (no MQTT). The rules below keep working without Wi-Fi.");
  Serial.println();
  Serial.println(" Pin map (ESP32 GPIO):");
  Serial.printf("   LED=%d  DHT22=%d  BUZZER=%d  PIR=%d  MQ2=%d  LDR=%d  FAN_GATE=%d  RAIN=%d  SERVO=%d\n",
                LED_PIN, DHT_PIN, BUZZER_PIN, PIR_PIN, MQ2_PIN, LDR_PIN, FAN_PIN, RAIN_PIN, SERVO_PIN);
  Serial.printf("   OLED I2C preferred SDA=%d SCL=%d (auto-detected)\n", I2C_SDA, I2C_SCL);
  Serial.println();
  Serial.println(" Rules:");
  Serial.printf("   Fan    : ON at >= %.1f C, OFF at <= %.1f C, hold in between / if DHT22 invalid\n",
                FAN_ON_TEMP_C, FAN_OFF_TEMP_C);
  Serial.printf("   LED    : ON at light <= %.0f %%, OFF at >= %.0f %%, hold in between\n",
                LED_ON_PCT, LED_OFF_PCT);
  Serial.printf("   Buzzer : only when MQ-2 avg > %d for %lu s (after %lu s warm-up); clears below %d\n",
                MQ2_ALARM_THRESHOLD, MQ2_ALARM_CONFIRM_MS / 1000UL, MQ2_WARMUP_MS / 1000UL,
                MQ2_ALARM_THRESHOLD - MQ2_ALARM_HYSTERESIS);
  Serial.printf("   Window : %s, closes (%d deg) after %lu s of rain, opens (%d deg) after %lu s dry,\n"
                "            holds its position on a rain sensor error\n",
                WINDOW_AUTO_ENABLED ? "auto" : "auto OFF", WINDOW_CLOSED_ANGLE, RAIN_CONFIRM_MS / 1000UL,
                WINDOW_OPEN_ANGLE, WINDOW_REOPEN_DRY_MS / 1000UL);
  Serial.println();
  Serial.println(" LDR calibration: cover the LDR -> Light% should go DOWN.");
  Serial.println("                  If it goes UP instead, flip LDR_INVERT.");
  Serial.println(" Notes  : MQ-2 values are raw ADC (0-4095), NOT ppm.");
  Serial.println("          This prototype is NOT a certified gas/smoke/fire safety device.");
  Serial.println(" Commands: t=table  h=detailed  c=CSV  b=both  ?=help");
  Serial.println("=====================================================================");
}

void printResetReason() {
  esp_reset_reason_t rr = esp_reset_reason();
  const char* text;
  switch (rr) {
    case ESP_RST_POWERON:  text = "power-on / USB plugged in"; break;
    case ESP_RST_EXT:      text = "external reset (EN button)"; break;
    case ESP_RST_SW:       text = "software reset / serial port reset"; break;
    case ESP_RST_PANIC:    text = "CRASH (panic)"; break;
    case ESP_RST_INT_WDT:
    case ESP_RST_TASK_WDT:
    case ESP_RST_WDT:      text = "WATCHDOG reset (check for shorts / weak power)"; break;
    case ESP_RST_BROWNOUT: text = "BROWNOUT - power supply too weak!"; break;
    case ESP_RST_DEEPSLEEP:text = "wake from deep sleep"; break;
    default:               text = "other/unknown"; break;
  }
  bool bad = (rr == ESP_RST_BROWNOUT || rr == ESP_RST_PANIC ||
              rr == ESP_RST_INT_WDT || rr == ESP_RST_TASK_WDT || rr == ESP_RST_WDT);
  diag(bad ? "ERROR" : "INFO", "Reset reason: %d (%s)", (int)rr, text);
  if (rr == ESP_RST_BROWNOUT) {
    diag("ERROR", "Power the MQ-2 heater from a separate 5V supply (shared GND) and use a good USB cable.");
  }
}

void printHelp() {
  if (serialMode == SERIAL_CSV) return;
  Serial.println("---- SmartBuddy serial commands ----");
  Serial.println("  t : live sensor data table (one row per reading)");
  Serial.println("  h : detailed human-readable report");
  Serial.println("  c : CSV output only (diagnostics suppressed)");
  Serial.println("  b : detailed report + CSV");
  Serial.println("  ? : this help");
  Serial.printf("Current mode: %s\n", modeName(serialMode));
}

void handleSerialCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    switch (c) {
      case 't': case 'T': setSerialMode(SERIAL_DATA_TABLE);     break;
      case 'h': case 'H': setSerialMode(SERIAL_HUMAN_READABLE); break;
      case 'c': case 'C': setSerialMode(SERIAL_CSV);            break;
      case 'b': case 'B': setSerialMode(SERIAL_BOTH);           break;
      case '?':           printHelp();                          break;
      default: break;
    }
  }
}

void setSerialMode(SerialOutputMode m) {
  if (m == serialMode) return;
  serialMode = m;
  tableRowsSinceHeader = 0;
  diag("INFO", "Serial output mode changed to %s", modeName(m));
  if (m == SERIAL_CSV || m == SERIAL_BOTH) printCSVHeader();
}

void printDataTable() {
  if (tableRowsSinceHeader == 0) {
    Serial.println();
    Serial.println("---------------------------------------------------------------------------------------------------------------------------");
    Serial.println("  Time(s) | Temp(C) | Hum(%) | Light% | LDR raw | Motion   | MQ2 raw | MQ2 avg | MQ2      | Fan | LED | Buzzer | Rain  | Window");
    Serial.println("---------------------------------------------------------------------------------------------------------------------------");
  }
  tableRowsSinceHeader = (uint16_t)((tableRowsSinceHeader + 1) % TABLE_HEADER_EVERY_ROWS);

  char temp[10], hum[10], light[10], ldrRaw[8], mot[12], raw[8], flt[8];

  if (dhtUsable()) {
    snprintf(temp, sizeof(temp), "%.1f", dhtData.temperatureC);
    snprintf(hum,  sizeof(hum),  "%.1f", dhtData.humidityPct);
  } else {
    strcpy(temp, "N/A");
    strcpy(hum,  "N/A");
  }

  if (lightUsable()) snprintf(light, sizeof(light), "%.1f", ldrData.percent);
  else               strcpy(light, "N/A");
  if (ldrData.hasSample) snprintf(ldrRaw, sizeof(ldrRaw), "%d", ldrData.raw);
  else                   strcpy(ldrRaw, "N/A");

  if (pirData.initialized) {
    snprintf(mot, sizeof(mot), "%s%s", pirData.motion ? "YES" : "no",
             pirData.state == SENSOR_WARMING_UP ? "*" : "");
  } else {
    strcpy(mot, "N/A");
  }

  if (mq2Data.hasSample) snprintf(raw, sizeof(raw), "%d", mq2Data.raw);
  else                   strcpy(raw, "N/A");
  if (mq2Data.count > 0) snprintf(flt, sizeof(flt), "%d", mq2Data.filtered);
  else                   strcpy(flt, "N/A");

  const char* rain = rainData.status == RAIN_INITIALIZING ? "WAIT" : rainStatusName(rainData.status);
  Serial.printf("%9lu | %7s | %6s | %6s | %7s | %-8s | %7s | %7s | %-8s | %-3s | %-3s | %-6s | %-5s | %s\n",
                (unsigned long)((millis() - bootMs) / 1000UL),
                temp, hum, light, ldrRaw, mot, raw, flt,
                mq2IndicationName(mq2Data.indication),
                onOff(act.fanOn), onOff(act.ledOn),
                act.alarmActive ? "ALARM" : "OFF", rain, windowStateName(windowState()));
}

void printHumanReadableData() {
  unsigned long now = millis();
  char up[20];
  formatUptime(now - bootMs, up, sizeof(up));
  char val[48];
  char st[32];
  const char* LINE = "---------------------------------------------------------------------";

  Serial.println();
  Serial.printf("================== SMARTBUDDY  |  Uptime %s ==================\n", up);
  Serial.printf(" %-10s %-28s %s\n", "SENSOR", "VALUE", "STATUS");
  Serial.println(LINE);

  if (dhtUsable())               snprintf(val, sizeof(val), "%.1f C", dhtData.temperatureC);
  else if (dhtData.hasLastValid) snprintf(val, sizeof(val), "N/A (last %.1f C)", dhtData.lastValidTempC);
  else                           strcpy(val, "N/A");
  Serial.printf(" %-10s %-28s %s\n", "Temp", val, sensorStatusText(dhtData.state, 0, st, sizeof(st)));

  if (dhtUsable())               snprintf(val, sizeof(val), "%.1f %%", dhtData.humidityPct);
  else if (dhtData.hasLastValid) snprintf(val, sizeof(val), "N/A (last %.1f %%)", dhtData.lastValidHumPct);
  else                           strcpy(val, "N/A");
  Serial.printf(" %-10s %-28s %s\n", "Humidity", val, sensorStatusText(dhtData.state, 0, st, sizeof(st)));

  if (lightUsable()) snprintf(val, sizeof(val), "%.1f %% (raw avg %d)", ldrData.percent, ldrData.filtered);
  else               strcpy(val, "N/A");
  Serial.printf(" %-10s %-28s %s\n", "Light", val, sensorStatusText(ldrData.state, 0, st, sizeof(st)));

  if (!pirData.initialized) {
    strcpy(val, "N/A");
  } else if (pirData.hasMotionEver) {
    snprintf(val, sizeof(val), "%s (last %lus ago)", pirData.motion ? "DETECTED" : "none",
             (now - pirData.lastMotionMs) / 1000UL);
  } else {
    snprintf(val, sizeof(val), "%s", pirData.motion ? "DETECTED" : "none");
  }
  Serial.printf(" %-10s %-28s %s\n", "Motion", val,
                sensorStatusText(pirData.state, remainingMs(pirData.warmupStartMs, PIR_WARMUP_MS), st, sizeof(st)));

  if (mq2Data.hasSample) snprintf(val, sizeof(val), "raw %d | avg %d", mq2Data.raw, mq2Data.filtered);
  else                   strcpy(val, "N/A");
  const char* mq2St = act.alarmActive ? "ALERT! (threshold exceeded)"
                    : sensorStatusText(mq2Data.state, remainingMs(mq2Data.warmupStartMs, MQ2_WARMUP_MS), st, sizeof(st));
  Serial.printf(" %-10s %-28s %s\n", "MQ-2 gas", val, mq2St);

  if (rainData.hasSample) snprintf(val, sizeof(val), "raw %d | avg %d", rainData.raw, rainData.filtered);
  else                    strcpy(val, "N/A");
  Serial.printf(" %-10s %-28s %s\n", "Rain", val, rainStatusName(rainData.status));

  Serial.println(LINE);
  Serial.printf(" %-10s %-7s %s\n", "OUTPUT", "STATE", "WHY");
  Serial.println(LINE);
  Serial.printf(" %-10s %-7s %s\n", "Fan", onOff(act.fanOn), act.fanReason);
  Serial.printf(" %-10s %-7s %s\n", "LED", onOff(act.ledOn), act.ledReason);

  if (act.alarmActive)                    snprintf(val, sizeof(val), "MQ-2 avg %d > %d", mq2Data.filtered, MQ2_ALARM_THRESHOLD);
  else if (mq2Data.aboveActive)           snprintf(val, sizeof(val), "MQ-2 avg %d > %d, confirming...", mq2Data.filtered, MQ2_ALARM_THRESHOLD);
  else if (mq2Data.state == SENSOR_ERROR) strcpy(val, "MQ-2 error, alarm not evaluated");
  else if (mq2Data.state != SENSOR_READY) strcpy(val, "MQ-2 warming up, alarm paused");
  else                                    snprintf(val, sizeof(val), "MQ-2 avg %d <= %d (normal)", mq2Data.filtered, MQ2_ALARM_THRESHOLD);
  Serial.printf(" %-10s %-7s %s\n", "Buzzer", act.alarmActive ? "ALARM" : "OFF", val);

  WindowState ws = windowState();
  if (ws == WINDOW_UNKNOWN) snprintf(val, sizeof(val), "position unknown");
  else                      snprintf(val, sizeof(val), "servo %d deg, last move: %s", win.angle, win.reason);
  Serial.printf(" %-10s %-7s %s\n", "Window", windowStateName(ws), val);

  Serial.println(LINE);
  Serial.printf(" OLED: %s  |  Mode: %s  |  CSV rows: %lu (valid %lu)\n",
                oled.ok ? "OK" : "NOT CONNECTED", automationStatus(),
                (unsigned long)csvRowsTotal, (unsigned long)csvRowsValid);

  char link[16];
  netShortStatus(link, sizeof(link));
  Serial.printf(" Wi-Fi/HTTP: %s  |  sent %lu, rejected %lu, dropped %lu, last HTTP %d\n", link,
                (unsigned long)net.sent, (unsigned long)net.rejected, (unsigned long)net.dropped, net.lastHttpCode);

  if (!oled.ok)
    Serial.printf(" CHECK: OLED not answering -> VCC=3V3, GND, SDA=GPIO%d, SCL=GPIO%d, address 0x3C.\n", i2cSda, i2cScl);
  if (dhtData.state == SENSOR_ERROR) Serial.println(" CHECK: DHT22 not responding -> data on GPIO5, 10k pull-up, 3.3V, GND.");
  if (mq2Data.state == SENSOR_ERROR) Serial.println(" CHECK: MQ-2 reads ~0 -> 5V heater supply, AO divider, common GND.");
  Serial.println("=====================================================================");
}

void printCSVHeader() {
  Serial.println("timestamp_ms,temperature_c,humidity_percent,light_percent,ldr_raw,motion_detected,"
                 "mq2_raw,mq2_filtered,mq2_status,fan_state,led_state,buzzer_state,"
                 "dht_status,ldr_status,pir_status,mq2_sensor_status,dht_new_reading,record_valid,"
                 "rain_raw,rain_filtered,rain_status,window_state,servo_angle");
}

void printCSVData() {
  unsigned long now = millis();
  bool dhtOk   = dhtUsable();
  bool lightOk = lightUsable();
  bool pirOk   = pirUsable();
  bool dhtNew  = dhtData.newSinceCsv && dhtOk;
  bool recordValid = dhtOk && lightOk && pirOk && dhtNew &&
                     mq2Data.state == SENSOR_READY && mq2Data.filterFull;

  Serial.print(now);                                     Serial.print(',');
  if (dhtOk) Serial.print(dhtData.temperatureC, 1);      Serial.print(',');
  if (dhtOk) Serial.print(dhtData.humidityPct, 1);       Serial.print(',');
  if (lightOk) Serial.print(ldrData.percent, 1);         Serial.print(',');
  if (ldrData.hasSample) Serial.print(ldrData.raw);      Serial.print(',');
  if (pirOk) Serial.print(pirData.motion ? 1 : 0);       Serial.print(',');
  if (mq2Data.hasSample) Serial.print(mq2Data.raw);      Serial.print(',');
  if (mq2Data.count > 0) Serial.print(mq2Data.filtered); Serial.print(',');
  Serial.print(mq2IndicationName(mq2Data.indication));   Serial.print(',');
  Serial.print(act.fanOn ? 1 : 0);                       Serial.print(',');
  Serial.print(act.ledOn ? 1 : 0);                       Serial.print(',');
  Serial.print(act.alarmActive ? 1 : 0);                 Serial.print(',');
  Serial.print(stateName(dhtData.state));                Serial.print(',');
  Serial.print(stateName(ldrData.state));                Serial.print(',');
  Serial.print(stateName(pirData.state));                Serial.print(',');
  Serial.print(stateName(mq2Data.state));                Serial.print(',');
  Serial.print(dhtNew ? 1 : 0);                          Serial.print(',');
  Serial.print(recordValid ? 1 : 0);                     Serial.print(',');
  if (rainData.hasSample) Serial.print(rainData.raw);    Serial.print(',');
  if (rainData.count > 0) Serial.print(rainData.filtered); Serial.print(',');
  Serial.print(rainStatusName(rainData.status));         Serial.print(',');
  WindowState ws = windowState();
  Serial.print(windowStateName(ws));                     Serial.print(',');
  if (ws != WINDOW_UNKNOWN) Serial.print(win.angle);
  Serial.println();

  dhtData.newSinceCsv = false;
  csvRowsTotal++;
  if (recordValid) csvRowsValid++;
}

void setup() {
  initializeActuators();

  Serial.begin(SERIAL_BAUD);
  delay(300);
  bootMs = millis();

  printStartupInformation();
  printResetReason();
  diag("INFO", "Actuators initialized: Fan OFF, LED OFF, Buzzer OFF.");

  ledSelfTest();

  initializeSensors();
  initializeWindow();
  initializeDisplay();
  initializeNetwork();

  unsigned long now = millis();
  tPir = tMq2 = tDht = tLdr = tOled = tHuman = tCsv = tNet = tRain = now;

  if (serialMode == SERIAL_CSV || serialMode == SERIAL_BOTH) printCSVHeader();
  diag("INFO", "Setup complete. Entering main loop.");
}

void loop() {
  handleSerialCommands();

  if (isDue(tPir, PIR_INTERVAL_MS)) {
    readPIR();
  }

  if (isDue(tMq2, MQ2_INTERVAL_MS)) {
    readMQ2();
    handleMQ2Alarm();
  }

  if (isDue(tDht, DHT_INTERVAL_MS)) {
    readDHT22();
    handleFanAutomation();
  }

  if (isDue(tLdr, LDR_INTERVAL_MS)) {
    readLDR();
    handleLEDAutomation();
  }

  if (isDue(tRain, RAIN_INTERVAL_MS)) {
    readRain();
    handleWindowAutomation();
  }

  updateBuzzer();
  updateServo();

  if (isDue(tOled, OLED_REFRESH_MS)) {
    updateOLED();
  }

  if (isDue(tHuman, HUMAN_PRINT_INTERVAL_MS)) {
    if (serialMode == SERIAL_HUMAN_READABLE || serialMode == SERIAL_BOTH) printHumanReadableData();
    else if (serialMode == SERIAL_DATA_TABLE) printDataTable();
  }

  if (isDue(tCsv, CSV_INTERVAL_MS)) {
    if (serialMode == SERIAL_CSV || serialMode == SERIAL_BOTH) printCSVData();
  }

  if (isDue(tNet, NET_SEND_INTERVAL_MS)) {
    queueReading();
  }
  printNetLog();
}

char    netBootId[9]     = "00000000";
int64_t netClockOffsetMs = 0;

void netLog(const char* fmt, ...) {
  if (netLogQueue == nullptr) return;
  NetLogLine line;
  va_list args;
  va_start(args, fmt);
  vsnprintf(line.text, sizeof(line.text), fmt, args);
  va_end(args);
  xQueueSend(netLogQueue, &line, 0);
}

void printNetLog() {
  if (netLogQueue == nullptr) return;
  NetLogLine line;
  while (xQueueReceive(netLogQueue, &line, 0) == pdTRUE) diag("NET", "%s", line.text);
}

void netShortStatus(char* buf, size_t len) {
  if (!net.started)            snprintf(buf, len, "off");
  else if (!net.wifiConnected) snprintf(buf, len, "no Wi-Fi");
  else if (!net.backendOk)     snprintf(buf, len, "no server");
  else                         snprintf(buf, len, "OK %ddBm", (int)net.rssi);
}

uint8_t netHealth(SensorState s, bool hasValue) {
  if (s == SENSOR_READY) return hasValue ? NET_OK : NET_ERROR;
  if (s == SENSOR_ERROR) return NET_ERROR;
  return NET_WARMING_UP;
}

// http can block for seconds, so it runs in netTask on core 0 and loop() only queues readings
void queueReading() {
  if (netQueue == nullptr) return;
  NetReading r = {};
  r.sequence     = netSequence++;
  r.uptimeMs     = millis();
  r.dht          = netHealth(dhtData.state, dhtUsable());
  r.ldr          = netHealth(ldrData.state, lightUsable() && ldrData.hasSample);
  r.pir          = netHealth(pirData.state, pirUsable());
  r.mq2          = netHealth(mq2Data.state, mq2Data.count > 0);
  r.temperatureC = dhtData.temperatureC;
  r.humidityPct  = dhtData.humidityPct;
  r.lightPct     = ldrData.percent;
  r.ldrRaw       = (int16_t)ldrData.raw;
  r.motion       = pirData.motion;
  r.gasAdc       = (int16_t)mq2Data.filtered;
  r.gasWarning   = act.alarmActive;
  r.fanOn        = act.fanOn;
  r.ledOn        = act.ledOn;
  r.rainHasRaw      = rainData.hasSample;
  r.rainHasFiltered = rainData.count > 0;
  r.rainRaw         = (int16_t)rainData.raw;
  r.rainFiltered    = (int16_t)rainData.filtered;
  r.rainStatus      = rainData.status;
  r.windowState     = windowState();
  r.servoAngle      = (int16_t)win.angle;

  if (xQueueSend(netQueue, &r, 0) != pdTRUE) {
    NetReading oldest;
    xQueueReceive(netQueue, &oldest, 0);
    xQueueSend(netQueue, &r, 0);
    net.dropped++;
  }
}

void jsonFloat(char* out, size_t len, bool ok, float v) {
  if (ok) snprintf(out, len, "%.1f", v);
  else    snprintf(out, len, "null");
}

void jsonInt(char* out, size_t len, bool ok, int v) {
  if (ok) snprintf(out, len, "%d", v);
  else    snprintf(out, len, "null");
}

int buildReadingJson(const NetReading& r, char* out, size_t len) {
  static const char* STATUS[] = {"ok", "error", "warming_up"};
  static const char* RAIN[]   = {"initializing", "dry", "rain", "error"};
  static const char* WINDOW[] = {"unknown", "open", "closed", "moving"};

  char ts[32] = "null";
  if (net.clockSynced) {
    int64_t ms = netClockOffsetMs + (int64_t)r.uptimeMs;
    time_t secs = (time_t)(ms / 1000);
    struct tm t;
    gmtime_r(&secs, &t);
    char base[24];
    strftime(base, sizeof(base), "%Y-%m-%dT%H:%M:%S", &t);
    snprintf(ts, sizeof(ts), "\"%s.%03dZ\"", base, (int)(ms % 1000));
  }

  char temp[12], hum[12], light[12], ldr[8], motion[8], gas[8];
  jsonFloat(temp,  sizeof(temp),  r.dht == NET_OK, r.temperatureC);
  jsonFloat(hum,   sizeof(hum),   r.dht == NET_OK, r.humidityPct);
  jsonFloat(light, sizeof(light), r.ldr == NET_OK, r.lightPct);
  jsonInt(ldr, sizeof(ldr), r.ldr == NET_OK, r.ldrRaw);
  jsonInt(gas, sizeof(gas), r.mq2 == NET_OK, r.gasAdc);
  snprintf(motion, sizeof(motion), "%s", r.pir == NET_OK ? (r.motion ? "true" : "false") : "null");

  char rainRaw[8], rainAvg[8], angle[8];
  jsonInt(rainRaw, sizeof(rainRaw), r.rainHasRaw, r.rainRaw);
  jsonInt(rainAvg, sizeof(rainAvg), r.rainHasFiltered, r.rainFiltered);
  jsonInt(angle, sizeof(angle), r.windowState != WINDOW_UNKNOWN, r.servoAngle);

  return snprintf(out, len,
    "{\"device_id\":\"%s\",\"boot_id\":\"%s\",\"sequence\":%lu,\"timestamp\":%s,\"uptime_ms\":%lu,"
    "\"temperature_c\":%s,\"humidity_pct\":%s,\"light_pct\":%s,\"ldr_raw\":%s,\"motion_detected\":%s,"
    "\"gas_adc\":%s,\"gas_warning_local\":%s,"
    "\"sensor_status\":{\"dht\":\"%s\",\"ldr\":\"%s\",\"pir\":\"%s\",\"mq2\":\"%s\"},"
    "\"actuators\":{\"fan\":%s,\"light\":%s,\"buzzer\":%s},"
    "\"rain_raw\":%s,\"rain_filtered\":%s,\"rain_status\":\"%s\",\"window_state\":\"%s\","
    "\"servo_angle\":%s,\"window_auto\":%s,\"source\":\"device\"}",
    DEVICE_ID, netBootId, (unsigned long)r.sequence, ts, (unsigned long)r.uptimeMs,
    temp, hum, light, ldr, motion, gas, r.gasWarning ? "true" : "false",
    STATUS[r.dht], STATUS[r.ldr], STATUS[r.pir], STATUS[r.mq2],
    r.fanOn ? "true" : "false", r.ledOn ? "true" : "false", r.gasWarning ? "true" : "false",
    rainRaw, rainAvg, RAIN[r.rainStatus], WINDOW[r.windowState], angle, WINDOW_AUTO_ENABLED ? "true" : "false");
}

void netReadServerTime(const String& body) {
  int i = body.indexOf("\"server_time_ms\":");
  if (i < 0) return;
  int64_t serverMs = strtoll(body.c_str() + i + 17, nullptr, 10);
  if (serverMs < 1600000000000LL) return;
  netClockOffsetMs = serverMs - (int64_t)millis();
  net.clockSynced = true;
}

int netRequest(const char* path, const char* body) {
  // kept between calls so the tls handshake (about 1 s) happens once, not every 2 s
  static NetworkClientSecure secureClient;
  static WiFiClient plainClient;
  static HTTPClient http;
  static bool firstCall = true;
  if (firstCall) {
    secureClient.useBuiltinCACertBundle();
    secureClient.setHandshakeTimeout(10);
    http.setReuse(true);
    firstCall = false;
  }

  char url[160];
  snprintf(url, sizeof(url), "%s://%s:%u%s", BACKEND_SCHEME, BACKEND_HOST, (unsigned)BACKEND_PORT, path);
  http.setConnectTimeout(NET_HTTP_TIMEOUT_MS);
  http.setTimeout(NET_HTTP_TIMEOUT_MS);
  bool ok = BACKEND_HTTPS ? http.begin(secureClient, url) : http.begin(plainClient, url);
  if (!ok) return -1;

  int code;
  if (body != nullptr) {
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", "Bearer " DEVICE_KEY);
    code = http.POST((uint8_t*)body, strlen(body));
  } else {
    code = http.GET();
  }
  if (code > 0) netReadServerTime(http.getString());
  http.end();
  return code;
}

const char* netHttpHint(int code) {
  switch (code) {
    case 401: return "device key not accepted - check DEVICE_KEY (secrets.h) vs DEVICE_KEYS (.env)";
    case 403: return "forbidden - DEVICE_ID in secrets.h must match the key";
    case 413: return "reading too large";
    case 422: return "backend rejected the reading format";
    case 429: return "too many requests, slowing down";
    case 502:
    case 503: return "server is starting up (Render wakes up in about a minute)";
    default:
      if (code >= 0) return "unexpected response";
      return BACKEND_HTTPS ? "server not reachable - BACKEND_HOST right? internet on this Wi-Fi?"
                           : "backend not reachable - HOST=0.0.0.0? firewall rule? laptop IP?";
  }
}

void netTask(void*) {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  snprintf(netBootId, sizeof(netBootId), "%08lx", (unsigned long)esp_random());
  netLog("Joining Wi-Fi '%s', boot id %s", WIFI_SSID, netBootId);

  unsigned long joinStartMs = millis();
  unsigned long retryAtMs   = millis();
  bool wasConnected   = false;
  int  lastLoggedCode = 0;
  NetReading pending;
  bool hasPending = false;
  char body[768];

  for (;;) {
    unsigned long now = millis();
    bool up = WiFi.status() == WL_CONNECTED;
    if (up != wasConnected) {
      wasConnected = up;
      net.wifiConnected = up;
      if (up) {
        netLog("Wi-Fi connected, IP %s, signal %d dBm", WiFi.localIP().toString().c_str(), (int)WiFi.RSSI());
      } else {
        net.backendOk = false;
        joinStartMs = now;
        netLog("Wi-Fi lost, reconnecting (readings are queued)");
      }
    }
    if (!up) {
      if (now - joinStartMs >= NET_WIFI_REJOIN_MS) {
        netLog("Still no Wi-Fi '%s' (2.4 GHz only). Trying again.", WIFI_SSID);
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
        joinStartMs = now;
      }
      vTaskDelay(pdMS_TO_TICKS(250));
      continue;
    }
    net.rssi = (int8_t)WiFi.RSSI();

    if ((long)(now - retryAtMs) < 0) {
      vTaskDelay(pdMS_TO_TICKS(100));
      continue;
    }

    if (!net.clockSynced) {
      int code = netRequest("/api/v1/health", nullptr);
      if (code <= 0) {
        net.backendOk = false;
        net.lastHttpCode = code;
        if (code != lastLoggedCode) netLog("HTTP %d: %s", code, netHttpHint(code));
        lastLoggedCode = code;
        retryAtMs = now + NET_RETRY_MS;
        continue;
      }
    }

    if (!hasPending) {
      if (xQueueReceive(netQueue, &pending, pdMS_TO_TICKS(250)) != pdTRUE) continue;
      hasPending = true;
    }

    int len = buildReadingJson(pending, body, sizeof(body));
    if (len <= 0 || len >= (int)sizeof(body)) {
      hasPending = false;
      net.rejected++;
      continue;
    }

    int code = netRequest("/api/v1/device/readings", body);
    net.lastHttpCode = code;
    if (code == 200 || code == 201) {
      hasPending = false;
      net.sent++;
      if (!net.backendOk) netLog("Backend reachable, sending readings (HTTP %d)", code);
      net.backendOk = true;
      lastLoggedCode = code;
    } else if (code >= 400 && code < 500 && code != 429) {
      hasPending = false;
      net.rejected++;
      net.backendOk = false;
      if (code != lastLoggedCode) netLog("HTTP %d: %s", code, netHttpHint(code));
      lastLoggedCode = code;
    } else {
      net.backendOk = false;
      if (code != lastLoggedCode) netLog("HTTP %d: %s", code, netHttpHint(code));
      lastLoggedCode = code;
      retryAtMs = now + NET_RETRY_MS;
    }
  }
}

void initializeNetwork() {
  netQueue    = xQueueCreate(NET_QUEUE_LEN, sizeof(NetReading));
  netLogQueue = xQueueCreate(8, sizeof(NetLogLine));
  if (netQueue == nullptr || netLogQueue == nullptr ||
      xTaskCreatePinnedToCore(netTask, "net", BACKEND_HTTPS ? 12288 : 8192, nullptr, 1, nullptr, 0) != pdPASS) {
    diag("ERROR", "Not enough memory to start the network task. Running without Wi-Fi.");
    return;
  }
  net.started = true;
  diag("INFO", "Network task started: Wi-Fi '%s' -> %s://%s:%u as %s", WIFI_SSID, BACKEND_SCHEME, BACKEND_HOST,
       (unsigned)BACKEND_PORT, DEVICE_ID);
}
