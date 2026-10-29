"""
FreshRoute in-memory state store.

Responsible for: loading the JSON seed files into one source of truth, producing
the full state snapshot sent to the frontend, and recording audit entries,
facility notifications and impact counters (kg, meals, rupee value, CO2e).
NOT responsible for: simulating movement, scoring facilities or handling HTTP.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import db, matcher
from .models import Alert, Facility, Vehicle

DATA_DIR = Path(__file__).resolve().parent / "data"
SIM_START_MINUTES = 8 * 60  # The simulated clock starts at 08:00.

# --- The single source of truth ---------------------------------------------
vehicles: dict[str, Vehicle] = {}
facilities: dict[str, Facility] = {}
routes: dict[str, list[list[float]]] = {}

alerts: list[Alert] = []
notifications: list[dict] = []
audit_log: list[dict] = []

# --- Impact assumptions ------------------------------------------------------
# These are rough, clearly-labelled demo estimates, not audited figures.
# Keeping them in one place means the UI, the CSV export and the tests agree.
MEALS_PER_KG = 2.0          # one meal is treated as 0.5 kg of produce
VALUE_INR_PER_KG = 30.0     # approximate wholesale value of rescued produce
CO2E_KG_PER_KG = 2.5        # emissions avoided per kg of food not wasted
IMPACT_RATES = {
    "meals_per_kg": MEALS_PER_KG,
    "value_inr_per_kg": VALUE_INR_PER_KG,
    "co2e_kg_per_kg": CO2E_KG_PER_KG,
}


def _blank_impact() -> dict[str, float]:
    """A zeroed counter block, used by both module start-up and POST /reset."""
    return {
        "kg_rescued": 0,
        "meals_saved": 0,
        "events_resolved": 0,
        "value_inr": 0,
        "co2e_kg_avoided": 0,
    }


impact: dict[str, float] = _blank_impact()

# --- Simulator bookkeeping ---------------------------------------------------
tick: int = 0
sim_minutes: int = 0
progress_km: dict[str, float] = {}       # distance already driven on the active route
original_speed: dict[str, float] = {}    # speed to restore after a reroute
sim_flags: dict[str, dict] = {}          # active scenario flags per vehicle
active_alerts: dict[str, Alert] = {}     # one active alert per vehicle (de-duplication)
seed_shelf: dict[str, float] = {}        # shelf life at 08:00, restored on a new load
seed_destination: dict[str, str] = {}    # original destination, restored on a new load
delivered_at: dict[str, int] = {}        # tick when the current trip arrived


def _now() -> str:
    """UTC timestamp in ISO format, safe to send straight to JavaScript."""
    return datetime.now(timezone.utc).isoformat()


def _load_json(filename: str) -> dict:
    """Read one seed file from backend/data."""
    with open(DATA_DIR / filename, encoding="utf-8") as handle:
        return json.load(handle)


def reset_state(label: str = "demo") -> None:
    """
    Reload the JSON seed files and clear every log, counter and scenario.
    This is what POST /reset calls, so the demo always starts from the same place.
    """
    global tick, sim_minutes

    vehicles.clear()
    facilities.clear()
    routes.clear()
    progress_km.clear()
    original_speed.clear()
    sim_flags.clear()
    active_alerts.clear()
    seed_shelf.clear()
    seed_destination.clear()
    delivered_at.clear()
    alerts.clear()
    notifications.clear()
    audit_log.clear()

    for raw in _load_json("routes.json")["routes"].items():
        route_id, points = raw
        routes[route_id] = [[float(p[0]), float(p[1])] for p in points]

    for raw in _load_json("facilities.json")["facilities"]:
        facility = Facility(**raw)
        facilities[facility.id] = facility

    for raw in _load_json("vehicles.json")["vehicles"]:
        vehicle = Vehicle(**raw)
        route = routes.get(vehicle.route_id, [])
        vehicle.distance_remaining_km = round(matcher.route_length_km(route), 2)
        vehicle.eta_hours = (
            round(vehicle.distance_remaining_km / vehicle.speed_kmph, 2)
            if vehicle.speed_kmph > 0
            else 999.0
        )
        vehicles[vehicle.id] = vehicle
        progress_km[vehicle.id] = 0.0
        original_speed[vehicle.id] = vehicle.speed_kmph
        seed_shelf[vehicle.id] = vehicle.shelf_life_h
        seed_destination[vehicle.id] = vehicle.destination_id
        sim_flags[vehicle.id] = {
            "reefer_failure": False,
            "delay": False,
            "breakdown": False,
        }

    impact.update(_blank_impact())
    tick = 0
    sim_minutes = 0

    # Keep history in SQLite: a reset starts a fresh demo run but never deletes
    # the ledger, so the analytics panel can show every run of the day.
    db.start_run(label)


def sim_clock() -> str:
    """Convert simulated minutes into a HH:MM wall clock for the header."""
    total = SIM_START_MINUTES + sim_minutes
    return f"{(total // 60) % 24:02d}:{total % 60:02d}"


def get_state() -> dict:
    """
    Build the complete JSON snapshot. Both GET /state and the WebSocket use this.
    Deep copies keep callers from accidentally mutating the live objects.
    """
    return {
        "vehicles": [vehicle.model_dump() for vehicle in vehicles.values()],
        "facilities": [facility.model_dump() for facility in facilities.values()],
        "routes": {route_id: [list(p) for p in points] for route_id, points in routes.items()},
        "alerts": [alert.model_dump() for alert in alerts],
        "notifications": [dict(item) for item in notifications],
        "audit_log": [dict(item) for item in audit_log],
        "impact": dict(impact),
        "impact_rates": dict(IMPACT_RATES),
        "tick": tick,
        "sim_minutes": sim_minutes,
        "sim_clock": sim_clock(),
        "server_time": _now(),
    }


def add_audit(event: str, details: str, vehicle_id: str | None = None) -> dict:
    """Append a traceable decision/event. Newest entries are kept if the log is capped."""
    entry = {
        "id": uuid.uuid4().hex[:8],
        "timestamp": _now(),
        "sim_clock": sim_clock(),
        "event": event,
        "details": details,
        "vehicle_id": vehicle_id,
    }
    audit_log.append(entry)
    if len(audit_log) > 300:
        del audit_log[: len(audit_log) - 300]
    db.log_audit(entry)
    return entry


def add_notification(facility_id: str, message: str, vehicle_id: str | None = None) -> dict:
    """Tell a receiving facility that a load is coming (or another event happened)."""
    facility = facilities.get(facility_id)
    entry = {
        "id": uuid.uuid4().hex[:8],
        "timestamp": _now(),
        "facility_id": facility_id,
        "facility_name": facility.name if facility else facility_id,
        "message": message,
        "vehicle_id": vehicle_id,
    }
    notifications.append(entry)
    if len(notifications) > 100:
        del notifications[: len(notifications) - 100]
    return entry


def record_rescue(
    kg: float,
    vehicle_id: str | None = None,
    allocations: list[tuple[Facility, float]] | None = None,
) -> None:
    """
    Update every impact counter after a successful dispatch and write one row to
    the SQLite ledger.

    Kilograms are the only measured value; meals, rupee value and CO2e are
    derived from the assumptions above and labelled "estimated" in the UI.
    `allocations` pairs each receiving facility with the kilograms it takes, so a
    two-stop rescue is credited to both receivers without double-counting.
    """
    rescued_meals = round(kg * MEALS_PER_KG)
    rescued_value = round(kg * VALUE_INR_PER_KG)
    rescued_co2e = round(kg * CO2E_KG_PER_KG, 1)

    impact["kg_rescued"] = round(impact["kg_rescued"] + kg, 1)
    impact["meals_saved"] = round(impact["kg_rescued"] * MEALS_PER_KG)
    impact["events_resolved"] = int(impact["events_resolved"] + 1)
    impact["value_inr"] = round(impact["kg_rescued"] * VALUE_INR_PER_KG)
    impact["co2e_kg_avoided"] = round(impact["kg_rescued"] * CO2E_KG_PER_KG, 1)

    stops = allocations or []
    db.log_rescue(
        run_id=db.current_run_id(),
        timestamp=_now(),
        sim_clock=sim_clock(),
        vehicle_id=vehicle_id or "unknown",
        kg=kg,
        meals=rescued_meals,
        value_inr=rescued_value,
        co2e_kg=rescued_co2e,
        facility_ids=[facility.id for facility, _kg in stops],
        facility_names=[facility.name for facility, _kg in stops],
        facility_types=[facility.type for facility, _kg in stops],
        facility_kg=[stop_kg for _facility, stop_kg in stops],
    )


def resolve_alert(vehicle_id: str) -> None:
    """Mark a vehicle's active alert resolved (used when a reroute is accepted)."""
    alert = active_alerts.pop(vehicle_id, None)
    if alert:
        alert.resolved = True


def transfer_load(
    broken_vehicle_id: str,
    candidate_vehicle_id: str,
    facility_id: str,
) -> dict:
    """
    Execute a truck-to-truck load transfer.

    The candidate truck drives to the broken truck's position, picks up the
    cargo, and continues to the receiving facility. The broken truck is left
    empty and back in OK status. Impact counters are updated with the rescued
    kilograms and one rescue row is written to SQLite.
    """
    broken = vehicles.get(broken_vehicle_id)
    candidate = vehicles.get(candidate_vehicle_id)
    facility = facilities.get(facility_id)
    if not broken or not candidate or not facility:
        return {"ok": False, "detail": "Vehicle or facility not found"}

    if candidate.status != "OK":
        return {"ok": False, "detail": f"{candidate.name} is not available for transfer"}

    load = broken.load_kg
    if load <= 0:
        return {"ok": False, "detail": f"{broken.name} has no load to transfer"}

    # The candidate reroutes: its current position → broken truck's position → facility.
    destinations = [list(broken.position), list(facility.position)]
    candidate.new_route = matcher.build_rescue_route(list(candidate.position), destinations)
    candidate.destination_id = facility.id
    candidate.reroute_stops = [facility.id]
    candidate.rerouted_to = facility.id
    candidate.status = "REROUTED"
    candidate.speed_kmph = candidate.cruise_kmph
    state.progress_km[candidate.id] = 0.0
    length = matcher.route_length_km(candidate.new_route)
    candidate.distance_remaining_km = round(length, 2)
    candidate.eta_hours = round(length / candidate.speed_kmph, 2) if candidate.speed_kmph > 0 else 999.0

    # Clear the broken truck: load transferred away, back to OK.
    broken.load_kg = 0.0
    broken.status = "OK"
    broken.new_route = None
    broken.distance_remaining_km = 0.0
    broken.eta_hours = 0.0
    broken.sim_flags = {
        "reefer_failure": False,
        "delay": False,
        "breakdown": False,
    }
    if broken.id in active_alerts:
        resolve_alert(broken.id)

    # Notify the receiving facility.
    eta = matcher.eta_hours(candidate, facility)
    add_notification(
        facility.id,
        f"Incoming {load:.0f} kg {broken.produce} (transferred from {broken.name} via {candidate.name}), ETA {eta:.1f} h.",
        candidate.id,
    )

    # Record the rescue and impact.
    add_audit(
        "TRANSFER",
        f"{candidate.name}: {load:.0f} kg {broken.produce} transferred from {broken.name} at {broken.position}, delivered to {facility.name}.",
        candidate.id,
    )
    record_rescue(
        load,
        vehicle_id=candidate.id,
        allocations=[(facility, load)],
    )

    return {
        "ok": True,
        "candidate_id": candidate.id,
        "broken_id": broken.id,
        "facility_id": facility.id,
        "kg_rescued": load,
        "impact": dict(impact),
    }
