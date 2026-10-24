"""
UP domestic electricity tariff — indicative slab calculation.

DISCLAIMER
----------
The slabs below are *approximate / indicative* figures modelled on the
UPPCL LMV-1 (domestic) slab structure that has been in use in Uttar Pradesh
in recent years. They are NOT an official tariff order, they change when
UPERC issues a new order, and your actual bill also depends on your
sanctioned load, meter type, urban/rural category, subsidies and arrears.

Use this module to *estimate* a bill and to avoid end-of-month shocks —
never as a legal / billing source of truth. Always cross-check with the
current UPPCL tariff order or your actual electricity bill.
"""

from __future__ import annotations

# (slab_upper_limit_kwh, rate_in_inr_per_kwh)
# The last slab has no upper limit (None).
SLABS: list[tuple[float | None, float]] = [
    (100.0, 3.50),   # first 100 units
    (150.0, 4.00),   # next 50 units  (101-150)
    (300.0, 5.00),   # next 150 units (151-300)
    (500.0, 5.50),   # next 200 units (301-500)
    (None, 6.00),    # everything above 500 units
]

# Indicative fixed charge for a typical 1-2 kW domestic connection (INR/month).
FIXED_CHARGE_INR = 110.0

# Electricity duty, applied on the energy charge (indicative).
DUTY_RATE = 0.05  # 5%


def slab_breakdown(units_kwh: float) -> list[dict]:
    """Return per-slab consumption and charge for ``units_kwh``.

    Each entry: {"from_unit", "to_unit" (None = no cap), "units",
                 "rate_inr_per_kwh", "amount_inr"}
    """
    if units_kwh < 0:
        raise ValueError("units_kwh cannot be negative")

    breakdown: list[dict] = []
    remaining = float(units_kwh)
    lower = 0.0

    for upper, rate in SLABS:
        if remaining <= 0:
            break
        slab_size = float("inf") if upper is None else upper - lower
        used = min(remaining, slab_size)
        breakdown.append(
            {
                "from_unit": lower,
                "to_unit": upper,
                "units": round(used, 3),
                "rate_inr_per_kwh": rate,
                "amount_inr": round(used * rate, 2),
            }
        )
        remaining -= used
        if upper is not None:
            lower = upper

    return breakdown


def estimate_bill(units_kwh: float) -> dict:
    """Estimate a monthly domestic bill for ``units_kwh`` consumed.

    Returns a dict with the breakdown, energy charge, fixed charge,
    duty, and the rounded total. Zero consumption -> zero bill
    (we do not apply the fixed charge when nothing was recorded,
    which keeps demos/tests intuitive; your DISCOM will still charge it).
    """
    if units_kwh < 0:
        raise ValueError("units_kwh cannot be negative")

    if units_kwh == 0:
        return {
            "units_kwh": 0.0,
            "breakdown": [],
            "energy_charge_inr": 0.0,
            "fixed_charge_inr": 0.0,
            "duty_inr": 0.0,
            "total_inr": 0.0,
            "indicative": True,
        }

    breakdown = slab_breakdown(units_kwh)
    energy_charge = round(sum(row["amount_inr"] for row in breakdown), 2)
    duty = round(energy_charge * DUTY_RATE, 2)
    total = round(energy_charge + FIXED_CHARGE_INR + duty, 2)

    return {
        "units_kwh": round(float(units_kwh), 3),
        "breakdown": breakdown,
        "energy_charge_inr": energy_charge,
        "fixed_charge_inr": FIXED_CHARGE_INR,
        "duty_inr": duty,
        "total_inr": total,
        "indicative": True,
    }


def project_monthly_units(today_kwh: float, day_of_month: int) -> float:
    """Crude monthly projection: today's usage scaled to a 30-day month.

    This is intentionally simple and documented as such — a single day is
    not very predictive. It exists so the dashboard can show a
    'if every day looked like today' bill estimate.
    """
    if day_of_month < 1 or day_of_month > 31:
        raise ValueError("day_of_month must be between 1 and 31")
    if today_kwh < 0:
        raise ValueError("today_kwh cannot be negative")
    return round(float(today_kwh) * 30, 3)
