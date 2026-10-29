# FreshRoute architecture

A hackathon prototype, so the whole system is deliberately small: one Python process
holds all live state and simulates the world, one React page renders it, and a WebSocket
carries the full state on every tick. A single embedded SQLite file keeps the history.
There is no database server, no message queue and no external service except
OpenStreetMap tiles.

```
┌──────────────────────────── browser (React + Vite + Leaflet) ───────────────────────────┐
│  App.jsx ── useLiveState.js ──► WS /events  (full state every tick)                     │
│    │             └────────────► GET /state   (2 s fallback, 5 s socket retry)            │
│    ├── MapView (markers, routes, legend)                                                │
│    └── DemoControls / AlertPanel / RecommendPanel / NotificationFeed / Impact / Ledger  │
└───────────────────────────────────────┬─────────────────────────────────────────────────┘
                                        │ HTTP commands + WS state
┌───────────────────────────────────────▼─────────────────────────────────────────────────┐
│  backend/main.py — wiring only                                                          │
│    lifespan ──► db.init() + state.reset_state() + simulation_loop()                     │
│    simulation_loop: sleep 2 s → simulator.tick() → risk.run_risk_checks() → broadcast()  │
│    endpoints: /state /events /simulate /recommend /reroute /reset /analytics /audit.csv  │
└──────┬───────────────────────┬──────────────────────────┬───────────────────────────────┘
       │                       │                          │
 ┌─────▼──────┐        ┌───────▼────────┐         ┌───────▼────────┐
 │ state.py   │◄───────┤ simulator.py   │         │ matcher.py     │
 │ source of  │        │ tick, movement │         │ score, rank,   │
 │ truth      │◄───────┤ risk.py        │         │ split, route   │
 └─────┬──────┘        └────────────────┘         └────────────────┘
       │
       ├── backend/data/{vehicles,facilities,routes}.json   (loaded at startup and on /reset)
       └── db.py ──► backend/data/freshroute.db   (runs, audit_events, rescues)
```

## Feature → file/function map

| Feature | Where it lives | Key functions |
| ------- | -------------- | ------------- |
| Seed data & in-memory state | `backend/state.py` | `reset_state()`, `get_state()`, `_load_json()` |
| Simulated clock (08:00 + 6 min/tick) | `backend/state.py`, `backend/main.py` | `_sim_clock()`, `simulation_loop()` |
| Truck movement along a polyline | `backend/simulator.py`, `backend/matcher.py` | `_advance()`, `interpolate_position()`, `remaining_route_km()` |
| Temperature drift and shelf-life burn | `backend/simulator.py` | `_update_cargo()` |
| Disruption scenarios | `backend/simulator.py`, `backend/main.py` | `trigger_reefer_failure()`, `trigger_delay()`, `trigger_breakdown()`, `POST /simulate/{scenario}` |
| Risk trigger (breach detection) | `backend/risk.py` | `check_vehicle()`, `run_risk_checks()` |
| Alert de-duplication and status | `backend/risk.py`, `backend/state.py` | `check_vehicle()`, `active_alerts`, `resolve_alert()` |
| Matching / ranking | `backend/matcher.py` | `is_feasible()`, `score_facility()`, `recommend()` |
| "Why not the nearest?" explainer | `backend/matcher.py`, `backend/main.py` | `nearest_option()`, `GET /recommend/{id}` |
| Split plan when nothing fits alone | `backend/matcher.py`, `backend/main.py` | `split_plan()`, `GET /recommend/{id}` |
| Reroute command | `backend/main.py` | `reroute()` |
| Rescue polyline | `backend/matcher.py` | `build_rescue_route()` |
| Receiver notifications | `backend/state.py`, `backend/main.py` | `add_notification()`, `reroute()` |
| Audit trail | `backend/state.py`, `backend/risk.py`, `backend/main.py` | `add_audit()` at every decision point |
| Impact counters | `backend/state.py`, `backend/main.py` | `record_rescue()`, `reroute()` |
| SQLite ledger (runs, rescues, audit) | `backend/db.py`, `backend/state.py` | `init()`, `start_run()`, `log_audit()`, `log_rescue()`, `analytics()`, `audit_rows()` |
| Cross-run analytics panel | `frontend/src/components/AnalyticsPanel.jsx` | `AnalyticsPanel()`, `fetchAnalytics()` |
| CSV export | `backend/main.py` | `download_audit_csv()`, `GET /audit.csv` |
| Reset | `backend/state.py`, `backend/db.py`, `backend/main.py` | `reset_state()` (starts a new run), `POST /reset` |
| Live push | `backend/main.py` | `broadcast()`, `events()`, `simulation_loop()` |
| Polling fallback & retry | `frontend/src/hooks/useLiveState.js` | `connect()`, `startPolling()`, `stopPolling()` |
| Map, markers, legend, fly-to | `frontend/src/components/MapView.jsx` | `MapView()`, `truckIcon()`, `facilityIcon()`, `PanToVehicle()` |
| Dispatcher controls | `frontend/src/components/DemoControls.jsx`, `App.jsx` | `runScenario()`, `handleScenario()`, `handleReset()` |
| Recommendations UI | `frontend/src/components/RecommendPanel.jsx` | `ScoreBar()`, `RecommendationCard()`, fetch-once-per-alert effect |
| Alert list & runway bar | `frontend/src/components/AlertPanel.jsx` | `AlertPanel()`, `runwayFor()` |
| Receiver feed | `frontend/src/components/NotificationFeed.jsx` | `NotificationFeed()` |
| Impact & audit UI | `frontend/src/components/ImpactCounters.jsx`, `AnalyticsPanel.jsx`, `AuditLog.jsx` | `ImpactCounters()`, `AnalyticsPanel()`, `AuditLog()` |
| Formatting helpers | `frontend/src/format.js` | `formatKg()`, `formatHours()`, `formatTemp()`, `formatTime()`, `formatInr()`, `formatCo2e()` |
| HTTP client | `frontend/src/api.js` | `fetchState()`, `triggerScenario()`, `fetchRecommendations()`, `acceptReroute()`, `resetDemo()`, `fetchAnalytics()` |

## The 8-step data flow

1. **Startup.** `main.lifespan()` calls `db.init()` (creates the SQLite schema if
   needed) and `state.reset_state()`, which reads `vehicles.json`, `facilities.json` and
   `routes.json` into dicts, computes each truck's remaining distance/ETA, opens a new
   ledger run and writes one `SYSTEM` audit entry. `simulation_loop()` starts.

2. **Dashboard connects.** `useLiveState()` opens `ws://…/events`. The socket immediately
   receives a full `get_state()` snapshot, then one snapshot every tick. If the socket
   fails, the hook polls `GET /state` every 2 s and retries the socket every 5 s.

3. **Dispatcher triggers a disruption.** `DemoControls` posts
   `/simulate/{scenario}?vehicle_id=V1`. `main.simulate()` calls the matching
   `simulator.trigger_*()` function, writes a `SCENARIO` audit entry, runs
   `risk.run_risk_checks()` and broadcasts the new state.

4. **World advances.** Every 2 s `simulation_loop()` calls `simulator.tick()`:
   `_advance()` moves each truck along its active polyline (`interpolate_position`),
   `_update_cargo()` drifts temperature and burns shelf life (5× faster during a traffic
   hold, until the breach is flagged). A truck that reaches its destination is marked
   `DELIVERED`, gets an audit entry, and reloads after three ticks.

5. **Risk engine decides.** `risk.check_vehicle()` compares `temp_c > 10` and
   `eta_hours > shelf_life_h`. The first breach sets `AT_RISK`, appends exactly one
   `Alert`, records one `BREACH` audit entry and stores the alert in `state.active_alerts`
   so later ticks cannot duplicate it.

6. **Browser shows the alert and asks for options.** `AlertPanel` lists unresolved alerts
   with a runway bar (trip ETA vs remaining shelf life). When the selected truck is
   `AT_RISK` with an unresolved alert, `RecommendPanel` calls `GET /recommend/{id}`
   **once per alert**. `main.get_recommendations()` → `matcher.recommend()` filters
   feasible facilities (`free_kg >= load_kg` and `eta_hours < shelf_life_h`), scores each
   on proximity 0.40, capacity fit 0.30, cold-chain 0.20 and time margin 0.10, sorts and
   returns the top three with a plain-English "why". If nothing fits,
   `matcher.split_plan()` returns two stops. Either way `matcher.nearest_option()` adds
   the closest site and the reason it did or did not win.

7. **Dispatcher accepts a reroute.** `POST /reroute` validates the request, checks
   capacity and survival time, restores the truck's cruising speed/temperature
   (`clear_scenarios`), subtracts `free_kg` from each receiver, writes one "Incoming …"
   notification per stop, builds the rescue polyline (`build_rescue_route`), sets status
   `REROUTED`, records a `REROUTE` audit entry, updates the impact counters
   (kg, meals = kg × 2, ₹ = kg × 30, CO₂e = kg × 2.5, events + 1), writes one `rescues`
   row to SQLite, resolves the alert and broadcasts.

8. **Map redraws.** The next state snapshot carries `new_route`, so `MapView` draws the
   bold green animated polyline in its own pane, colours the truck blue, and the panels
   show the resolved card, the receiver feed, the new counters, the refreshed SQLite
   ledger (runs, all-time kg/₹, recent rescues) and the audit rows. `POST /reset` at any
   time repeats step 1 — new run, cleared live lists and counters — while the ledger
   keeps every earlier run and `/audit.csv` still exports the full history.

## Persistence design (why SQLite, and how it stays safe)

```
runs(id, started_at, label)
audit_events(id, run_id, entry_id, sim_clock, timestamp, event, vehicle_id, details)
rescues(id, run_id, timestamp, sim_clock, vehicle_id, kg, meals, value_inr, co2e_kg,
        facility_ids, facility_names, facility_types)
```

- **The live world never waits for the disk.** `state.py` is still the only source of
  truth for vehicles, alerts and counters. `db.py` is a write-behind logger; every public
  function is wrapped in `_guard()`, which prints one warning and returns `None` on
  failure. A read-only or missing file degrades the ledger, never the demo.
- **A run is a reset-to-reset session.** `reset_state()` calls `db.start_run()`, so the
  analytics panel can separate *this run* from *all runs today* while `/reset` still
  restores the exact seed state.
- **Estimates are constants, not magic numbers.** `IMPACT_RATES` in `state.py` is the
  single definition of meals/kg, ₹/kg and CO₂e/kg; `/state` and `/analytics` expose it so
  the UI can label every derived number as an estimate.
- **CSV is Excel-friendly.** `/audit.csv` writes a UTF-8 BOM and a
  `Content-Disposition: attachment` header, and falls back to the in-memory audit log if
  SQLite is unavailable.
- **Tests are isolated.** `backend/tests/conftest.py` sets `FRESHROUTE_DB=:memory:`
  before importing the app, so the suite never grows the demo ledger.

## Invariants worth protecting

- **`state.py` is the only owner of mutable world data.** Every other module reads and
  writes through it; `main.py` never touches a vehicle field directly (except the reroute
  command, which is the business action itself).
- **`main.py` has no business logic.** It validates input, calls one function per step
  and broadcasts.
- **One tick = 6 simulated minutes, 2 real seconds.** All constants live at the top of
  `simulator.py` and `matcher.py`.
- **One alert and one audit entry per breach.** `state.active_alerts` is the guard.
- **The API contract is stable.** `/state` always returns the full documented shape;
  every command returns JSON and never a traceback (400/404 with a plain `detail`).
- **The frontend can lose the socket without losing the demo.** Polling keeps the UI
  alive, and the server keeps ticking while a dashboard has asked for state recently.
- **History is append-only.** Nothing deletes rows from `runs`, `audit_events` or
  `rescues`; `/reset` only starts a new run. Deleting `backend/data/freshroute.db` is the
  one supported way to start a clean ledger.
