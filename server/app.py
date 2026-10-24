"""
bijli-watch server — Flask app.

Why Flask (and not FastAPI)?
----------------------------
* One small file a beginner can read top-to-bottom; no async, no schema
  framework, no separate ASGI server to learn before the demo runs.
* The API surface is tiny (4 routes) and the audience is home users /
  students flashing an ESP32, not API consumers needing OpenAPI docs.
* FastAPI is a great choice for a bigger, typed, multi-client API — it is
  deliberately *not* needed here. Swapping later is easy because all the
  real logic lives in tariff.py / logic.py, which are framework-free.

Run:
    pip install -r requirements.txt
    python -m server.app            # from the project root
    # or:  flask --app server.app run --host 0.0.0.0 --port 5000

Storage is in-memory on purpose (a demo / home tool, restarts clear it).
Swap ``ReadingStore`` for SQLite if you want persistence — see README roadmap.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from flask import Flask, jsonify, request

try:  # package import
    from .logic import summarise
except ImportError:  # direct script: python server/app.py
    from logic import summarise  # type: ignore


class ReadingStore:
    """Thread-safe in-memory list of readings (oldest first)."""

    def __init__(self, max_readings: int = 10000):
        self._readings: list[dict] = []
        self._lock = threading.Lock()
        self._max = max_readings

    def add(self, reading: dict) -> dict:
        with self._lock:
            self._readings.append(reading)
            # Keep memory bounded on a long-running home server.
            if len(self._readings) > self._max:
                del self._readings[: len(self._readings) - self._max]
            return reading

    def all(self) -> list[dict]:
        with self._lock:
            return list(self._readings)

    def recent(self, limit: int) -> list[dict]:
        with self._lock:
            return list(self._readings[-limit:])

    def clear(self) -> None:
        with self._lock:
            self._readings.clear()


store = ReadingStore()
app = Flask(__name__)


def _normalise_reading(payload: dict) -> tuple[dict | None, str | None]:
    """Validate/normalise an incoming reading. Returns (reading, error)."""
    if not isinstance(payload, dict):
        return None, "JSON object expected"

    power = payload.get("power_w")
    voltage = payload.get("voltage_v")
    current = payload.get("current_a")

    # Derive power from V x A when the sensor only sent those two.
    if power is None and voltage is not None and current is not None:
        power = round(float(voltage) * float(current), 2)
    if power is None:
        return None, "power_w is required (or send voltage_v and current_a)"

    try:
        reading = {
            "timestamp": payload.get("timestamp")
            or datetime.now(timezone.utc).isoformat(),
            "device_id": str(payload.get("device_id", "default")),
            "voltage_v": float(voltage) if voltage is not None else None,
            "current_a": float(current) if current is not None else None,
            "power_w": float(power),
            "energy_kwh": (
                float(payload["energy_kwh"])
                if payload.get("energy_kwh") is not None
                else None
            ),
        }
    except (TypeError, ValueError):
        return None, "voltage_v, current_a, power_w and energy_kwh must be numbers"

    if reading["power_w"] < 0:
        return None, "power_w cannot be negative"
    return reading, None


@app.post("/readings")
def ingest_reading():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify(error="Request body must be JSON"), 400
    reading, error = _normalise_reading(payload)
    if error:
        return jsonify(error=error), 400
    store.add(reading)
    return jsonify(status="ok", reading=reading), 201


@app.get("/readings")
def list_readings():
    try:
        limit = int(request.args.get("limit", 100))
    except ValueError:
        return jsonify(error="limit must be an integer"), 400
    limit = max(1, min(limit, 1000))
    return jsonify(readings=store.recent(limit), count=len(store.recent(limit)))


@app.get("/summary")
def summary():
    return jsonify(summarise(store.all()))


@app.get("/health")
def health():
    return jsonify(status="ok", readings=len(store.all()))


@app.get("/")
def dashboard():
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>bijli-watch — live dashboard</title>
<style>
  body { font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 860px;
         padding: 0 1rem; color: #1a1a1a; }
  .cards { display: flex; gap: 1rem; flex-wrap: wrap; }
  .card { border: 1px solid #ddd; border-radius: 12px; padding: 1rem 1.25rem;
          min-width: 180px; flex: 1; }
  .big { font-size: 1.9rem; font-weight: 700; }
  .label { color: #666; font-size: .85rem; text-transform: uppercase;
           letter-spacing: .04em; }
  #alert { display: none; background: #ffe3e3; border: 1px solid #e03131;
           color: #862e2e; border-radius: 8px; padding: .75rem 1rem; margin: 1rem 0; }
  canvas { width: 100%; height: 260px; border: 1px solid #ddd; border-radius: 12px; }
  .fallback { color: #666; }
</style>
</head>
<body>
<h1>⚡ bijli-watch</h1>
<p class="fallback" id="fallback-text">
  Live dashboard. If the numbers below never appear, JavaScript or the
  server API may be blocked — you can still read the raw data at
  <a href="/summary">/summary</a> and <a href="/readings">/readings</a>.
</p>

<div id="alert" role="alert"></div>

<div class="cards">
  <div class="card"><div class="label">Current power</div>
    <div class="big"><span id="power">–</span> W</div></div>
  <div class="card"><div class="label">Today</div>
    <div class="big"><span id="today">–</span> kWh</div></div>
  <div class="card"><div class="label">Est. monthly bill*</div>
    <div class="big">₹<span id="bill">–</span></div></div>
  <div class="card"><div class="label">Spike alerts</div>
    <div class="big"><span id="spikes">–</span></div></div>
</div>

<h2>Power — recent readings</h2>
<canvas id="chart" width="820" height="260"></canvas>
<p class="fallback" id="chart-fallback">Chart draws here when readings arrive.</p>
<p><small>* Indicative estimate from documented approximate UP domestic
slabs — not an official UPPCL bill. See README tariff disclaimer.</small></p>

<!-- Chart.js from CDN when available; the hand-rolled canvas fallback
     below is used automatically if the CDN cannot be reached. -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<script>
let chart = null;
function drawFallback(points) {
  const c = document.getElementById('chart'), ctx = c.getContext('2d');
  ctx.clearRect(0, 0, c.width, c.height);
  if (!points.length) return;
  const max = Math.max(...points, 100);
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = (i / Math.max(points.length - 1, 1)) * (c.width - 20) + 10;
    const y = c.height - 15 - (p / max) * (c.height - 30);
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  });
  ctx.strokeStyle = '#f08c00'; ctx.lineWidth = 2; ctx.stroke();
}
async function refresh() {
  try {
    const [summaryRes, readingsRes] = await Promise.all([
      fetch('/summary'), fetch('/readings?limit=60')
    ]);
    const s = await summaryRes.json();
    const r = await readingsRes.json();
    if (s.latest_reading) {
      document.getElementById('power').textContent =
        Math.round(s.latest_reading.power_w);
    }
    document.getElementById('today').textContent = s.today_kwh;
    document.getElementById('bill').textContent =
      s.estimated_monthly_bill_inr.toLocaleString('en-IN');
    document.getElementById('spikes').textContent = s.spike_alert_count;
    const alertBox = document.getElementById('alert');
    if (s.has_active_spike) {
      alertBox.style.display = 'block';
      alertBox.textContent = '⚠ Power spike right now: ' +
        Math.round(s.latest_reading.power_w) + ' W (threshold ' +
        s.spike_threshold_w + ' W) — check the geyser / AC / iron.';
    } else { alertBox.style.display = 'none'; }

    const powers = r.readings.map(x => x.power_w);
    const labels = r.readings.map(x =>
      new Date(x.timestamp).toLocaleTimeString('en-IN'));
    document.getElementById('chart-fallback').textContent =
      powers.length ? '' : 'No readings yet — start the simulator or the ESP32.';
    if (window.Chart) {
      if (!chart) {
        chart = new Chart(document.getElementById('chart'), {
          type: 'line',
          data: { labels, datasets: [{ label: 'Watts', data: powers,
                    borderColor: '#f08c00', tension: 0.25 }] },
          options: { animation: false, scales: { y: { beginAtZero: true } } }
        });
      } else {
        chart.data.labels = labels;
        chart.data.datasets[0].data = powers;
        chart.update();
      }
    } else {
      drawFallback(powers);
    }
  } catch (e) {
    document.getElementById('chart-fallback').textContent =
      'Could not reach the API: ' + e;
  }
}
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


if __name__ == "__main__":
    # Local demo server. Use a real WSGI server (gunicorn/waitress) and
    # authentication before exposing this beyond your home network.
    app.run(host="0.0.0.0", port=5000)
