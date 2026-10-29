"""
Tests for the FreshRoute simulation engine.

Responsible for: proving the tick clock, truck movement, shelf-life drain, the
three disruption scenarios, safe arrival at a destination and the reload that
keeps a delivered truck on the map for the next demo run.
NOT responsible for: risk detection rules (test_risk.py) or HTTP endpoints
(test_api.py).
"""

from __future__ import annotations

import pytest

from backend import matcher, risk, simulator, state

SEED_SHELF_V1 = 9.0


@pytest.fixture(autouse=True)
def clean_state():
    """Every test starts from the same seed data."""
    state.reset_state()
    yield
    state.reset_state()


def test_tick_moves_truck_and_burns_shelf_life():
    vehicle = state.vehicles["V1"]
    start = list(vehicle.position)

    simulator.tick()

    assert state.tick == 1
    assert state.sim_minutes == simulator.SIM_MINUTES_PER_TICK
    assert vehicle.position != start
    assert vehicle.shelf_life_h == pytest.approx(SEED_SHELF_V1 - 0.1, abs=0.01)
    assert state.progress_km["V1"] > 0


def test_reefer_failure_warms_cargo_faster_than_normal():
    healthy = state.vehicles["V2"]
    failing = state.vehicles["V1"]
    simulator.trigger_reefer_failure("V1")

    simulator.tick()

    assert failing.temp_c >= failing.baseline_temp_c + 1.5 - simulator.TEMP_DRIFT_C
    assert abs(healthy.temp_c - healthy.baseline_temp_c) <= 0.6


def test_delay_burns_shelf_life_five_times_faster():
    vehicle = state.vehicles["V5"]
    before = vehicle.shelf_life_h

    simulator.trigger_delay("V5")
    after_penalty = vehicle.shelf_life_h
    simulator.tick()

    assert after_penalty == pytest.approx(before - simulator.DELAY_PENALTY_H, abs=0.01)
    assert vehicle.shelf_life_h == pytest.approx(
        after_penalty - simulator.SHELF_DRAIN_PER_TICK * simulator.DELAY_DRAIN_MULTIPLIER,
        abs=0.01,
    )


def test_breakdown_stops_the_truck():
    vehicle = state.vehicles["V3"]
    start = list(vehicle.position)

    simulator.trigger_breakdown("V3")
    simulator.tick()

    assert vehicle.speed_kmph == 0
    assert vehicle.position == start
    assert vehicle.eta_hours == 999.0


def test_arrival_marks_delivered_and_closes_the_open_alert():
    """A done trip cannot be rescued, so its alert must not linger on the board."""
    vehicle = state.vehicles["V1"]
    vehicle.temp_c = 11.0
    alert = risk.check_vehicle(vehicle)
    assert alert is not None

    # Park the truck one kilometre short of the destination and finish the leg.
    route = state.routes[vehicle.route_id]
    simulator.set_position_at_progress(vehicle, matcher.route_length_km(route) - 1.0)
    simulator.tick()

    assert vehicle.status == "DELIVERED"
    assert alert.resolved is True
    assert "V1" not in state.active_alerts
    assert vehicle.distance_remaining_km == 0
    # Cargo stops changing once the load is at the dock.
    warm = vehicle.temp_c
    simulator.tick()
    assert vehicle.temp_c == warm


def test_delivered_truck_reloads_after_the_dwell():
    vehicle = state.vehicles["V1"]
    route = state.routes[vehicle.route_id]
    simulator.set_position_at_progress(vehicle, matcher.route_length_km(route) - 1.0)
    simulator.tick()
    assert vehicle.status == "DELIVERED"

    for _ in range(simulator.DWELL_TICKS):
        simulator.tick()

    assert vehicle.status == "OK"
    assert vehicle.position == route[0]
    assert vehicle.distance_remaining_km > 0
    assert vehicle.shelf_life_h == pytest.approx(SEED_SHELF_V1, abs=0.01)
    assert vehicle.temp_c == pytest.approx(vehicle.baseline_temp_c, abs=0.01)
    assert state.delivered_at.get("V1") is None
    assert any(entry["event"] == simulator.RELOAD_AUDIT for entry in state.audit_log)


def test_refresh_eta_uses_the_truck_speed():
    vehicle = state.vehicles["V4"]
    simulator.set_position_at_progress(vehicle, 0.0)

    distance = vehicle.distance_remaining_km
    assert distance > 0
    assert vehicle.eta_hours == pytest.approx(distance / vehicle.speed_kmph, abs=0.01)


def test_reset_restores_the_exact_seed_state():
    vehicle = state.vehicles["V1"]
    simulator.trigger_reefer_failure("V1")
    simulator.tick()
    simulator.tick()

    simulator.reset()

    fresh = state.vehicles["V1"]
    assert state.tick == 0
    assert state.sim_minutes == 0
    assert fresh.shelf_life_h == SEED_SHELF_V1
    assert fresh.temp_c == pytest.approx(fresh.baseline_temp_c, abs=0.01)
    assert fresh.position == pytest.approx([13.98, 77.85], abs=1e-6)
    assert state.alerts == []
    assert state.notifications == []
    assert state.impact == {
        "kg_rescued": 0,
        "meals_saved": 0,
        "events_resolved": 0,
        "value_inr": 0,
        "co2e_kg_avoided": 0,
    }
