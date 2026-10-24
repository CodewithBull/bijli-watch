"""Pure summary / spike logic for bijli-watch.

Everything in here is stdlib-only and side-effect free so it can be unit
tested without a web framework or a running server.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

try:  # package import (python -m server.app / tests)
    from .tariff import estimate_bill, project_monthly_units
except ImportError:  # direct script import (python server/app.py)
    from tariff import estimate_bill, project_monthly_units  # type: ignore

DEFAULT_SPIKE_THRESHOLD_W = 4000.0


def spike_threshold_w() -> float:
    """Configurable spike threshold, env BIJLI_SPIKE_THRESHOLD_W (watts)."""
    raw = os.environ.get("BIJLI_SPIKE_THRESHOLD_W")
    if raw is None:
        return DEFAULT_SPIKE_THRESHOLD_W
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_SPIKE_THRESHOLD_W


def parse_timestamp(value) -> datetime:
    """Parse an ISO-8601 timestamp; naive values are assumed to be UTC."""
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def detect_spikes(readings: list[dict], threshold_w: float | None = None) -> list[dict]:
    """Return alert dicts for every reading above the spike threshold."""
    threshold = spike_threshold_w() if threshold_w is None else float(threshold_w)
    alerts = []
    for reading in readings:
        power = reading.get("power_w")
        if power is not None and float(power) > threshold:
            alerts.append(
                {
                    "timestamp": reading.get("timestamp"),
                    "power_w": float(power),
                    "threshold_w": threshold,
                    "device_id": reading.get("device_id", "default"),
                    "message": (
                        f"Power spike: {float(power):.0f} W exceeded "
                        f"threshold of {threshold:.0f} W"
                    ),
                }
            )
    return alerts


def today_kwh(readings: list[dict], now: datetime | None = None) -> float:
    """Estimate today's consumption in kWh from a list of readings.

    Preferred method: cumulative meter energy (``energy_kwh``) — take the
    difference between the first and last cumulative values recorded today,
    and add the energy implied by the first reading's own sampling interval
    is *not* knowable, so the first-to-last difference is the documented,
    conservative estimate.

    Fallback method (no cumulative values): integrate instantaneous power
    over time between consecutive readings recorded today
    (trapezoidal rule), which is exact enough for a home demo.
    """
    now = now or datetime.now(timezone.utc)
    today = now.date()

    todays: list[tuple[datetime, dict]] = []
    for reading in readings:
        ts_raw = reading.get("timestamp")
        if ts_raw is None:
            continue
        try:
            ts = parse_timestamp(ts_raw)
        except (ValueError, TypeError):
            continue
        if ts.date() == today:
            todays.append((ts, reading))

    if not todays:
        return 0.0

    todays.sort(key=lambda item: item[0])

    cumulative = [
        (ts, float(r["energy_kwh"]))
        for ts, r in todays
        if r.get("energy_kwh") is not None
    ]
    if len(cumulative) >= 2:
        return round(max(0.0, cumulative[-1][1] - cumulative[0][1]), 3)
    if len(cumulative) == 1:
        # Only one cumulative sample today: nothing to diff against yet.
        return 0.0

    # Trapezoidal integration of power_w over time.
    total_kwh = 0.0
    for (t1, r1), (t2, r2) in zip(todays, todays[1:]):
        if r1.get("power_w") is None or r2.get("power_w") is None:
            continue
        hours = (t2 - t1).total_seconds() / 3600.0
        avg_w = (float(r1["power_w"]) + float(r2["power_w"])) / 2.0
        total_kwh += avg_w * hours / 1000.0
    return round(total_kwh, 3)


def summarise(
    readings: list[dict],
    now: datetime | None = None,
    threshold_w: float | None = None,
) -> dict:
    """Build the /summary payload from a list of readings."""
    now = now or datetime.now(timezone.utc)
    threshold = spike_threshold_w() if threshold_w is None else float(threshold_w)

    consumed_today = today_kwh(readings, now=now)
    projected_units = project_monthly_units(consumed_today, day_of_month=now.day)
    # Bill for the projection (what the month looks like at today's pace)
    # and, when today is the only data we have, that IS the headline estimate.
    bill = estimate_bill(projected_units)

    alerts = detect_spikes(readings, threshold_w=threshold)
    latest = readings[-1] if readings else None

    return {
        "reading_count": len(readings),
        "latest_reading": latest,
        "today_kwh": consumed_today,
        "projected_monthly_kwh": projected_units,
        "estimated_monthly_bill_inr": bill["total_inr"],
        "bill_estimate": bill,
        "spike_threshold_w": threshold,
        "spike_alert_count": len(alerts),
        "spike_alerts": alerts[-10:],  # most recent 10, oldest first
        "has_active_spike": bool(
            latest and latest.get("power_w") is not None
            and float(latest["power_w"]) > threshold
        ),
    }
