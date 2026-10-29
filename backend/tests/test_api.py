"""
Tests for the FreshRoute HTTP and WebSocket surface.

Responsible for: proving every endpoint in the API contract answers with the
documented shape, that a dispatcher can run the whole demo loop through HTTP,
and that bad input is rejected with 400/404 instead of a traceback.
NOT responsible for: scoring maths, risk rules or movement — those have their
own test modules.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend import matcher, state
from backend.main import app


@pytest.fixture(scope="module")
def client():
    """One TestClient for the module; lifespan loads the seed state once."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def fresh_demo():
    """Each test starts from the 08:00 seed state."""
    state.reset_state()
    yield
    state.reset_state()


def test_state_returns_the_documented_shape(client):
    response = client.get("/state")

    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "vehicles",
        "facilities",
        "routes",
        "alerts",
        "notifications",
        "audit_log",
        "impact",
        "tick",
        "sim_minutes",
    }
    assert len(body["vehicles"]) == 6
    assert len(body["facilities"]) == 10
    assert len(body["routes"]) == 6
    assert body["tick"] == 0
    assert body["impact"] == {
        "kg_rescued": 0,
        "meals_saved": 0,
        "events_resolved": 0,
        "value_inr": 0,
        "co2e_kg_avoided": 0,
    }
    assert body["impact_rates"] == {
        "meals_per_kg": 2.0,
        "value_inr_per_kg": 30.0,
        "co2e_kg_per_kg": 2.5,
    }


def test_health_probe(client):
    assert client.get("/health").json()["status"] == "ok"


def test_recommend_returns_three_ranked_facilities(client):
    body = client.get("/recommend/V1").json()

    assert body["mode"] in ("single", "split")
    if body["mode"] == "single":
        assert len(body["recommendations"]) == 3
        scores = [rec["total_score"] for rec in body["recommendations"]]
        assert scores == sorted(scores, reverse=True)
        first = body["recommendations"][0]
        assert set(first["components"]) == {
            "proximity",
            "capacity_fit",
            "cold_chain_match",
            "time_margin",
        }
        assert first["why"]
    else:
        assert len(body["split_plan"]["stops"]) == 2


def test_unknown_vehicle_is_a_404(client):
    assert client.get("/recommend/NOPE").status_code == 404
    assert client.post("/reroute", json={"vehicle_id": "NOPE", "facility_id": "F1"}).status_code == 404
    assert client.post("/reroute", json={"vehicle_id": "V1", "facility_id": "NOPE"}).status_code == 404


def test_unknown_scenario_is_a_400(client):
    response = client.post("/simulate/meltdown?vehicle_id=V1")

    assert response.status_code == 400
    assert "reefer_failure" in response.json()["detail"]


def test_delay_scenario_raises_an_alert_within_one_call(client):
    response = client.post("/simulate/delay?vehicle_id=V1")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "AT_RISK"
    assert len(body["alerts"]) == 1
    assert body["alerts"][0]["reason"] in ("delay", "temperature")

    state_body = client.get("/state").json()
    assert any(alert["vehicle_id"] == "V1" for alert in state_body["alerts"])
    assert any(entry["event"] == "BREACH" for entry in state_body["audit_log"])


def test_full_rescue_loop_over_http(client):
    """Simulate, recommend, reroute, then check every counter and log entry."""
    client.post("/simulate/delay?vehicle_id=V1")
    body = client.get("/recommend/V1").json()
    if body["mode"] == "single":
        facility_id = body["recommendations"][0]["facility_id"]
        payload = {"vehicle_id": "V1", "facility_id": facility_id}
    else:
        stops = body["split_plan"]["stops"]
        facility_id = stops[0]["facility_id"]
        payload = {
            "vehicle_id": "V1",
            "facility_id": facility_id,
            "via_facility_id": stops[1]["facility_id"],
        }

    response = client.post("/reroute", json=payload)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["kg_rescued"] == 1800
    assert result["impact"]["kg_rescued"] > 0
    assert result["impact"]["meals_saved"] == round(result["impact"]["kg_rescued"] / 0.5)
    assert result["impact"]["events_resolved"] == 1
    assert result["impact"]["value_inr"] == round(result["impact"]["kg_rescued"] * 30)
    assert result["impact"]["co2e_kg_avoided"] == round(
        result["impact"]["kg_rescued"] * 2.5, 1
    )

    after = client.get("/state").json()
    vehicle = next(v for v in after["vehicles"] if v["id"] == "V1")
    assert vehicle["status"] == "REROUTED"
    assert vehicle["new_route"]
    assert after["alerts"][0]["resolved"] is True
    assert len(after["notifications"]) == len(result["facility_ids"])
    assert any(entry["event"] == "REROUTE" for entry in after["audit_log"])

    # Accepting twice is a dispatcher mistake, not a crash.
    assert client.post("/reroute", json=payload).status_code == 400


def test_reset_restores_the_demo(client):
    client.post("/simulate/reefer_failure?vehicle_id=V1")
    client.post("/reset")

    body = client.get("/state").json()
    assert body["tick"] == 0
    assert body["impact"] == {
        "kg_rescued": 0,
        "meals_saved": 0,
        "events_resolved": 0,
        "value_inr": 0,
        "co2e_kg_avoided": 0,
    }
    assert body["impact_rates"] == {
        "meals_per_kg": 2.0,
        "value_inr_per_kg": 30.0,
        "co2e_kg_per_kg": 2.5,
    }
    assert all(not alert["resolved"] for alert in body["alerts"]) is True
    assert body["alerts"] == []
    assert body["notifications"] == []
    assert {vehicle["status"] for vehicle in body["vehicles"]} == {"OK"}
    assert body["vehicles"][0]["temp_c"] == pytest.approx(
        body["vehicles"][0]["baseline_temp_c"], abs=0.01
    )


def test_websocket_pushes_the_full_state(client):
    with client.websocket_connect("/events") as socket:
        body = socket.receive_json()

    assert len(body["vehicles"]) == 6
    assert "impact" in body


def _run_rescue(client):
    """Disrupt V1, accept its best option, and return the reroute response."""
    client.post("/simulate/delay?vehicle_id=V1")
    body = client.get("/recommend/V1").json()
    if body["mode"] == "single":
        payload = {
            "vehicle_id": "V1",
            "facility_id": body["recommendations"][0]["facility_id"],
        }
    else:
        stops = body["split_plan"]["stops"]
        payload = {
            "vehicle_id": "V1",
            "facility_id": stops[0]["facility_id"],
            "via_facility_id": stops[1]["facility_id"],
        }
    return client.post("/reroute", json=payload)


def test_recommendation_explains_the_nearest_facility(client):
    """The response always names the closest site, even if it did not rank."""
    body = client.get("/recommend/V1").json()
    nearest = body["nearest"]

    assert nearest is not None
    assert {"facility_id", "distance_km", "eta_hours", "feasible", "reason"} <= set(nearest)
    assert nearest["reason"]

    vehicle = state.vehicles["V1"]
    closest = min(
        state.facilities.values(),
        key=lambda facility: matcher.haversine_km(
            vehicle.position[0],
            vehicle.position[1],
            facility.position[0],
            facility.position[1],
        ),
    )
    assert nearest["facility_id"] == closest.id


def test_audit_csv_export_contains_the_breach(client):
    client.post("/simulate/reefer_failure?vehicle_id=V2")

    response = client.get("/audit.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment;" in response.headers["content-disposition"]
    text = response.text
    assert "sim_clock,timestamp_utc,event,vehicle_id,details" in text
    assert "BREACH" in text
    assert "V2" in text


def test_ledger_survives_reset_and_aggregates_runs(client):
    """SQLite keeps history after POST /reset while the live counters go back to zero."""
    before = client.get("/analytics").json()
    response = _run_rescue(client)
    assert response.status_code == 200, response.text

    after = client.get("/analytics").json()
    assert after["all_time"]["rescues"] == before["all_time"]["rescues"] + 1
    assert after["all_time"]["kg_rescued"] >= before["all_time"]["kg_rescued"] + 1800
    assert after["current_run"]["rescues"] == 1
    assert after["recent_rescues"][0]["vehicle_id"] == "V1"
    assert after["recent_rescues"][0]["kg"] == 1800
    assert after["recent_rescues"][0]["facility_names"]
    assert after["top_facilities"][0]["kg"] >= 1800
    assert after["by_facility_type"]

    client.post("/reset")
    reset = client.get("/analytics").json()
    assert reset["current_run"]["rescues"] == 0
    assert reset["all_time"]["rescues"] == after["all_time"]["rescues"]
    assert reset["runs"] == after["runs"] + 1


def test_reroute_rejects_same_facility_for_both_split_stops(client):
    """A split plan must use two *different* facilities — same ID twice is a 400."""
    client.post("/simulate/delay?vehicle_id=V1")
    response = client.post(
        "/reroute",
        json={"vehicle_id": "V1", "facility_id": "F1", "via_facility_id": "F1"},
    )
    assert response.status_code == 400
    assert "different" in response.json()["detail"].lower()


def test_health_exposes_sim_clock_and_alert_count(client):
    """The /health endpoint must include sim_clock and active_alerts."""
    body = client.get("/health").json()
    assert "sim_clock" in body
    assert "active_alerts" in body
    assert body["status"] == "ok"

    # After triggering an alert, active_alerts must increment.
    client.post("/simulate/delay?vehicle_id=V1")
    body2 = client.get("/health").json()
    assert body2["active_alerts"] >= 1
