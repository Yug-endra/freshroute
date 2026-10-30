"""
FreshRoute matching engine.

Responsible for: distance geometry, feasibility checks, explainable facility
scoring, ranked recommendations and the two-stop split plan.
NOT responsible for: HTTP routing, simulation, alerts or writing to state.
"""

from __future__ import annotations

import math

import httpx

from .models import (
    Facility,
    NearestOption,
    Recommendation,
    ScoreComponents,
    SplitPlan,
    SplitStop,
    TransferOption,
    Vehicle,
)

# --- Tunable scoring weights (they sum to 1.0) ------------------------------
W_PROXIMITY = 0.40
W_CAPACITY = 0.30
W_COLD_CHAIN = 0.20
W_TIME_MARGIN = 0.10

# How fast a replacement truck is assumed to move after a breakdown.
RECOVERY_SPEED_KMPH = 20.0

# How well each facility type preserves each produce class.
COLD_CHAIN_SCORE = {
    "fast": {"kitchen": 1.0, "shelter": 0.9, "cold_storage": 0.6},
    "stable": {"cold_storage": 1.0, "kitchen": 0.7, "shelter": 0.6},
}

TYPE_LABEL = {
    "cold_storage": "cold storage",
    "kitchen": "community kitchen",
    "shelter": "food shelter",
}

# Route-length cache: avoids re-walking the polyline on every tick.
# Keys are the tuple of coordinates so memory reuse cannot cause stale lookups.
_route_len_cache: dict[tuple[tuple[float, float], ...], float] = {}

# Cache for OSRM road polylines keyed on (start_tuple, end_tuple).
# Avoids a network round-trip when the dispatcher re-opens the reroute panel.
_osrm_cache: dict[tuple, list[list[float]]] = {}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometres between two lat/lng points."""
    radius_km = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius_km * math.asin(math.sqrt(a))


def route_length_km(points: list[list[float]]) -> float:
    """Total length of a polyline, in kilometres (cached by waypoint coordinates)."""
    if not points:
        return 0.0
    key = tuple((p[0], p[1]) for p in points)
    if key not in _route_len_cache:
        _route_len_cache[key] = sum(
            haversine_km(a[0], a[1], b[0], b[1]) for a, b in zip(points, points[1:])
        )
    return _route_len_cache[key]


def interpolate_position(points: list[list[float]], progress_km: float) -> list[float]:
    """Return the [lat, lng] reached after travelling `progress_km` along the polyline."""
    if not points:
        return [0.0, 0.0]
    if progress_km <= 0:
        return list(points[0])

    travelled = 0.0
    for start, end in zip(points, points[1:]):
        segment = haversine_km(start[0], start[1], end[0], end[1])
        if travelled + segment >= progress_km:
            # Linear interpolation inside this segment (the road is straight between waypoints).
            ratio = 0 if segment == 0 else (progress_km - travelled) / segment
            return [
                start[0] + (end[0] - start[0]) * ratio,
                start[1] + (end[1] - start[1]) * ratio,
            ]
        travelled += segment
    return list(points[-1])


def remaining_route_km(points: list[list[float]], progress_km: float) -> float:
    """How many kilometres are left on this polyline."""
    return max(0.0, route_length_km(points) - progress_km)


def straight_line_km(vehicle: Vehicle, facility: Facility) -> float:
    """Driving stand-in distance: great-circle distance between truck and facility."""
    return haversine_km(
        vehicle.position[0], vehicle.position[1], facility.position[0], facility.position[1]
    )


def effective_speed_kmph(vehicle: Vehicle) -> float:
    """
    Speed used for an alternative trip. A rescue is run by a sound vehicle, so we
    assume the truck's healthy cruising speed even when it is crawling or stopped.
    """
    return max(vehicle.speed_kmph, vehicle.cruise_kmph, RECOVERY_SPEED_KMPH)


def eta_hours(vehicle: Vehicle, facility: Facility) -> float:
    """Estimated hours to reach a facility at the recovery speed."""
    return straight_line_km(vehicle, facility) / effective_speed_kmph(vehicle)


def is_feasible(vehicle: Vehicle, facility: Facility) -> bool:
    """A facility can help only if it has room and the cargo survives the trip."""
    if facility.free_kg < vehicle.load_kg:
        return False
    return eta_hours(vehicle, facility) < vehicle.shelf_life_h


def score_facility(vehicle: Vehicle, facility: Facility, max_distance: float) -> dict:
    """
    Score one facility from 0 to 1 on four explainable components.

    Returns a plain dict so tests and the API can inspect each component.
    """
    distance = straight_line_km(vehicle, facility)
    eta = eta_hours(vehicle, facility)

    # Closer is better. Distances are normalised by the farthest candidate.
    proximity = (
        max(0.0, min(1.0, 1.0 - distance / max_distance)) if max_distance > 0 else 1.0
    )

    # A facility whose free space closely matches the load scores higher than an
    # enormous warehouse that would be mostly empty after the drop.
    capacity_fit = min(1.0, vehicle.load_kg / facility.free_kg) if facility.free_kg > 0 else 0.0

    cold_chain = COLD_CHAIN_SCORE[vehicle.produce_class][facility.type]

    margin = vehicle.shelf_life_h - eta
    time_margin = max(0.0, min(1.0, margin / vehicle.shelf_life_h)) if vehicle.shelf_life_h > 0 else 0.0

    total = (
        W_PROXIMITY * proximity
        + W_CAPACITY * capacity_fit
        + W_COLD_CHAIN * cold_chain
        + W_TIME_MARGIN * time_margin
    )

    return {
        "distance_km": round(distance, 2),
        "eta_hours": round(eta, 2),
        "components": {
            "proximity": round(proximity, 3),
            "capacity_fit": round(capacity_fit, 3),
            "cold_chain_match": round(cold_chain, 3),
            "time_margin": round(time_margin, 3),
        },
        "total": round(total, 3),
        "spare_hours": margin,
    }


def _why(vehicle: Vehicle, facility: Facility, result: dict, allocated_kg: float | None = None) -> str:
    """Build the one-sentence explanation shown under each recommendation card."""
    label = TYPE_LABEL[facility.type]
    # For a split stop, show how much of this facility's space the allocated
    # drop uses; otherwise show the whole load against free space.
    load = allocated_kg if allocated_kg is not None else vehicle.load_kg
    used_pct = round(100 * load / facility.free_kg) if facility.free_kg else 0
    spare = max(0.0, result["spare_hours"])
    return (
        f"{label.capitalize()} {result['distance_km']:.1f} km away, uses {used_pct}% "
        f"of its free space and arrives with {spare:.1f} h of shelf life to spare."
    )


def recommend(vehicle: Vehicle, facilities: list[Facility], top_n: int = 3) -> list[Recommendation]:
    """Filter to feasible facilities, score them, and return the best `top_n`."""
    candidates = [f for f in facilities if is_feasible(vehicle, f)]
    if not candidates:
        return []

    # Normalise proximity against every facility so the nearest always scores near 1.
    farthest = max(straight_line_km(vehicle, f) for f in facilities)
    ranked: list[Recommendation] = []
    for facility in candidates:
        result = score_facility(vehicle, facility, farthest)
        ranked.append(
            Recommendation(
                facility_id=facility.id,
                facility_name=facility.name,
                facility_type=facility.type,
                distance_km=result["distance_km"],
                eta_hours=result["eta_hours"],
                total_score=result["total"],
                components=ScoreComponents(**result["components"]),
                why=_why(vehicle, facility, result),
                spare_hours=round(max(0.0, result["spare_hours"]), 2),
            )
        )

    ranked.sort(key=lambda rec: rec.total_score, reverse=True)
    return ranked[:top_n]


COMPONENT_LABEL = {
    "proximity": "proximity",
    "capacity_fit": "capacity fit",
    "cold_chain_match": "cold-chain match",
    "time_margin": "time margin",
}


def nearest_option(
    vehicle: Vehicle,
    facilities: list[Facility],
    chosen: Recommendation | SplitStop | None = None,
) -> NearestOption | None:
    """
    Describe the closest facility, even when it is not a good answer.

    Judges always ask "why not the nearest one?". Returning the nearest site plus
    a one-line reason lets the UI answer that without inventing anything.
    When the nearest IS feasible we also return its full score breakdown so the
    UI can draw a side-by-side counterfactual without a second request.
    """
    if not facilities:
        return None

    nearest = min(facilities, key=lambda f: straight_line_km(vehicle, f))
    distance = round(straight_line_km(vehicle, nearest), 2)
    eta = round(eta_hours(vehicle, nearest), 2)

    nearest_score: float | None = None
    nearest_components: ScoreComponents | None = None

    if nearest.free_kg < vehicle.load_kg:
        feasible = False
        reason = (
            f"only {nearest.free_kg:.0f} kg free against a {vehicle.load_kg:.0f} kg load"
        )
    elif eta >= vehicle.shelf_life_h:
        feasible = False
        reason = (
            f"a {eta:.1f} h trip against {vehicle.shelf_life_h:.1f} h of shelf life left"
        )
    else:
        feasible = True
        # Score the nearest facility so the UI can draw the counterfactual.
        farthest = max(straight_line_km(vehicle, f) for f in facilities) or 1.0
        result = score_facility(vehicle, nearest, farthest)
        nearest_score = result["total"]
        nearest_components = ScoreComponents(**result["components"])

        reason = "it is feasible, but the ranked options score higher overall"
        if chosen is not None:
            gaps = {
                key: round(getattr(chosen.components, key, 0.0) - result["components"][key], 3)
                for key in result["components"]
            }
            weakest = max(gaps, key=gaps.get)
            if gaps[weakest] > 0:
                reason = (
                    f"it is feasible, but the top pick wins on {COMPONENT_LABEL[weakest]}"
                )

    return NearestOption(
        facility_id=nearest.id,
        facility_name=nearest.name,
        facility_type=nearest.type,
        distance_km=distance,
        eta_hours=eta,
        feasible=feasible,
        reason=reason,
        total_score=nearest_score,
        components=nearest_components,
    )


def onward_for(
    vehicle: Vehicle, first: Facility, first_result: dict, remaining_kg: float
) -> Vehicle:
    """
    The truck as it leaves the first stop: a smaller load, the shelf life left
    after the first leg, and a new position. The second stop is scored and
    explained against this state, so a two-stop plan cannot teleport.
    """
    return vehicle.model_copy(
        update={
            "position": list(first.position),
            "load_kg": remaining_kg,
            "shelf_life_h": max(0.0, vehicle.shelf_life_h - first_result["eta_hours"]),
        }
    )


def split_plan(vehicle: Vehicle, facilities: list[Facility]) -> SplitPlan | None:
    """
    Build a two-stop plan when no single facility can take the whole load.

    The truck drops part of the load at the first stop and drives on to the
    second. The second leg is measured from the first stop, and the shelf life
    used to score it is what is left after the first leg, so the plan cannot
    pretend the truck teleports or that time stands still between stops.
    """
    usable = [
        f
        for f in facilities
        if f.free_kg > 0 and eta_hours(vehicle, f) < vehicle.shelf_life_h
    ]
    if len(usable) < 2:
        return None

    farthest = max(straight_line_km(vehicle, f) for f in facilities) or 1.0
    best: tuple[float, Facility, Facility, float, float, dict, dict, Vehicle] | None = None

    # Try every ordered pair and keep the pair with the best combined score.
    for first in usable:
        first_kg = min(vehicle.load_kg, first.free_kg)
        remaining = vehicle.load_kg - first_kg
        if remaining <= 0:
            continue
        first_result = score_facility(vehicle, first, farthest)

        # What the truck looks like when it leaves the first stop: same cargo
        # minus the drop, less shelf life, and standing at the first facility.
        onward = onward_for(vehicle, first, first_result, remaining)

        for second in usable:
            if second.id == first.id or second.free_kg < remaining:
                continue
            second_result = score_facility(onward, second, farthest)
            # Cargo must still be edible when the truck reaches stop two.
            if second_result["eta_hours"] >= onward.shelf_life_h:
                continue
            combined = first_result["total"] + second_result["total"]
            if best is None or combined > best[0]:
                best = (
                    combined,
                    first,
                    second,
                    first_kg,
                    remaining,
                    first_result,
                    second_result,
                    onward,
                )

    if best is None:
        return None

    _, first, second, first_kg, second_kg, first_result, second_result, onward = best
    stops: list[SplitStop] = []
    for facility, kg, result, scored_for in (
        (first, first_kg, first_result, vehicle),
        (second, second_kg, second_result, onward),
    ):
        stops.append(
            SplitStop(
                facility_id=facility.id,
                facility_name=facility.name,
                facility_type=facility.type,
                distance_km=result["distance_km"],
                eta_hours=result["eta_hours"],
                total_score=result["total"],
                components=ScoreComponents(**result["components"]),
                why=_why(scored_for, facility, result, allocated_kg=kg),
                kg_allocated=round(kg, 1),
            )
        )

    return SplitPlan(stops=stops, total_kg=round(first_kg + second_kg, 1))


def build_rescue_route(start: list[float], destinations: list[list[float]]) -> list[list[float]]:
    """
    Draw a plausible rescue polyline from the truck's current position to one or
    two facilities. A gentle sideways bow makes it read as a road rather than a
    ruler line. No road API is involved.
    """
    points: list[list[float]] = [list(start)]
    origin = start
    for target in destinations:
        for fraction in (0.25, 0.5, 0.75):
            lat = origin[0] + (target[0] - origin[0]) * fraction
            lng = origin[1] + (target[1] - origin[1]) * fraction
            bow = math.sin(math.pi * fraction) * 0.008
            points.append([round(lat + bow, 5), round(lng + bow * 0.6, 5)])
        points.append(list(target))
        origin = target
    return points


async def build_rescue_route_async(
    start: list[float],
    destinations: list[list[float]],
) -> list[list[float]]:
    """
    Fetch real road polylines from the OSRM public demo server
    (http://router.project-osrm.org) for each leg of the rescue route.

    - OSRM returns coordinates as [lng, lat]; these are flipped to [lat, lng]
      for Leaflet before being stored.
    - A module-level dict `_osrm_cache` keyed on (start_tuple, end_tuple) avoids
      repeated network calls for the same leg within a session.
    - Any leg that fails (timeout, non-200, code != "Ok", or network error) falls
      back to `build_rescue_route` for that leg so the UI always gets a polyline.
    - Timeout per HTTP request: 3 seconds.

    For a two-destination split plan the two legs are stitched together; the
    duplicate junction point (last point of leg 1 == first point of leg 2) is
    removed before joining so the polyline has no repeated node.
    """
    OSRM_BASE = "http://router.project-osrm.org/route/v1/driving"
    TIMEOUT_S = 3.0

    async def _fetch_leg(leg_start: list[float], leg_end: list[float]) -> list[list[float]]:
        """Return [lat, lng] points for one leg, using cache or OSRM, or the bow fallback."""
        cache_key = (
            (leg_start[0], leg_start[1]),
            (leg_end[0], leg_end[1]),
        )
        if cache_key in _osrm_cache:
            return _osrm_cache[cache_key]

        # OSRM expects coordinates in {lng},{lat} order.
        coords = f"{leg_start[1]},{leg_start[0]};{leg_end[1]},{leg_end[0]}"
        url = f"{OSRM_BASE}/{coords}?overview=full&geometries=geojson"

        try:
            async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
                resp = await client.get(url)
            if resp.status_code != 200:
                raise ValueError(f"HTTP {resp.status_code}")
            data = resp.json()
            if data.get("code") != "Ok":
                raise ValueError(f"OSRM code={data.get('code')}")
            # OSRM geometry is [[lng, lat], ...]; flip to [[lat, lng]] for Leaflet.
            raw = data["routes"][0]["geometry"]["coordinates"]
            leg_points = [[pt[1], pt[0]] for pt in raw]
        except Exception:
            # Network failure, timeout, or unexpected response — use the bow fallback.
            leg_points = build_rescue_route(leg_start, [leg_end])

        _osrm_cache[cache_key] = leg_points
        return leg_points

    if not destinations:
        return [list(start)]

    # Build the full route leg by leg, stitching without duplicate junction nodes.
    full_route: list[list[float]] = []
    leg_start = start
    for leg_end in destinations:
        leg = await _fetch_leg(leg_start, leg_end)
        if full_route:
            # Remove the first point of this leg — it duplicates the last point
            # of the previous leg (the junction facility).
            leg = leg[1:]
        full_route.extend(leg)
        leg_start = leg_end

    return full_route


def transfer_options(
    broken_vehicle: Vehicle,
    all_vehicles: list[Vehicle],
    facilities: list[Facility],
    max_transfer_distance_km: float = 100.0,
) -> list[TransferOption]:
    """
    Find healthy trucks that can rescue the broken truck's load by driving to
    its location, picking up the cargo, and delivering it to the nearest
    feasible facility.

    Returns a list of TransferOption, ranked by total ETA (fastest first).
    A candidate truck must:
      - Be in OK status (healthy, not itself at risk or rerouted)
      - Not be the broken truck
      - Be within max_transfer_distance_km of the broken truck
    For each candidate, the nearest facility reachable from the broken truck's
    position within the cargo's remaining shelf life is chosen as the drop-off.
    """
    options: list[TransferOption] = []

    for candidate in all_vehicles:
        if candidate.id == broken_vehicle.id:
            continue
        if candidate.status != "OK":
            continue

        distance_to_broken = straight_line_km(candidate, broken_vehicle)
        if distance_to_broken > max_transfer_distance_km:
            continue

        # The candidate picks up the load at the broken truck's position, so
        # the delivery leg starts from the broken truck's position.
        proxy = broken_vehicle.model_copy(update={"position": list(broken_vehicle.position)})

        ranked = recommend(proxy, facilities, top_n=1)
        if not ranked:
            continue

        best = ranked[0]
        distance_to_facility = best.distance_km
        total_eta = round(
            distance_to_broken / candidate.speed_kmph + best.eta_hours, 2
        )

        shelf_ok = total_eta < broken_vehicle.shelf_life_h
        if not shelf_ok:
            continue

        why = (
            f"{candidate.name} is {distance_to_broken:.1f} km away, can reach "
            f"{best.facility_name} ({best.facility_type}) in {best.eta_hours:.1f} h "
            f"after pickup — total {total_eta:.1f} h."
        )

        options.append(
            TransferOption(
                vehicle_id=candidate.id,
                vehicle_name=candidate.name,
                distance_to_broken_km=round(distance_to_broken, 2),
                load_kg=round(broken_vehicle.load_kg, 1),
                target_facility_id=best.facility_id,
                target_facility_name=best.facility_name,
                distance_to_facility_km=distance_to_facility,
                total_eta_hours=total_eta,
                why=why,
            )
        )

    options.sort(key=lambda o: o.total_eta_hours)
    return options

