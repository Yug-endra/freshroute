"""
FreshRoute FastAPI application.

Responsible for: HTTP/WebSocket wiring, starting the simulator loop, broadcasting
full state to every connected client, and turning dispatcher actions into state
changes (reroute, scenario trigger, reset).
NOT responsible for: scoring facilities, detecting risk or simulating movement —
those live in matcher.py, risk.py and simulator.py.
"""

from __future__ import annotations

import asyncio
import contextlib
import csv
import io
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, matcher, risk, simulator, state
from .models import (
    RecommendationResponse,
    RerouteRequest,
    TransferOption,
)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

# Scenario name -> simulator function.
SCENARIOS = {
    "reefer_failure": simulator.trigger_reefer_failure,
    "delay": simulator.trigger_delay,
    "breakdown": simulator.trigger_breakdown,
}

SCENARIO_LABEL = {
    "reefer_failure": "Reefer failure",
    "delay": "Traffic delay",
    "breakdown": "Truck breakdown",
}

# Every open /events socket. The tick loop fans the same snapshot out to all.
_clients: set[WebSocket] = set()

# Last time a browser asked for state (socket or poll). The clock pauses when
# nobody is watching, so a judge never opens a page where every truck is done.
_last_activity: float = 0.0
WATCH_WINDOW_SECONDS = 12.0


def _mark_activity() -> None:
    """Remember that a dashboard is currently watching the simulation."""
    global _last_activity
    _last_activity = time.monotonic()


async def broadcast() -> None:
    """Send the current full state to every connected browser."""
    if not _clients:
        return
    payload = json.dumps(state.get_state())
    dead: list[WebSocket] = []
    for socket in list(_clients):
        try:
            await socket.send_text(payload)
        except Exception:
            dead.append(socket)
    for socket in dead:
        _clients.discard(socket)


async def simulation_loop() -> None:
    """
    One tick every 2 seconds: move trucks, check risk, push the new state.
    The clock pauses while no dashboard is watching, so a judge never opens a
    page where every truck has already delivered. Polling-only clients count as
    watching too, which keeps the GET /state fallback live.
    """
    while True:
        await asyncio.sleep(simulator.TICK_SECONDS)
        watching = bool(_clients) or (time.monotonic() - _last_activity) < WATCH_WINDOW_SECONDS
        if not watching:
            continue
        simulator.tick()
        risk.run_risk_checks()
        await broadcast()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load seed data and run the simulator for the lifetime of the server."""
    db.init()
    state.reset_state()
    state.add_audit("SYSTEM", "Simulation started with Bengaluru seed data.")
    task = asyncio.create_task(simulation_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title="FreshRoute API",
    version="1.0.0",
    description="Perishable produce rerouting and surplus food rescue (simulated).",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Small validation helpers (no business logic) ---------------------------
def _require_vehicle(vehicle_id: str):
    vehicle = state.vehicles.get(vehicle_id)
    if not vehicle:
        raise HTTPException(status_code=404, detail=f"Vehicle '{vehicle_id}' not found")
    return vehicle


def _require_facility(facility_id: str):
    facility = state.facilities.get(facility_id)
    if not facility:
        raise HTTPException(status_code=404, detail=f"Facility '{facility_id}' not found")
    return facility


# --- Read endpoints ---------------------------------------------------------
@app.get("/state")
async def get_state():
    """The whole world in one JSON document."""
    _mark_activity()
    return state.get_state()


@app.get("/health")
async def health():
    """Liveness probe: tick, client count, sim clock and active alert count."""
    active_alerts = sum(1 for a in state.alerts if not a.resolved)
    return {
        "status": "ok",
        "tick": state.tick,
        "clients": len(_clients),
        "sim_clock": state.sim_clock(),
        "active_alerts": active_alerts,
    }


@app.get("/analytics")
async def get_analytics():
    """
    Cross-run ledger from SQLite: all-time impact, the current run, recent
    rescues and the busiest facilities. Powers the Impact ledger panel.
    """
    data = db.analytics()
    data["sim_clock"] = state.sim_clock()
    data["rates"] = dict(state.IMPACT_RATES)
    return data


@app.get("/audit.csv")
async def download_audit_csv():
    """Download every persisted audit entry as a CSV (Excel-friendly, with BOM)."""
    rows = db.audit_rows()
    if not rows:
        # If SQLite is unavailable, still let the dispatcher export this run.
        rows = [
            {
                "run_id": "",
                "sim_clock": entry.get("sim_clock"),
                "timestamp": entry.get("timestamp"),
                "event": entry.get("event"),
                "vehicle_id": entry.get("vehicle_id"),
                "details": entry.get("details"),
            }
            for entry in state.audit_log
        ]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["run", "sim_clock", "timestamp_utc", "event", "vehicle_id", "details"])
    for row in rows:
        writer.writerow(
            [
                row.get("run_id", ""),
                row.get("sim_clock") or "",
                row.get("timestamp") or "",
                row.get("event") or "",
                row.get("vehicle_id") or "",
                row.get("details") or "",
            ]
        )

    filename = f"freshroute-audit-{state.sim_clock().replace(':', '')}.csv"
    return Response(
        content="\ufeff" + buffer.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@app.get("/recommend/{vehicle_id}", response_model=RecommendationResponse)
async def get_recommendations(vehicle_id: str):
    """Top three feasible facilities, or a two-stop split plan if none fits."""
    vehicle = _require_vehicle(vehicle_id)
    facilities = list(state.facilities.values())

    ranked = matcher.recommend(vehicle, facilities)
    if ranked:
        response = RecommendationResponse(
            vehicle_id=vehicle_id,
            mode="single",
            recommendations=ranked,
            split_plan=None,
            nearest=matcher.nearest_option(vehicle, facilities, ranked[0]),
        )
        best = ranked[0]
        details = (
            f"{len(ranked)} feasible option(s) for {vehicle.name}; "
            f"best is {best.facility_name} at {best.total_score:.3f}."
        )
    else:
        plan = matcher.split_plan(vehicle, facilities)
        if plan is None:
            # Diagnose why no rescue is possible so the dispatcher gets
            # an actionable next step instead of a dead-end error.
            too_far = [
                f
                for f in facilities
                if matcher.eta_hours(vehicle, f) >= vehicle.shelf_life_h
            ]
            too_small = [
                f
                for f in facilities
                if f.free_kg < vehicle.load_kg
            ]
            usable = [
                f
                for f in facilities
                if f.free_kg > 0
                and matcher.eta_hours(vehicle, f) < vehicle.shelf_life_h
            ]
            if len(usable) < 2:
                blocked_reason = (
                    f"Only {len(usable)} facility(ies) can take any of this "
                    f"{vehicle.load_kg:.0f} kg load before its shelf life runs "
                    f"out; a two-stop rescue needs at least two."
                )
            elif too_small and not too_far:
                blocked_reason = (
                    f"No single facility has enough free space for the "
                    f"{vehicle.load_kg:.0f} kg load, and no two facilities "
                    f"together can cover it before shelf life expires."
                )
            elif too_far and not too_small:
                blocked_reason = (
                    f"Facilities have space, but none can be reached before "
                    f"the {vehicle.shelf_life_h:.1f} h shelf life expires."
                )
            else:
                blocked_reason = (
                    f"No facility can take this {vehicle.load_kg:.0f} kg load "
                    f"before its shelf life runs out."
                )
            response = RecommendationResponse(
                vehicle_id=vehicle_id,
                mode="none",
                recommendations=[],
                split_plan=None,
                nearest=matcher.nearest_option(vehicle, facilities),
                blocked_reason=blocked_reason,
                transfer_options=matcher.transfer_options(
                    vehicle, list(state.vehicles.values()), facilities
                ),
            )
            details = f"No rescue options for {vehicle.name}: {blocked_reason}"
        else:
            response = RecommendationResponse(
                vehicle_id=vehicle_id,
                mode="split",
                recommendations=[],
                split_plan=plan,
                nearest=matcher.nearest_option(vehicle, facilities, plan.stops[0]),
            )
            details = f"No single facility fits; two-stop plan proposed for {vehicle.name}."

    state.add_audit("RECOMMEND", details, vehicle_id)
    return response


# --- Dispatcher commands ----------------------------------------------------
@app.post("/simulate/{scenario}")
async def simulate(
    scenario: str,
    vehicle_id: str = Query(..., description="Vehicle to disrupt"),
):
    """Trigger a disruption and immediately check whether it causes a breach."""
    scenario = scenario.lower()
    if scenario not in SCENARIOS:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown scenario '{scenario}'. Use reefer_failure, delay or breakdown.",
        )
    vehicle = _require_vehicle(vehicle_id)
    if vehicle.status == "DELIVERED":
        raise HTTPException(status_code=400, detail="This vehicle has already delivered its load")

    SCENARIOS[scenario](vehicle_id)
    state.add_audit(
        "SCENARIO",
        f"{SCENARIO_LABEL[scenario]} triggered on {vehicle.name} ({vehicle.produce}).",
        vehicle_id,
    )
    fresh_alerts = risk.run_risk_checks()
    await broadcast()
    return {
        "ok": True,
        "scenario": scenario,
        "vehicle_id": vehicle_id,
        "status": vehicle.status,
        "alerts": [alert.model_dump() for alert in fresh_alerts],
    }


@app.post("/reroute")
async def reroute(body: RerouteRequest):
    """
    Accept a recommendation: reserve capacity, draw the rescue polyline, notify
    the receiver(s), write the audit trail and update impact counters.
    """
    vehicle = _require_vehicle(body.vehicle_id)
    facility = _require_facility(body.facility_id)
    via = _require_facility(body.via_facility_id) if body.via_facility_id else None

    if vehicle.status == "DELIVERED":
        raise HTTPException(status_code=400, detail="This vehicle has already delivered")
    if vehicle.status == "REROUTED":
        raise HTTPException(status_code=400, detail="This vehicle has already been rerouted")
    if via and via.id == facility.id:
        raise HTTPException(status_code=400, detail="A split plan needs two different facilities")

    load = vehicle.load_kg
    allocations: list[tuple[object, float]] = []

    if via:
        first_kg = min(load, facility.free_kg)
        remaining = load - first_kg
        if remaining > via.free_kg:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Together these facilities have only "
                    f"{facility.free_kg + via.free_kg:.0f} kg free, {load:.0f} kg needed"
                ),
            )
        allocations = [(facility, first_kg), (via, remaining)]
    else:
        if facility.free_kg < load:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"{facility.name} has {facility.free_kg:.0f} kg free, "
                    f"but the load is {load:.0f} kg"
                ),
            )
        allocations = [(facility, load)]

    # The cargo must survive the trip to every stop.
    for target, _kg in allocations:
        if matcher.eta_hours(vehicle, target) >= vehicle.shelf_life_h:
            raise HTTPException(
                status_code=400,
                detail=f"Cargo would not survive the trip to {target.name}",
            )

    # Hand the load to a healthy rescue vehicle: speed and temperature normalise.
    if vehicle.original_destination_id is None:
        vehicle.original_destination_id = vehicle.destination_id
    simulator.clear_scenarios(vehicle.id)

    # Reserve capacity and notify each receiver.
    for target, kg in allocations:
        target.free_kg = round(target.free_kg - kg, 1)
        eta = matcher.eta_hours(vehicle, target)
        state.add_notification(
            target.id,
            f"Incoming {kg:.0f} kg {vehicle.produce}, ETA {eta:.1f} h.",
            vehicle.id,
        )

    # Redraw the route through the receiving facility (or both, for a split load).
    destinations = [target.position for target, _kg in allocations]
    vehicle.new_route = await matcher.build_rescue_route_async(vehicle.position, destinations)
    vehicle.reroute_stops = [target.id for target, _kg in allocations]
    vehicle.destination_id = allocations[-1][0].id  # the route ends at the last stop
    vehicle.rerouted_to = facility.id
    vehicle.status = "REROUTED"
    state.progress_km[vehicle.id] = 0.0
    length = matcher.route_length_km(vehicle.new_route)
    vehicle.distance_remaining_km = round(length, 2)
    vehicle.eta_hours = round(length / vehicle.speed_kmph, 2) if vehicle.speed_kmph > 0 else 999.0

    targets_text = " + ".join(f"{target.name} ({kg:.0f} kg)" for target, kg in allocations)
    state.add_audit(
        "REROUTE",
        f"{vehicle.name}: {load:.0f} kg {vehicle.produce} rerouted to {targets_text}.",
        vehicle.id,
    )
    state.record_rescue(
        load,
        vehicle_id=vehicle.id,
        allocations=allocations,
    )
    state.resolve_alert(vehicle.id)

    await broadcast()
    return {
        "ok": True,
        "vehicle_id": vehicle.id,
        "facility_ids": [target.id for target, _kg in allocations],
        "kg_rescued": load,
        "impact": dict(state.impact),
    }


class TransferRequest(BaseModel):
    """Body of POST /transfer-load."""

    broken_vehicle_id: str
    candidate_vehicle_id: str
    facility_id: str


@app.post("/transfer-load")
async def transfer_load_endpoint(body: TransferRequest):
    """
    Truck-to-truck load transfer: a healthy truck drives to the broken truck's
    position, picks up the cargo, and delivers it to the receiving facility.
    """
    result = state.transfer_load(
        body.broken_vehicle_id,
        body.candidate_vehicle_id,
        body.facility_id,
    )
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["detail"])
    await broadcast()
    return result


@app.post("/reset")
async def reset(label: str = Query("demo", description="Name shown in the analytics ledger for this run")):
    """Restore the exact seed state so the demo can be run again."""
    state.reset_state(label=label)
    state.add_audit("SYSTEM", f"Demo reset to seed state (run: {label}).")
    await broadcast()
    return state.get_state()


# --- Realtime endpoint ------------------------------------------------------
@app.websocket("/events")
async def events(websocket: WebSocket):
    """Push the full state immediately, then once per simulator tick."""
    await websocket.accept()
    _clients.add(websocket)
    _mark_activity()
    try:
        await websocket.send_text(json.dumps(state.get_state()))
        while True:
            # We do not need client messages; this keeps the socket open and
            # raises WebSocketDisconnect as soon as the browser goes away.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _clients.discard(websocket)


# --- Static frontend (built with `npm run build`) ---------------------------
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
else:

    @app.get("/")
    async def root():
        return {
            "message": "FreshRoute API is running. Build frontend/ with `npm run build`.",
            "docs": "/docs",
            "state": "/state",
        }
