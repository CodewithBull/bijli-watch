from datetime import datetime, timezone

import pytest

from server.logic import detect_spikes, summarise, today_kwh

NOW = datetime(2026, 5, 15, 18, 0, tzinfo=timezone.utc)  # a hot May evening


def reading(ts, power, energy=None):
    return {
        "timestamp": ts,
        "device_id": "test",
        "voltage_v": 230.0,
        "current_a": round(power / 230.0, 3) if power else 0.0,
        "power_w": power,
        "energy_kwh": energy,
    }


def test_today_kwh_from_cumulative_meter():
    readings = [
        reading("2026-05-15T00:10:00+00:00", 200, energy=100.0),
        reading("2026-05-15T12:00:00+00:00", 1500, energy=105.5),
        reading("2026-05-15T17:00:00+00:00", 300, energy=108.25),
        # yesterday's reading must be ignored
        reading("2026-05-14T23:00:00+00:00", 300, energy=95.0),
    ]
    assert today_kwh(readings, now=NOW) == 8.25


def test_today_kwh_by_power_integration_fallback():
    # Constant 1000 W for exactly one hour -> 1 kWh
    readings = [
        reading("2026-05-15T10:00:00+00:00", 1000),
        reading("2026-05-15T11:00:00+00:00", 1000),
    ]
    assert today_kwh(readings, now=NOW) == 1.0


def test_today_kwh_no_readings_today():
    readings = [reading("2026-05-14T10:00:00+00:00", 500, energy=42.0)]
    assert today_kwh(readings, now=NOW) == 0.0
    assert today_kwh([], now=NOW) == 0.0


def test_detect_spikes_respects_threshold():
    readings = [
        reading("2026-05-15T10:00:00+00:00", 500),
        reading("2026-05-15T13:00:00+00:00", 4500),   # AC + geyser + iron
        reading("2026-05-15T14:00:00+00:00", 3999),
    ]
    alerts = detect_spikes(readings, threshold_w=4000)
    assert len(alerts) == 1
    assert alerts[0]["power_w"] == 4500
    assert "4500" in alerts[0]["message"]


def test_summary_shape_and_spike_flag():
    readings = [
        reading("2026-05-15T00:10:00+00:00", 200, energy=100.0),
        reading("2026-05-15T17:00:00+00:00", 5000, energy=110.0),
    ]
    summary = summarise(readings, now=NOW, threshold_w=4000)
    assert summary["reading_count"] == 2
    assert summary["today_kwh"] == 10.0
    assert summary["projected_monthly_kwh"] == 300.0
    assert summary["estimated_monthly_bill_inr"] > 0
    assert summary["spike_alert_count"] == 1
    assert summary["has_active_spike"] is True  # latest reading is the spike


def test_summary_empty():
    summary = summarise([], now=NOW, threshold_w=4000)
    assert summary["today_kwh"] == 0.0
    assert summary["estimated_monthly_bill_inr"] == 0.0
    assert summary["has_active_spike"] is False
    assert summary["latest_reading"] is None


def test_simulator_load_pattern_is_plausible():
    import random
    from datetime import datetime as dt

    from simulator.simulator import household_load_w

    rng = random.Random(42)
    overnight = [household_load_w(dt(2026, 5, 15, 3, m), rng) for m in range(0, 60, 10)]
    afternoon = [household_load_w(dt(2026, 5, 15, 15, m), rng) for m in range(0, 60, 10)]
    # Everything is a sane household load, and a summer afternoon (AC)
    # averages far above a 3 am standby/fridge-only load.
    assert all(0 < w < 6000 for w in overnight + afternoon)
    assert sum(afternoon) / len(afternoon) > sum(overnight) / len(overnight)
