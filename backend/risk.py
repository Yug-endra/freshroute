"""
FreshRoute risk engine.

Responsible for: turning live vehicle readings into alerts, setting AT_RISK,
de-duplicating repeated breaches and writing one audit entry per breach.
NOT responsible for: moving trucks, ranking facilities or rerouting them.
"""

from __future__ import annotations

from . import state
from .models import Alert, Vehicle

TEMP_LIMIT_C = 10.0


def _destination_name(vehicle: Vehicle) -> str:
    """Human-friendly name of where this truck is currently headed."""
    facility = state.facilities.get(vehicle.destination_id)
    return facility.name if facility else vehicle.destination_id


def check_vehicle(vehicle: Vehicle) -> Alert | None:
    """
    Return a new Alert if this truck breaches a safe limit, otherwise None.
    A breach is: cargo above 10 C, or ETA longer than the remaining shelf life.
    """
    # Rerouted and delivered trucks are already resolved (or finished).
    if vehicle.status in ("REROUTED", "DELIVERED"):
        return None

    reason: str | None = None
    if vehicle.temp_c > TEMP_LIMIT_C:
        reason = "temperature"
        details = (
            f"{vehicle.name}: cargo is {vehicle.temp_c:.1f} C, above the "
            f"{TEMP_LIMIT_C:.0f} C safe limit for {vehicle.produce}."
        )
    elif vehicle.speed_kmph <= 0:
        reason = "delay"
        details = (
            f"{vehicle.name} is stopped with {vehicle.shelf_life_h:.1f} h of shelf life "
            f"left and cannot reach {_destination_name(vehicle)}."
        )
    elif vehicle.eta_hours > vehicle.shelf_life_h:
        reason = "delay"
        details = (
            f"{vehicle.name} needs {vehicle.eta_hours:.1f} h to reach "
            f"{_destination_name(vehicle)} but only {vehicle.shelf_life_h:.1f} h of "
            f"shelf life remains."
        )

    if reason is None:
        return None

    # One alert per active breach, not one per tick.
    if vehicle.id in state.active_alerts:
        return None

    import uuid

    alert = Alert(
        id=uuid.uuid4().hex[:8],
        vehicle_id=vehicle.id,
        reason=reason,
        details=details,
        timestamp=state._now(),
    )
    vehicle.status = "AT_RISK"
    state.alerts.append(alert)
    state.active_alerts[vehicle.id] = alert
    state.add_audit("BREACH", details, vehicle.id)
    return alert


def run_risk_checks() -> list[Alert]:
    """Check every truck once. Returns only the alerts created on this pass."""
    fresh: list[Alert] = []
    for vehicle in state.vehicles.values():
        alert = check_vehicle(vehicle)
        if alert:
            fresh.append(alert)
    return fresh
