# AGENTS.md — FreshRoute project context

> Read this first. It is the shared brain for anyone (human or AI) working on FreshRoute.

## What we are building

**FreshRoute** is a hackathon prototype (4 hours) of a perishable-produce rerouting and
surplus-food-rescue portal.

A live map tracks six refrigerated trucks carrying produce around **Bengaluru, India**.
When a shipment becomes unsafe — cargo temperature above **10 °C**, or the remaining
shelf life is shorter than the time still needed to reach the current destination —
FreshRoute raises an alert, ranks nearby cold storages, community kitchens and shelters,
and lets the dispatcher accept the best reroute with one click. The receiver is notified,
the map redraws the route, and impact counters rise.

Everything is simulated. There is no real GPS, no sensor feed and no live road API.

## Fixed stack (do not change)

| Layer      | Choice                                                        |
| ---------- | ------------------------------------------------------------- |
| Backend    | Python 3.11+, FastAPI, uvicorn, WebSockets                    |
| State      | In-memory, loaded from JSON seed files (no database server)   |
| History    | Embedded SQLite file via stdlib `sqlite3` (`backend/db.py`)   |
| Frontend   | React + Vite, Leaflet via react-leaflet, OpenStreetMap tiles  |
| Realtime   | Full state broadcast over WS `/events` every tick             |
| Fallback   | Frontend polls `GET /state` every 2 s if the socket drops     |
| Routing    | Pre-computed polylines in JSON, no road API                   |
| Tests      | pytest (40 tests)                                             |

No paid APIs, no API keys, no UI frameworks beyond React. "No database server" still
holds: SQLite is an embedded file, not a service, and the live world never waits for it.

## API contract

| Method | Path                               | Purpose                                      |
| ------ | ---------------------------------- | -------------------------------------------- |
| GET    | `/state`                           | Full current state as JSON                   |
| WS     | `/events`                          | Full state pushed every simulator tick       |
| POST   | `/simulate/{scenario}?vehicle_id=` | `reefer_failure` / `delay` / `breakdown`     |
| GET    | `/recommend/{vehicle_id}`          | Top 3 ranked facilities, split plan, nearest explainer |
| POST   | `/reroute`                         | `{vehicle_id, facility_id}` — accept reroute |
| POST   | `/reset`                           | Reload seed data, clear live demo, start a new ledger run |
| GET    | `/analytics`                       | SQLite ledger summary (runs, all-time, recent) |
| GET    | `/audit.csv`                       | Every persisted audit entry as CSV           |

`GET /state` shape:

```json
{
  "vehicles": [],
  "facilities": [],
  "routes": {},
  "alerts": [],
  "notifications": [],
  "audit_log": [],
  "impact": {
    "kg_rescued": 0,
    "meals_saved": 0,
    "events_resolved": 0,
    "value_inr": 0,
    "co2e_kg_avoided": 0
  },
  "impact_rates": {"meals_per_kg": 2.0, "value_inr_per_kg": 30.0, "co2e_kg_per_kg": 2.5},
  "tick": 0,
  "sim_minutes": 0,
  "sim_clock": "08:00"
}
```

## Simulator rules

- One tick every **2 real seconds** = **6 simulated minutes**.
- A moving truck advances along its route at `speed_kmph` (linear interpolation).
- Shelf life drops **0.1 h** per tick normally.
- Temperature drifts **±0.2 °C** around its baseline.
- Scenarios:
  - `reefer_failure`: temperature rises **1.5 °C per tick**.
  - `delay`: shelf life drains **5× faster** plus a one-time traffic-loss penalty and a
    speed reduction, so a breach appears within ~10 s on stage.
  - `breakdown`: speed becomes **0**, so the current trip can never finish.
- Risk breach = `temp_c > 10` **or** `eta_hours > shelf_life_h`.
- One alert and one audit entry per breach — not one per tick.
- `reset` restores the exact seed state (positions, free capacity, counters, logs) and
  starts a new SQLite run; it never deletes ledger history.

## Matching algorithm (weights are constants in `backend/matcher.py`)

Feasible only when `free_kg >= load_kg` **and** `eta_hours < shelf_life_h`.

```
total = 0.40 * proximity
      + 0.30 * capacity_fit
      + 0.20 * cold_chain_match
      + 0.10 * time_margin
```

- `proximity = 1 - distance / max_distance`
- `capacity_fit = load_kg / free_kg`
- `cold_chain_match`: fast produce → kitchen 1.0, shelter 0.9, cold storage 0.6;
  stable produce → cold storage 1.0, kitchen 0.7, shelter 0.6
- `time_margin = (shelf_life_h - eta_hours) / shelf_life_h`

If no single facility can take the whole load, `split_plan` returns a two-stop plan.
`nearest_option` always names the closest site and explains why it did or did not win
(no capacity, no time, or a lower total score).

## Impact estimates (constants in `backend/state.py`)

| Multiplier | Value | Meaning |
| ---------- | ----- | ------- |
| `meals_per_kg` | 2 | 1 kg produce ≈ 2 meals |
| `value_inr_per_kg` | ₹30 | Farm-gate value of mixed produce |
| `co2e_kg_per_kg` | 2.5 | CO₂e avoided per kg not wasted |

Only kilograms are measured; the UI labels every derived number as an estimate.

## Folder map

```
backend/
  main.py          FastAPI wiring: routes, startup, WebSocket broadcast, /analytics, /audit.csv
  models.py        Pydantic models (Vehicle, Facility, Alert, Recommendation, NearestOption, RerouteRequest)
  state.py         Single source of truth, JSON loading, impact rates, audit/notification/rescue helpers
  db.py            Embedded SQLite ledger: runs, audit_events, rescues, analytics, CSV rows (fail-soft)
  simulator.py     Tick engine, movement, temperature, scenario triggers
  risk.py          Breach detection and alert de-duplication
  matcher.py       Haversine, feasibility, scoring, ranking, split plan, nearest explainer
  demo_sim.py      Headless 20-tick demo that prints when the alert fires
  data/            Vehicles, facilities and route polylines (JSON seed) + freshroute.db (git-ignored)
  tests/           pytest suites (conftest.py forces an in-memory DB)
frontend/
  src/
    App.jsx
    main.jsx
    api.js
    format.js
    styles.css
    hooks/useLiveState.js
    components/MapView.jsx
    components/AlertPanel.jsx
    components/RecommendPanel.jsx
    components/NotificationFeed.jsx
    components/ImpactCounters.jsx
    components/AnalyticsPanel.jsx
    components/AuditLog.jsx
    components/DemoControls.jsx
    components/FleetRibbon.jsx
ARCHITECTURE.md    Feature → file/function map, persistence design and the 8-step data flow
README.md          Setup, run, demo script, file-by-file responsibilities
```

## House rules

1. **Header comment on every source file** describing what it is responsible for and
   what it is NOT. JSON has no comment syntax, so seed files carry a `_header` field;
   `package.json` uses a `"//"` field.
2. Plain-English comments. Every function must be explainable to a judge.
3. Keep `backend/main.py` free of business logic — only wiring.
4. No paid APIs or keys. No database server (the embedded SQLite file is allowed). No UI
   component library.
5. Backend stays importable without the frontend; frontend degrades to polling if WS fails.
6. After each phase, state how to run it and what should be visible.

## Commands (Windows, from project root)

```powershell
# one-time setup
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
cd frontend; npm install; npm run build; cd ..

# run the whole app (FastAPI serves frontend/dist)
.venv\Scripts\python -m uvicorn backend.main:app --reload --port 8000

# tests
.venv\Scripts\python -m pytest backend/tests -q

# headless simulation demo
.venv\Scripts\python -m backend.demo_sim
```

Open <http://localhost:8000>. API docs at <http://localhost:8000/docs>.

## Demo script (90 seconds)

1. Show six trucks and ten facilities on the Bengaluru map.
2. Select a truck, press **Reefer failure**. It turns red within ~8 s and the shelf-life
   countdown starts.
3. The recommendation panel ranks three facilities with score bars, a one-line "why" and
   a "why not the nearest?" note.
4. Press **Accept Reroute**. A bold green animated polyline appears, the receiver feed gets
   an "Incoming …" message, the audit log records it, impact counters jump to 1,800 kg /
   3,600 meals / ₹54,000 est. / 4,500 kg CO₂e and the SQLite ledger adds the run.
5. Press **Reset** to restore the demo (clock 08:00, zero counters). The ledger keeps the
   earlier run, so a second pass shows two runs and the all-time total.

## Non-goals

- Real GPS, IoT sensors, traffic or road routing APIs.
- Authentication, roles, multi-tenant persistence or multi-city scale.
- Production hardening. This is a demo that must be reliable on stage.
