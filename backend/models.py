"""
FreshRoute data models.

Responsible for: the shape of every object that crosses the API boundary —
vehicles, facilities, alerts, recommendations and reroute requests.
NOT responsible for: loading data, simulation, scoring or API routing.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VehicleStatus = Literal["OK", "AT_RISK", "REROUTED", "DELIVERED"]
ProduceClass = Literal["fast", "stable"]
FacilityType = Literal["cold_storage", "kitchen", "shelter"]
AlertReason = Literal["temperature", "delay"]


class Vehicle(BaseModel):
    """One refrigerated truck carrying one produce load."""

    id: str
    name: str
    produce: str
    produce_class: ProduceClass
    load_kg: float
    temp_c: float
    shelf_life_h: float
    speed_kmph: float
    route_id: str
    destination_id: str
    position: list[float] = Field(..., min_length=2, max_length=2)
    status: VehicleStatus = "OK"

    # Simulation bookkeeping. These are shown in the UI but never edited by it.
    baseline_temp_c: float = 5.0
    cruise_kmph: float = 0.0
    distance_remaining_km: float = 0.0
    eta_hours: float = 0.0

    # Filled only after a dispatcher accepts a reroute.
    new_route: list[list[float]] | None = None
    original_destination_id: str | None = None
    rerouted_to: str | None = None
    # Every receiving facility in stop order. A split rescue has two entries.
    reroute_stops: list[str] = Field(default_factory=list)


class Facility(BaseModel):
    """A cold storage, community kitchen or food shelter that can absorb a load."""

    id: str
    name: str
    type: FacilityType
    position: list[float] = Field(..., min_length=2, max_length=2)
    capacity_kg: float
    free_kg: float
    contact: str


class Alert(BaseModel):
    """A risk breach raised for one vehicle. One alert per breach, not per tick."""

    id: str
    vehicle_id: str
    reason: AlertReason
    details: str
    timestamp: str
    resolved: bool = False


class ScoreComponents(BaseModel):
    """The four explainable inputs to the matching score, each between 0 and 1."""

    proximity: float
    capacity_fit: float
    cold_chain_match: float
    time_margin: float


class Recommendation(BaseModel):
    """One ranked facility with its score breakdown and a plain-English reason."""

    facility_id: str
    facility_name: str
    facility_type: FacilityType
    distance_km: float
    eta_hours: float
    total_score: float
    components: ScoreComponents
    why: str
    spare_hours: float = 0.0   # hours of shelf life remaining after the trip


class SplitStop(Recommendation):
    """One leg of a two-stop rescue plan, carrying the kilograms sent there."""

    kg_allocated: float


class SplitPlan(BaseModel):
    """Fallback when no single facility can take the whole load."""

    stops: list[SplitStop]
    total_kg: float


class NearestOption(BaseModel):
    """
    The closest facility to the truck, whether it can help, and a plain-English
    reason. This powers the "why not the nearest?" explainer in the UI.
    """

    facility_id: str
    facility_name: str
    facility_type: FacilityType
    distance_km: float
    eta_hours: float
    feasible: bool
    reason: str
    # Score of the nearest facility (only populated when feasible and a chosen
    # facility exists). Lets the UI render a counterfactual comparison card.
    total_score: float | None = None
    components: ScoreComponents | None = None


class TransferOption(BaseModel):
    """
    A nearby healthy truck that can drive to the broken truck's location,
    pick up its load, and deliver it to the nearest feasible facility.
    """

    vehicle_id: str
    vehicle_name: str
    distance_to_broken_km: float
    load_kg: float
    target_facility_id: str
    target_facility_name: str
    distance_to_facility_km: float
    total_eta_hours: float
    why: str


class RecommendationResponse(BaseModel):
    """What GET /recommend/{vehicle_id} returns: one ranked list, a split plan,
    or a 'none' mode when no facility can take the load in time."""

    vehicle_id: str
    mode: Literal["single", "split", "none"]
    recommendations: list[Recommendation]
    split_plan: SplitPlan | None = None
    nearest: NearestOption | None = None
    # Plain-English explanation of why no rescue is possible, only set when
    # mode == "none".
    blocked_reason: str | None = None
    # Nearby healthy trucks that can pick up the load by driving to the broken
    # truck's location, only set when mode == "none".
    transfer_options: list[TransferOption] | None = None


class RerouteRequest(BaseModel):
    """Body of POST /reroute. `via_facility_id` is only used for a two-stop plan."""

    vehicle_id: str
    facility_id: str
    via_facility_id: str | None = None
