/*
 * bijli-watch — ESP32 firmware
 * ============================
 * Reads voltage / current / power / cumulative energy from a
 * PZEM-004T-100A energy-meter module over UART, and POSTs a JSON reading
 * to the bijli-watch server every POST_INTERVAL_MS.
 *
 *   POST http://<server>:5000/readings
 *   {"device_id":"bijli-watch-1","voltage_v":231.2,"current_a":6.31,
 *    "power_w":1458.0,"energy_kwh":123.456}
 *
 * Libraries (Arduino IDE -> Library Manager):
 *   - ESP32 board core            ("esp32" by Espressif)
 *   - ArduinoJson                 (by Benoit Blanchon)
 *   - PZEM004Tv30                 (by Jakub Mandula) — OPTIONAL, see below
 *
 * If the PZEM004Tv30 library is not installed, the sketch still compiles:
 * readSensor() falls back to clearly-marked DEMO values so you can test
 * WiFi + the server end-to-end before wiring any mains hardware.
 *
 * !!! SAFETY !!!
 * The PZEM-004T measures AC MAINS. Mains can kill. Use the CT-clamp
 * (non-invasive) version of the sensor, never open your distribution
 * board unless you are qualified, and get a licensed electrician to do
 * the mains-side wiring. See firmware/README.md.
 */

// ---------------------------------------------------------------------------
// CONFIG — edit these before flashing. These are PLACEHOLDERS, never commit
// real WiFi credentials to GitHub.
// ---------------------------------------------------------------------------
static const char*    WIFI_SSID           = "YOUR_WIFI_SSID";
static const char*    WIFI_PASSWORD       = "YOUR_WIFI_PASSWORD";
static const char*    SERVER_URL          = "http://192.168.1.100:5000/readings";
static const char*    DEVICE_ID           = "bijli-watch-1";
static const uint32_t POST_INTERVAL_MS    = 10000;   // post every 10 seconds
static const uint32_t WIFI_RETRY_MS       = 5000;    // WiFi reconnect backoff
static const int      LED_PIN             = 2;       // onboard LED, blink per post

// PZEM-004T UART pins (UART2 on ESP32)
static const int PZEM_RX_PIN = 16;  // ESP32 RX2 <- PZEM TX
static const int PZEM_TX_PIN = 17;  // ESP32 TX2 -> PZEM RX

// ---------------------------------------------------------------------------
// Includes
// ---------------------------------------------------------------------------
#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

// PZEM004Tv30 is optional at compile time (see header comment).
#if __has_include(<PZEM004Tv30.h>)
  #include <PZEM004Tv30.h>
  #define HAS_PZEM 1
  // CT-clamp / serial constructor: (Serial, rxPin, txPin)
  PZEM004Tv30 pzem(Serial2, PZEM_RX_PIN, PZEM_TX_PIN);
#else
  #define HAS_PZEM 0
#endif

// ---------------------------------------------------------------------------
// Sensor reading — the single place hardware access lives.
// ---------------------------------------------------------------------------
struct Reading {
  float voltageV;
  float currentA;
  float powerW;
  float energyKwh;   // cumulative, from the meter itself when available
  bool  valid;
};

static float demoEnergyKwh = 0.0;       // only used in no-library DEMO mode
static uint32_t lastDemoMs = 0;

Reading readSensor() {
  Reading r{0, 0, 0, 0, false};

#if HAS_PZEM
  r.voltageV  = pzem.voltage();
  r.currentA  = pzem.current();
  r.powerW    = pzem.power();
  r.energyKwh = pzem.energy();
  // The library returns NaN when the meter does not answer.
  r.valid = !isnan(r.voltageV) && !isnan(r.powerW);
#else
  // ---- DEMO MODE (no PZEM library): plausible, obviously fake values ----
  // A wandering ~1.4 kW load so the dashboard does something interesting.
  float wave = sin(millis() / 60000.0f) * 0.5f + 0.5f;   // 0..1, ~2 min period
  r.voltageV  = 230.0f + wave * 4.0f;
  r.powerW    = 250.0f + wave * 1300.0f;
  r.currentA  = r.powerW / r.voltageV;
  uint32_t now = millis();
  if (lastDemoMs > 0) {
    float hours = (now - lastDemoMs) / 3600000.0f;
    demoEnergyKwh += (r.powerW * hours) / 1000.0f;  // W * h = Wh; /1000 = kWh
  }
  lastDemoMs = now;
  r.energyKwh = demoEnergyKwh;
  r.valid = true;
#endif
  return r;
}

// ---------------------------------------------------------------------------
// WiFi — connect, and reconnect with backoff when it drops.
// ---------------------------------------------------------------------------
void ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;

  Serial.printf("[wifi] connecting to %s", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  uint32_t started = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - started < WIFI_RETRY_MS * 4) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[wifi] connected, IP %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\n[wifi] still not connected — will retry next loop");
  }
}

// ---------------------------------------------------------------------------
// POST one reading as JSON.
// ---------------------------------------------------------------------------
bool postReading(const Reading& r) {
  if (WiFi.status() != WL_CONNECTED) return false;

  StaticJsonDocument<256> doc;
  doc["device_id"]  = DEVICE_ID;
  doc["voltage_v"]  = serialized(String(r.voltageV, 1));
  doc["current_a"]  = serialized(String(r.currentA, 3));
  doc["power_w"]    = serialized(String(r.powerW, 1));
  doc["energy_kwh"] = serialized(String(r.energyKwh, 3));

  String body;
  serializeJson(doc, body);

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(body);
  String reply = http.getString();
  http.end();

  Serial.printf("[post] HTTP %d  %s\n", code, body.c_str());
  if (code < 200 || code >= 300) {
    Serial.printf("[post] server replied: %s\n", reply.c_str());
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
#if HAS_PZEM
  Serial2.begin(9600, SERIAL_8N1, PZEM_RX_PIN, PZEM_TX_PIN);
  Serial.println("[init] PZEM-004T on Serial2");
#else
  Serial.println("[init] PZEM004Tv30 library NOT found — running in DEMO mode");
#endif
  ensureWiFi();
}

void loop() {
  ensureWiFi();

  Reading r = readSensor();
  if (r.valid) {
    digitalWrite(LED_PIN, HIGH);
    postReading(r);
    digitalWrite(LED_PIN, LOW);
  } else {
    Serial.println("[sensor] no valid reading — check PZEM wiring / power");
  }

  delay(POST_INTERVAL_MS);
}
