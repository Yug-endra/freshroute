"""
Tests for the FreshRoute risk engine.

Responsible for: proving temperature breaches, delay breaches, healthy loads and
alert de-duplication / audit behaviour.
NOT responsible for: matcher scoring or HTTP endpoints.
"""

from __future__ import annotations

import pytest

from backend import risk, state


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts from the same seed data."""
    state.reset_state()
    yield
    state.reset_state()


def test_temperature_breach_creates_alert_and_sets_status():
    vehicle = state.vehicles["V1"]
    vehicle.temp_c = 10.5

    alert = risk.check_vehicle(vehicle)

    assert alert is not None
    assert alert.reason == "temperature"
    assert alert.vehicle_id == "V1"
    assert "above the 10 C" in alert.details
    assert vehicle.status == "AT_RISK"


def test_delay_breach_creates_alert():
    vehicle = state.vehicles["V1"]
    vehicle.temp_c = 6.0
    vehicle.shelf_life_h = 1.0
    vehicle.eta_hours = 2.5

    alert = risk.check_vehicle(vehicle)

    assert alert is not None
    assert alert.reason == "delay"
    assert "2.5 h" in alert.details
    assert "1.0 h" in alert.details
    assert vehicle.status == "AT_RISK"


def test_breakdown_breach_is_a_delay_alert():
    vehicle = state.vehicles["V1"]
    vehicle.temp_c = 6.0
    vehicle.speed_kmph = 0.0
    vehicle.eta_hours = 999.0

    alert = risk.check_vehicle(vehicle)

    assert alert is not None
    assert alert.reason == "delay"
    assert "stopped" in alert.details


def test_healthy_vehicle_has_no_alert():
    vehicle = state.vehicles["V1"]  # seed values: 5.2 C, 9 h shelf, ~2.5 h ETA

    alert = risk.check_vehicle(vehicle)

    assert alert is None
    assert vehicle.status == "OK"
    assert len(state.alerts) == 0


def test_one_alert_and_one_audit_entry_per_breach():
    """Repeated tick checks must not spam the alert list or the audit log."""
    vehicle = state.vehicles["V1"]
    vehicle.temp_c = 11.0

    first = risk.check_vehicle(vehicle)
    second = risk.check_vehicle(vehicle)
    third = risk.check_vehicle(vehicle)

    assert first is not None
    assert second is None
    assert third is None
    assert len(state.alerts) == 1
    assert len([entry for entry in state.audit_log if entry["event"] == "BREACH"]) == 1


def test_rerouted_vehicle_is_not_checked_again():
    vehicle = state.vehicles["V1"]
    vehicle.status = "REROUTED"
    vehicle.temp_c = 15.0
    assert risk.check_vehicle(vehicle) is None
