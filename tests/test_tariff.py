import pytest

from server.tariff import (
    DUTY_RATE,
    FIXED_CHARGE_INR,
    estimate_bill,
    project_monthly_units,
    slab_breakdown,
)


def test_zero_units_zero_bill():
    bill = estimate_bill(0)
    assert bill["total_inr"] == 0.0
    assert bill["breakdown"] == []


def test_negative_units_rejected():
    with pytest.raises(ValueError):
        estimate_bill(-5)
    with pytest.raises(ValueError):
        slab_breakdown(-1)


def test_first_slab_only():
    # 50 units, all at the first-slab rate of Rs 3.50
    breakdown = slab_breakdown(50)
    assert len(breakdown) == 1
    assert breakdown[0]["units"] == 50
    assert breakdown[0]["amount_inr"] == 175.0


def test_slab_progression_200_units():
    # 100 @3.50 = 350, 50 @4.00 = 200, 50 @5.00 = 250  -> 800
    breakdown = slab_breakdown(200)
    assert [row["units"] for row in breakdown] == [100, 50, 50]
    assert sum(row["amount_inr"] for row in breakdown) == 800.0


def test_bill_includes_fixed_charge_and_duty():
    bill = estimate_bill(200)
    assert bill["energy_charge_inr"] == 800.0
    assert bill["fixed_charge_inr"] == FIXED_CHARGE_INR
    assert bill["duty_inr"] == round(800.0 * DUTY_RATE, 2)
    assert bill["total_inr"] == round(800.0 + FIXED_CHARGE_INR + bill["duty_inr"], 2)
    assert bill["total_inr"] == 950.0  # 800 + 110 + 40


def test_large_consumption_reaches_top_slab():
    breakdown = slab_breakdown(600)
    # 100 + 50 + 150 + 200 = 500 in capped slabs, 100 left in the open slab
    assert breakdown[-1]["to_unit"] is None
    assert breakdown[-1]["units"] == 100
    assert sum(row["units"] for row in breakdown) == 600


def test_projection():
    assert project_monthly_units(10, day_of_month=15) == 300
    with pytest.raises(ValueError):
        project_monthly_units(10, day_of_month=0)
