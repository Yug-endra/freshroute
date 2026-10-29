"""
FreshRoute simulation engine.

Responsible for: advancing trucks along pre-computed polylines, drifting cargo
temperature, burning shelf life, applying the three disruption scenarios and
sending a delivered truck out again with a fresh load.
NOT responsible for: deciding when a breach is an alert (risk.py), scoring
facilities (matcher.py) or sending anything to the browser (main.py).
"""

from __future__ import annotations

import random

from . import matcher, state
from .models import Vehicle

TICK_SECONDS = 2.0                 # real seconds between ticks
SIM_MINUTES_PER_TICK = 6           # simulated minutes per tick
SHELF_DRAIN_PER_TICK = 0.1         # hours lost per tick in normal conditions
DELAY_DRAIN_MULTIPLIER = 5.0       # traffic delay burns shelf life 5x faster
TEMP_DRIFT_C = 0.2                 # normal temperature wobble, +/- this many degrees
REEFER_WARMUP_PER_TICK = 1.5       # degrees gained per tick after a reefer failure
DELAY_SPEED_FACTOR = 0.4           # heavy congestion leaves the truck at 40% speed
DELAY_PENALTY_H = 3.0              # hours lost sitting in the reported traffic hold
MIN_SHELF_LIFE_H = 0.2             # never let shelf life go negative in the model
ARRIVAL_AUDIT = "DELIVERED"
DWELL_TICKS = 3                    # ticks a delivered truck waits before reloading
RELOAD_AUDIT = "LOADED"


def _active_route(vehicle: Vehicle) -> list[list[float]]:
    """The route the truck is currently following: the rerouted one if present."""
    if vehicle.new_route:
        return vehicle.new_route
    return state.routes.get(vehicle.route_id, [])


def _refresh_eta(vehicle: Vehicle) -> None:
    """Recompute remaining distance and ETA from the truck's progress on its route."""
    route = _active_route(vehicle)
    progress = state.progress_km.get(vehicle.id, 0.0)
    remaining = matcher.remaining_route_km(route, progress)
    vehicle.distance_remaining_km = round(remaining, 2)
    # A stopped truck cannot arrive; use a large finite number so JSON stays clean.
    vehicle.eta_hours = round(remaining / vehicle.speed_kmph, 2) if vehicle.speed_kmph > 0 else 999.0


def _advance(vehicle: Vehicle) -> None:
    """Move one truck forward by one tick's worth of distance."""
    if vehicle.status == "DELIVERED":
        return

    route = _active_route(vehicle)
    if not route:
        return

    length = matcher.route_length_km(route)
    progress = state.progress_km.get(vehicle.id, 0.0)
    progress += vehicle.speed_kmph * (SIM_MINUTES_PER_TICK / 60.0)
    progress = min(progress, length)
    state.progress_km[vehicle.id] = progress
    vehicle.position = matcher.interpolate_position(route, progress)

    if progress >= length:
        # The truck has reached its (possibly new) destination.
        vehicle.position = list(route[-1])
        vehicle.status = "DELIVERED"
        target = state.facilities.get(vehicle.destination_id)
        where = target.name if target else vehicle.destination_id
        state.add_audit(
            ARRIVAL_AUDIT,
            f"{vehicle.name} reached {where} with {vehicle.load_kg:.0f} kg of {vehicle.produce}.",
            vehicle.id,
        )
        state.delivered_at[vehicle.id] = state.tick
        # A finished trip can no longer be rescued, so close any alert still open.
        if vehicle.id in state.active_alerts:
            state.resolve_alert(vehicle.id)
            state.add_audit(
                "ALERT_CLOSED",
                f"{vehicle.name} already reached {where}; open alert closed without a reroute.",
                vehicle.id,
            )

    _refresh_eta(vehicle)


def _start_new_load(vehicle: Vehicle) -> None:
    """
    The truck has unloaded and is back on the road with a fresh shipment.
    This keeps the live map moving for however long the demo runs, while
    /reset still restores the exact 08:00 seed state.
    """
    route = state.routes.get(vehicle.route_id, [])
    vehicle.status = "OK"
    vehicle.new_route = None
    vehicle.original_destination_id = None
    vehicle.rerouted_to = None
    vehicle.destination_id = state.seed_destination.get(vehicle.id, vehicle.destination_id)
    vehicle.speed_kmph = state.original_speed.get(vehicle.id, 40.0)
    vehicle.temp_c = vehicle.baseline_temp_c
    vehicle.shelf_life_h = state.seed_shelf.get(vehicle.id, vehicle.shelf_life_h)
    state.progress_km[vehicle.id] = 0.0
    if route:
        vehicle.position = list(route[0])
    state.sim_flags[vehicle.id] = {
        "reefer_failure": False,
        "delay": False,
        "breakdown": False,
    }
    state.delivered_at.pop(vehicle.id, None)
    _refresh_eta(vehicle)
    state.add_audit(
        RELOAD_AUDIT,
        f"{vehicle.name} loaded a fresh {vehicle.load_kg:.0f} kg of {vehicle.produce}.",
        vehicle.id,
    )


def _update_cargo(vehicle: Vehicle) -> None:
    """Apply one tick of shelf-life loss and temperature change."""
    flags = state.sim_flags.get(vehicle.id, {})
    # The traffic hold burns shelf life five times faster, but only until the
    # breach is flagged: after that the truck is out of the hold, is still
    # crawling, and its shelf life drips at the normal rate while the dispatcher
    # reads the rescue options.
    in_hold = flags.get("delay") and vehicle.id not in state.active_alerts
    multiplier = DELAY_DRAIN_MULTIPLIER if in_hold else 1.0
    vehicle.shelf_life_h = round(
        max(MIN_SHELF_LIFE_H, vehicle.shelf_life_h - SHELF_DRAIN_PER_TICK * multiplier), 2
    )

    drift = random.uniform(-TEMP_DRIFT_C, TEMP_DRIFT_C)
    if flags.get("reefer_failure"):
        # The cooling unit is failing: cargo warms up every tick.
        vehicle.temp_c = round(vehicle.temp_c + REEFER_WARMUP_PER_TICK + drift, 2)
    else:
        # Otherwise the cargo wobbles gently around its baseline temperature.
        offset = (vehicle.temp_c - vehicle.baseline_temp_c) + drift
        offset = max(-0.6, min(0.6, offset))
        vehicle.temp_c = round(vehicle.baseline_temp_c + offset, 2)


def tick() -> None:
    """Advance the whole simulated world by exactly one tick (6 simulated minutes)."""
    for vehicle in state.vehicles.values():
        if vehicle.status == "DELIVERED":
            # Unloading at the dock: no movement, no cargo change. After a short
            # dwell the truck takes on a fresh load so the map never goes dead.
            arrived = state.delivered_at.get(vehicle.id, state.tick)
            if state.tick - arrived >= DWELL_TICKS:
                _start_new_load(vehicle)
            continue
        _advance(vehicle)
        if vehicle.status != "DELIVERED":
            _update_cargo(vehicle)

    state.tick += 1
    state.sim_minutes += SIM_MINUTES_PER_TICK


def trigger_reefer_failure(vehicle_id: str) -> Vehicle:
    """Cooling fails: cargo temperature climbs 1.5 degrees every tick."""
    vehicle = state.vehicles[vehicle_id]
    state.sim_flags[vehicle_id]["reefer_failure"] = True
    return vehicle


def trigger_delay(vehicle_id: str) -> Vehicle:
    """
    Heavy traffic: the truck sits in a multi-hour hold, then crawls at 40% speed
    while its remaining shelf life drains five times faster than normal.
    The one-time hold is what makes the current destination unreachable quickly.
    """
    vehicle = state.vehicles[vehicle_id]
    flags = state.sim_flags[vehicle_id]
    if not flags["delay"]:
        vehicle.shelf_life_h = round(
            max(MIN_SHELF_LIFE_H, vehicle.shelf_life_h - DELAY_PENALTY_H), 2
        )
        vehicle.speed_kmph = round(vehicle.speed_kmph * DELAY_SPEED_FACTOR, 1)
        flags["delay"] = True
        _refresh_eta(vehicle)
    return vehicle


def trigger_breakdown(vehicle_id: str) -> Vehicle:
    """The truck stops where it is; the current trip can never finish."""
    vehicle = state.vehicles[vehicle_id]
    vehicle.speed_kmph = 0.0
    state.sim_flags[vehicle_id]["breakdown"] = True
    _refresh_eta(vehicle)
    return vehicle


def clear_scenarios(vehicle_id: str) -> None:
    """
    Put a truck back to healthy running order. Called after a reroute, where the
    load is handed to a sound rescue vehicle (or the fault is fixed).
    """
    vehicle = state.vehicles.get(vehicle_id)
    if not vehicle:
        return
    vehicle.speed_kmph = state.original_speed.get(vehicle_id, 40.0)
    vehicle.temp_c = vehicle.baseline_temp_c
    state.sim_flags[vehicle_id] = {
        "reefer_failure": False,
        "delay": False,
        "breakdown": False,
    }


def reset() -> None:
    """Restore the whole demo to its seed state."""
    state.reset_state()


def set_position_at_progress(vehicle: Vehicle, progress_km: float) -> None:
    """Test/demo helper: place a truck at a known distance along its route."""
    state.progress_km[vehicle.id] = progress_km
    vehicle.position = matcher.interpolate_position(_active_route(vehicle), progress_km)
    _refresh_eta(vehicle)
