#!/usr/bin/env python3
"""
bijli-watch simulator — no hardware needed.

Generates realistic Indian household load patterns and POSTs them to the
bijli-watch server exactly like the ESP32 does:

  * fridge baseline that cycles on/off all day (~100-150 W)
  * geyser spike in the morning (~2000 W, 6-8 am)
  * cooking peaks at breakfast / dinner (induction, microwave, mixer)
  * AC peaks on a summer afternoon and again in the evening (~1400-1600 W)
  * lights / fans / TV in the evening, low load overnight

Examples
--------
Normal speed (one reading every 5 s, simulated clock = real clock)::

    python simulator/simulator.py --server-url http://127.0.0.1:5000

Fast demo (a whole simulated day in about a minute)::

    python simulator/simulator.py --fast --duration 60

Uses only the Python standard library — no pip installs needed to simulate.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone


def household_load_w(moment: datetime, rng: random.Random) -> float:
    """Instantaneous household load in watts for a simulated time of day."""
    hour = moment.hour + moment.minute / 60.0
    load = 25.0  # standby: router, chargers, fridge electronics, etc.

    # Fridge compressor cycles: roughly 40 min on / 20 min off.
    if (moment.minute % 60) < 40:
        load += rng.uniform(100, 150)

    # Geyser: morning baths, roughly 6:00-8:00.
    if 6.0 <= hour < 8.0 and rng.random() < 0.55:
        load += rng.uniform(1800, 2200)

    # Morning cooking: 7:00-9:00 (induction / kettle / mixer bursts).
    if 7.0 <= hour < 9.0 and rng.random() < 0.35:
        load += rng.uniform(600, 1400)

    # AC: hot UP afternoon, roughly 13:00-17:00 (compressor cycles).
    if 13.0 <= hour < 17.0 and rng.random() < 0.75:
        load += rng.uniform(1300, 1600)

    # AC again + lights/fans/TV in the evening, 19:00-24:00.
    if 19.0 <= hour < 24.0:
        load += rng.uniform(150, 350)  # lights, fans, TV
        if rng.random() < 0.65:
            load += rng.uniform(1300, 1600)  # AC

    # Dinner cooking: 19:00-21:30.
    if 19.0 <= hour < 21.5 and rng.random() < 0.3:
        load += rng.uniform(600, 1200)

    # Iron / washing machine: occasional daytime bursts — these, stacked
    # on top of the AC, are what trip the spike alert in the demo.
    if 10.0 <= hour < 12.0 and rng.random() < 0.08:
        load += rng.uniform(1800, 2400)

    return round(max(load, 5.0), 1)


def build_reading(moment: datetime, energy_kwh: float, rng: random.Random) -> dict:
    power_w = household_load_w(moment, rng)
    voltage_v = round(rng.uniform(225, 238), 1)  # nominal 230 V, real grids wander
    current_a = round(power_w / voltage_v, 3)
    return {
        "timestamp": moment.astimezone(timezone.utc).isoformat(),
        "device_id": "simulator",
        "voltage_v": voltage_v,
        "current_a": current_a,
        "power_w": power_w,
        "energy_kwh": round(energy_kwh, 4),
    }


def post_reading(server_url: str, reading: dict) -> bool:
    url = server_url.rstrip("/") + "/readings"
    data = json.dumps(reading).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        print(f"  ! could not reach server ({exc}); is it running?", file=sys.stderr)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="bijli-watch load simulator")
    parser.add_argument(
        "--server-url", default="http://127.0.0.1:5000",
        help="base URL of the bijli-watch server (default: %(default)s)",
    )
    parser.add_argument(
        "--interval", type=float, default=5.0,
        help="seconds between readings in normal mode (default: %(default)s)",
    )
    parser.add_argument(
        "--duration", type=float, default=0.0,
        help="stop after this many real seconds (default: 0 = run until Ctrl-C)",
    )
    parser.add_argument(
        "--fast", action="store_true",
        help="fast mode: post every 0.2 s while the simulated clock "
             "advances 5 minutes per reading (a full day in ~1 minute)",
    )
    parser.add_argument(
        "--sim-step-seconds", type=float, default=None,
        help="simulated seconds advanced per reading "
             "(default: same as --interval, or 300 in --fast mode)",
    )
    parser.add_argument("--seed", type=int, default=None,
                        help="random seed for reproducible patterns")
    args = parser.parse_args(argv)

    rng = random.Random(args.seed)
    sleep_s = 0.2 if args.fast else args.interval
    sim_step = args.sim_step_seconds
    if sim_step is None:
        sim_step = 300.0 if args.fast else args.interval

    # Start the simulated day at the current local time.
    sim_now = datetime.now().astimezone()
    energy_kwh = 0.0
    started = time.monotonic()
    sent = 0

    print(f"bijli-watch simulator -> {args.server_url}")
    print(f"  sleep={sleep_s}s, simulated step={sim_step:.0f}s per reading"
          f"{', fast mode' if args.fast else ''}. Ctrl-C to stop.")

    try:
        while True:
            reading = build_reading(sim_now, energy_kwh, rng)
            # Energy consumed during this simulated step at the sampled load.
            energy_kwh += reading["power_w"] * (sim_step / 3600.0) / 1000.0
            reading["energy_kwh"] = round(energy_kwh, 4)

            ok = post_reading(args.server_url, reading)
            sent += 1
            print(f"[{sent:4d}] {sim_now.strftime('%H:%M')}  "
                  f"{reading['power_w']:7.1f} W  "
                  f"cumulative {reading['energy_kwh']:.3f} kWh"
                  f"{'' if ok else '  (not delivered)'}")

            sim_now += timedelta(seconds=sim_step)
            if args.duration and (time.monotonic() - started) >= args.duration:
                print(f"Duration reached; sent {sent} readings.")
                return 0
            time.sleep(sleep_s)
    except KeyboardInterrupt:
        print(f"\nStopped; sent {sent} readings.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
