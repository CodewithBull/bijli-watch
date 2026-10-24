# Firmware — bijli-watch ESP32

Arduino sketch: [`bijli_watch.ino`](bijli_watch.ino)

## Parts

See the main README for the full shopping list with approximate INR prices.
In short: ESP32 dev board, PZEM-004T-100A (CT-clamp version strongly
recommended), 5 V USB supply, a plastic enclosure, jumper wires.

## Wiring (CT-clamp PZEM-004T → ESP32)

```
PZEM-004T (CT version)              ESP32 DevKit
-----------------------             ------------
TX  ------------------------------> GPIO16 (RX2)
RX  ------------------------------> GPIO17 (TX2)
5V  ------------------------------> 5V / VIN (USB-powered)
GND ------------------------------> GND

CT clamp: around ONE live wire only (never both live+neutral,
or the fields cancel and you will read ~0 A).
PZEM mains input: as per the module's own manual — MAINS SIDE.
```

> ⚠️ **Safety:** the PZEM's own power / measurement side connects to
> 230 V AC mains. Mains can kill, and a mistake can start a fire.
> Use the non-invasive CT clamp, keep all mains wiring inside a
> closed insulated enclosure, and **get a licensed electrician to do
> the mains-side installation**. If in doubt, run the demo/simulator
> mode instead — it is the same software experience with zero mains.

## Flashing

1. Install the Arduino IDE and the **ESP32 board core**
   (Boards Manager → search `esp32`).
2. Install **ArduinoJson** (Library Manager).
   Optionally install **PZEM004Tv30** for a real sensor — without it the
   sketch compiles and runs in clearly-marked DEMO mode.
3. Open `bijli_watch.ino`, edit the CONFIG block at the top:
   `WIFI_SSID`, `WIFI_PASSWORD`, `SERVER_URL` (your computer's LAN IP,
   e.g. `http://192.168.1.100:5000/readings`). Never commit real
   credentials — they are placeholders in the repo on purpose.
4. Select your board + port, upload, open Serial Monitor at 115200 baud.
   You should see WiFi connect and a `[post] HTTP 201` line every
   10 seconds.

## How it behaves

- Reconnects to WiFi automatically with backoff if it drops.
- Blinks the onboard LED (GPIO2) on each post attempt.
- Prints every reading and the HTTP status to Serial for debugging.
- If the PZEM does not answer, values come back NaN, the reading is
  marked invalid, and nothing is posted.
