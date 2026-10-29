"""
FreshRoute headless simulation demo.

Responsible for: running 20 ticks without a server, triggering a reefer failure
after tick 5, and printing the exact tick where the alert fires.
NOT responsible for: the web UI, HTTP endpoints or persistent output.

Run with:  .venv\\Scripts\\python -m backend.demo_sim
"""

from __future__ import annotations

import argparse

from . import matcher, risk, simulator, state


def main() -> None:
    parser = argparse.ArgumentParser(description="FreshRoute 20-tick headless demo")
    parser.add_argument("--vehicle", default="V1", help="vehicle id (default: V1)")
    parser.add_argument("--scenario", default="reefer_failure",
                        choices=["reefer_failure", "delay", "breakdown"])
    args = parser.parse_args()

    state.reset_state()
    if args.vehicle not in state.vehicles:
        raise SystemExit(f"Unknown vehicle '{args.vehicle}'. Choose from {list(state.vehicles)}")

    vehicle = state.vehicles[args.vehicle]
    print(f"FreshRoute demo | {vehicle.name} | {vehicle.load_kg:.0f} kg {vehicle.produce}")
    print(f"Route {vehicle.route_id} | {vehicle.distance_remaining_km:.1f} km to destination")
    print(f"Scenario '{args.scenario}' fires after tick 5\n")
    print(f"{'tick':>4}  {'temp C':>7}  {'shelf h':>7}  {'eta h':>6}  {'km left':>7}  status")
    print("-" * 58)

    fired: int | None = None
    for tick_number in range(1, 21):
        if tick_number == 6:
            {"reefer_failure": simulator.trigger_reefer_failure,
             "delay": simulator.trigger_delay,
             "breakdown": simulator.trigger_breakdown}[args.scenario](args.vehicle)

        simulator.tick()
        new_alerts = risk.run_risk_checks()
        print(
            f"{tick_number:>4}  {vehicle.temp_c:>7.1f}  {vehicle.shelf_life_h:>7.1f}  "
            f"{vehicle.eta_hours:>6.1f}  {vehicle.distance_remaining_km:>7.1f}  {vehicle.status}"
        )
        for alert in new_alerts:
            fired = tick_number
            print(f"\n  ALERT at tick {tick_number} [{alert.reason}]: {alert.details}")
            options = matcher.recommend(vehicle, list(state.facilities.values()))
            if options:
                print("  Top reroute options:")
                for rank, option in enumerate(options, 1):
                    print(
                        f"    {rank}. {option.facility_name} ({option.facility_type}) "
                        f"{option.distance_km:.1f} km, ETA {option.eta_hours:.1f} h, "
                        f"score {option.total_score:.3f}"
                    )
            print()

    if fired is None:
        print("\nNo alert fired in 20 ticks (the load survived).")
    else:
        print(f"\nDemonstration complete: alert fired at tick {fired}.")
        print(f"Audit entries: {len(state.audit_log)} | Impact: {state.impact}")


if __name__ == "__main__":
    main()
