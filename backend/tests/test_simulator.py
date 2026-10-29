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
from backend.models import Facility, Vehicle


def make_vehicle(**overrides) -> Vehicle:
    base = dict(
        id="VX",
        name="Test Truck",
        produce="tomato",
        produce_class="fast",
        load_kg=1000,
        temp_c=5.0,
        shelf_life_h=10.0,
        speed_kmph=40.0,
        cruise_kmph=40.0,
        route_id="R1",
        destination_id="F1",
        position=[12.97, 77.59],
        status="OK",
        baseline_temp_c=5.0,
    )
    base.update(overrides)
    return Vehicle(**base)


def make_facility(fid: str, ftype: str, lat: float, lng: float, free_kg: float) -> Facility:
    return Facility(
        id=fid,
        name=f"Facility {fid}",
        type=ftype,
        position=[lat, lng],
        capacity_kg=free_kg * 2,
        free_kg=free_kg,
        contact="test",
    )


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


def test_delay_trigger_is_idempotent():
    """Calling trigger_delay twice must not double-penalise shelf life or slow the truck further."""
    vehicle = state.vehicles["V5"]
    before_shelf = vehicle.shelf_life_h
    before_speed = vehicle.speed_kmph

    simulator.trigger_delay("V5")
    after_first_shelf = vehicle.shelf_life_h
    after_first_speed = vehicle.speed_kmph

    simulator.trigger_delay("V5")  # second call must be a no-op

    assert vehicle.shelf_life_h == pytest.approx(after_first_shelf, abs=0.001), (
        "Second trigger_delay must not subtract the penalty a second time"
    )
    assert vehicle.speed_kmph == pytest.approx(after_first_speed, abs=0.001), (
        "Second trigger_delay must not slow the truck further"
    )
    # Sanity: the first call DID change things
    assert after_first_shelf < before_shelf
    assert after_first_speed < before_speed


def test_split_plan_rejects_second_leg_when_shelf_life_expires_en_route():
    """
    If getting to stop 1 burns all the shelf life, stop 2 must be rejected even
    though it is spatially reachable, because the cargo would not survive the
    onward leg.
    """
    # Place the truck 60 km from stop 1 at 40 km/h → 1.5 h ETA to stop 1.
    # Shelf life is 1.6 h, so after stop 1 only 0.1 h remains.
    # Stop 2 is 20 km from stop 1 → 0.5 h ETA from there → infeasible.
    vehicle = make_vehicle(
        load_kg=2000,
        shelf_life_h=1.6,
        speed_kmph=40.0,
        cruise_kmph=40.0,
        position=[12.97, 77.59],
    )
    # Stop 1: ~60 km NE (≈ 0.54° lat), can take 1200 kg
    stop1 = make_facility("S1", "kitchen", 13.51, 77.59, free_kg=1200)
    # Stop 2: ~20 km north of stop 1, can take 800 kg
    stop2 = make_facility("S2", "kitchen", 13.69, 77.59, free_kg=800)

    # The single-facility path fails (neither fits 2000 kg alone).
    assert matcher.recommend(vehicle, [stop1, stop2]) == []
    # The two-stop plan must also fail because the second leg is undeliverable.
    plan = matcher.split_plan(vehicle, [stop1, stop2])
    assert plan is None, "split_plan must reject a pair where cargo expires before stop 2"
