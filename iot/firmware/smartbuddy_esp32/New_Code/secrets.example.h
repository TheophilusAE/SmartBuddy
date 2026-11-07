// copy to secrets.h and fill in (or run scripts/make_firmware_secrets.py). don't commit secrets.h
#pragma once

#define WIFI_SSID     "your-wifi-name"       // 2.4 GHz only
#define WIFI_PASSWORD "your-wifi-password"

// backend on render (any wi-fi with internet works)
#define BACKEND_HOST  "your-app.onrender.com"
#define BACKEND_PORT  443
#define BACKEND_HTTPS 1

// backend on the laptop instead (same wi-fi as the esp32)
// #define BACKEND_HOST  "192.168.1.50"      // laptop IP (ipconfig)
// #define BACKEND_PORT  8000
// #define BACKEND_HTTPS 0

#define DEVICE_ID     "sb-esp32-01"
#define DEVICE_KEY    "paste-the-device-key-here"
