"""
Tests for the FreshRoute matching engine.

Responsible for: proving Haversine maths, feasibility filters, ranking order and
the split-load fallback behave exactly as the pitch deck claims.
NOT responsible for: HTTP endpoints or the simulator.
"""

from __future__ import annotations

import pytest

from backend import matcher
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


def test_haversine_known_distance():
    """Bengaluru to Chennai is about 290 km as the crow flies."""
    distance = matcher.haversine_km(12.9716, 77.5946, 13.0827, 80.2707)
    assert distance == pytest.approx(290, abs=5)


def test_haversine_short_distance():
    """One hundredth of a degree of longitude near Bengaluru is about 1.09 km."""
    distance = matcher.haversine_km(12.9716, 77.5946, 12.9716, 77.6046)
    assert distance == pytest.approx(1.09, abs=0.05)


def test_infeasible_when_capacity_too_small():
    vehicle = make_vehicle(load_kg=1800)
    small = make_facility("F1", "cold_storage", 12.98, 77.59, free_kg=500)
    assert matcher.is_feasible(vehicle, small) is False


def test_infeasible_when_eta_exceeds_shelf_life():
    vehicle = make_vehicle(load_kg=500, shelf_life_h=1.0)
    far = make_facility("F1", "cold_storage", 13.97, 77.59, free_kg=5000)
    assert matcher.eta_hours(vehicle, far) > vehicle.shelf_life_h
    assert matcher.is_feasible(vehicle, far) is False


def test_feasible_when_room_and_time_exist():
    vehicle = make_vehicle(load_kg=500, shelf_life_h=10.0)
    near = make_facility("F1", "kitchen", 12.98, 77.59, free_kg=900)
    assert matcher.is_feasible(vehicle, near) is True


def test_ranking_prefers_fast_produce_to_kitchen():
    """A close kitchen should outrank a slightly farther cold storage for fast produce."""
    vehicle = make_vehicle(load_kg=1000, shelf_life_h=10.0)
    facilities = [
        make_facility("KITCHEN", "kitchen", 12.98, 77.59, free_kg=1200),
        make_facility("COLD", "cold_storage", 12.99, 77.59, free_kg=5000),
        make_facility("SHELTER", "shelter", 13.0, 77.59, free_kg=1100),
    ]

    ranked = matcher.recommend(vehicle, facilities)

    assert [rec.facility_id for rec in ranked] == ["KITCHEN", "SHELTER", "COLD"]
    assert ranked[0].total_score >= ranked[1].total_score >= ranked[2].total_score
    assert all(0 <= rec.total_score <= 1 for rec in ranked)


def test_score_components_are_bounded_and_weighted():
    vehicle = make_vehicle(load_kg=1000, shelf_life_h=10.0)
    facility = make_facility("F1", "kitchen", 12.98, 77.59, free_kg=1100)
    result = matcher.score_facility(vehicle, facility, max_distance=10.0)
    parts = result["components"]

    assert all(0 <= value <= 1 for value in parts.values())
    expected = (
        matcher.W_PROXIMITY * parts["proximity"]
        + matcher.W_CAPACITY * parts["capacity_fit"]
        + matcher.W_COLD_CHAIN * parts["cold_chain_match"]
        + matcher.W_TIME_MARGIN * parts["time_margin"]
    )
    assert result["total"] == pytest.approx(expected, abs=0.002)


def test_facility_at_same_point_gets_full_proximity():
    vehicle = make_vehicle()
    facility = make_facility("F1", "kitchen", 12.97, 77.59, free_kg=2000)
    result = matcher.score_facility(vehicle, facility, max_distance=10.0)
    assert result["components"]["proximity"] == pytest.approx(1.0)


def test_recommend_hides_infeasible_candidates():
    vehicle = make_vehicle(load_kg=1800, shelf_life_h=2.0)
    facilities = [
        make_facility("SMALL", "kitchen", 12.98, 77.59, free_kg=500),
        make_facility("FAR", "kitchen", 14.5, 77.59, free_kg=5000),
        make_facility("GOOD", "shelter", 12.99, 77.59, free_kg=2000),
    ]
    ranked = matcher.recommend(vehicle, facilities)
    assert [rec.facility_id for rec in ranked] == ["GOOD"]


def test_split_plan_covers_load_with_two_stops():
    """When no single facility fits 2000 kg, two kitchens of 1200 kg each must."""
    vehicle = make_vehicle(load_kg=2000, shelf_life_h=10.0)
    facilities = [
        make_facility("A", "kitchen", 12.98, 77.59, free_kg=1200),
        make_facility("B", "kitchen", 12.99, 77.59, free_kg=1200),
    ]

    assert matcher.recommend(vehicle, facilities) == []
    plan = matcher.split_plan(vehicle, facilities)

    assert plan is not None
    assert len(plan.stops) == 2
    assert plan.total_kg == 2000
    assert sum(stop.kg_allocated for stop in plan.stops) == 2000
    assert {stop.facility_id for stop in plan.stops} == {"A", "B"}


def test_split_plan_returns_none_when_even_two_stops_cannot_help():
    vehicle = make_vehicle(load_kg=5000, shelf_life_h=10.0)
    facilities = [
        make_facility("A", "kitchen", 12.98, 77.59, free_kg=1000),
        make_facility("B", "kitchen", 12.99, 77.59, free_kg=1000),
    ]
    assert matcher.split_plan(vehicle, facilities) is None


def test_nearest_option_explains_a_capacity_shortfall():
    vehicle = make_vehicle(load_kg=1800)
    nearest = make_facility("NEAR", "kitchen", 12.975, 77.59, free_kg=400)
    farther = make_facility("FAR", "cold_storage", 13.2, 77.59, free_kg=5000)

    option = matcher.nearest_option(vehicle, [nearest, farther])

    assert option.facility_id == "NEAR"
    assert option.feasible is False
    assert "free" in option.reason


def test_nearest_option_explains_a_time_shortfall():
    vehicle = make_vehicle(load_kg=500, shelf_life_h=0.2)
    nearest = make_facility("NEAR", "kitchen", 13.97, 77.59, free_kg=5000)

    option = matcher.nearest_option(vehicle, [nearest])

    assert option.feasible is False
    assert "shelf life" in option.reason


def test_nearest_option_explains_why_a_feasible_nearest_lost():
    vehicle = make_vehicle(load_kg=1000, shelf_life_h=10.0)
    facilities = [
        make_facility("NEAR", "cold_storage", 12.975, 77.59, free_kg=5000),
        make_facility("TOP", "kitchen", 12.978, 77.59, free_kg=1100),
    ]

    ranked = matcher.recommend(vehicle, facilities)
    option = matcher.nearest_option(vehicle, facilities, ranked[0])

    assert ranked[0].facility_id == "TOP"
    assert option.facility_id == "NEAR"
    assert option.feasible is True
    assert "top pick wins on" in option.reason
