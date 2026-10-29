# FreshRoute

**Rescue routing for perishable produce — a 4-hour hackathon prototype.**

FreshRoute is a live map of six refrigerated trucks moving produce around Bengaluru.
When a load becomes unsafe — cargo warmer than **10 °C**, or the remaining shelf life
shorter than the time still needed to reach the current destination — the dispatcher
gets an alert, a ranked list of cold storages, community kitchens and shelters, and a
one-click reroute. Accept one and the map redraws the route, the receiver is notified,
the audit trail grows and the impact counters rise.

Everything is simulated: no GPS, no IoT sensors, no road-routing API, no database
server. Six vehicles, ten facilities and six pre-computed polylines live in JSON files
and are advanced by a tick loop inside the FastAPI process.

An **embedded SQLite ledger** (`backend/data/freshroute.db`, Python's stdlib `sqlite3`)
quietly records every run, breach, scenario and rescue. It survives a reset and a
restart, powers the *Impact ledger* panel and the CSV export, and fails soft — if the
file is read-only the live demo keeps running with nothing but a console warning.

---

## Quick start (one command, production build)

From the project root in PowerShell:

```powershell
# 1. one-time setup
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
npm.cmd install --prefix frontend
npm.cmd run build --prefix frontend

# 2. run the whole app: FastAPI serves frontend/dist and the API
.venv\Scripts\python -m uvicorn backend.main:app --reload --port 8000
```

Open <http://localhost:8000>. Interactive API docs: <http://localhost:8000/docs>.
A liveness probe is at `/health`.

> On Windows, use `npm.cmd` (PowerShell can block `npm.ps1` with the execution-policy error).

## Development mode (two terminals, hot reload)

```powershell
# terminal 1 — API + simulator
.venv\Scripts\python -m uvicorn backend.main:app --reload --port 8000

# terminal 2 — Vite dev server on :5173, proxying /state, /simulate,
# /recommend, /reroute, /reset, /analytics, /audit.csv and the /events
# WebSocket to :8000
npm.cmd run dev --prefix frontend
```

Open <http://localhost:5173>. Rebuild `frontend/dist` (`npm.cmd run build --prefix frontend`)
before demoing the single-command version.

The ledger file defaults to `backend/data/freshroute.db`. Point it elsewhere (or at
`:memory:`) with the `FRESHROUTE_DB` environment variable; that is how the tests stay
isolated.

## Tests

```powershell
.venv\Scripts\python -m pytest backend/tests -q
```

40 tests cover the matching algorithm (including the "why not the nearest?" explainer),
the risk engine, the simulator (movement, arrival, reload, reset) and the
HTTP/WebSocket contract, the SQLite ledger and CSV export. Tests use a throwaway
in-memory database (`backend/tests/conftest.py`) so they never touch the demo ledger.

## Headless simulation demo

```powershell
.venv\Scripts\python -m backend.demo_sim
```

Runs 20 ticks in a few milliseconds, triggers a reefer failure on one truck after
tick 5, and prints the tick, the breach and the top recommendation — useful when you
cannot look at a browser.

---

## Demo script (90 seconds)

1. Open <http://localhost:8000>. Six trucks and ten facilities are on the Bengaluru map;
   the header clock reads **08:00** and the badge says **Live**.
2. Click a truck (for example **KA-01 Reefer 1**, 1,800 kg of tomato) to select it.
3. Press **Reefer failure** (or **Traffic delay**). Within about 2–12 seconds the truck
   turns red, its card appears under *Active alerts*, and the recommendation panel
   ranks three facilities with score bars and a plain-English "why".
4. Press **Accept reroute** on the top card. A toast confirms the dispatch, a bold green
   animated polyline appears, the receiver feed shows *"Incoming 1800 kg tomato, ETA 1.4 h."*,
   the impact counters jump (1,800 kg, 3,600 meals, ₹54,000 estimated value, 4,500 kg CO₂e
   avoided, 1 event) and the audit trail records the decision. The panel switches to
   **Resolved**, the impact ledger adds the run, and *Download full audit CSV* exports
   every run so far.
5. Press **↺ Reset demo**. The clock returns to **08:00**, the counters to zero, every
   truck to **OK** and every scenario flag is cleared — ready for the next judge. The
   ledger is deliberately **not** wiped: it now shows two demo runs and keeps the
   all-time total.

Optional proof of resilience: open `http://localhost:8000/?poll=1`. The badge reads
**Polling**, no WebSocket is opened, and the world still advances from `GET /state`
every 2 seconds.

### Notes for the presenter

- One tick every **2 real seconds** = **6 simulated minutes**.
- Trucks unload at their destination, then take on a fresh shipment a few ticks later,
  so the map never goes flat during a long session. **Reset** still restores the exact
  seed state.
- The simulation clock pauses when no dashboard has asked for state in the last
  12 seconds. Open the page and the world starts from where it was; you never walk up
  to a map where every truck has already delivered.
- If the WebSocket drops, the UI polls `GET /state` every 2 s and retries the socket
  every 5 s; the badge switches from **Live** to **Polling** and back on its own.

---

## API

| Method | Path                               | Purpose                                       |
| ------ | ---------------------------------- | --------------------------------------------- |
| GET    | `/state`                           | Full current state as JSON                    |
| WS     | `/events`                          | Full state pushed every simulator tick        |
| GET    | `/recommend/{vehicle_id}`          | Top 3 ranked facilities, a two-stop split plan and a "why not the nearest?" explainer |
| POST   | `/simulate/{scenario}?vehicle_id=` | `reefer_failure`, `delay` or `breakdown`      |
| POST   | `/reroute`                         | `{vehicle_id, facility_id[, via_facility_id]}`|
| POST   | `/reset`                           | Reload the seed data, start a new ledger run  |
| GET    | `/analytics`                       | SQLite ledger: runs, all-time impact, recent rescues, top receivers |
| GET    | `/audit.csv`                       | Every persisted audit entry as an Excel-friendly CSV |
| GET    | `/health`                          | `{status, tick, clients}` liveness probe      |

```powershell
curl "http://localhost:8000/simulate/reefer_failure?vehicle_id=V1" -Method Post
curl "http://localhost:8000/recommend/V1"
curl "http://localhost:8000/reroute" -Method Post -ContentType "application/json" `
     -Body '{"vehicle_id":"V1","facility_id":"F4"}'
curl "http://localhost:8000/analytics"
curl "http://localhost:8000/audit.csv" -OutFile audit.csv
curl "http://localhost:8000/reset" -Method Post
```

---

## File-by-file responsibilities

### Backend

| File | Responsibility (and what it is **not**) |
| ---- | --------------------------------------- |
| `backend/main.py` | FastAPI wiring: endpoints, WebSocket fan-out, tick loop, static `dist/` serving. **No** business logic. |
| `backend/models.py` | Pydantic shapes for vehicles, facilities, alerts, recommendations, split plans and requests. No I/O. |
| `backend/state.py` | The single in-memory source of truth: JSON loading, snapshot, audit, notifications, impact, reset. No scoring or movement. |
| `backend/db.py` | Embedded SQLite ledger: runs, audit events, rescues, analytics aggregation and CSV rows. Every public call fails soft, so a disk problem cannot stop the demo. No live simulation state. |
| `backend/simulator.py` | Tick engine: interpolation along polylines, temperature drift, shelf-life burn, the three scenarios, arrival and reload. No breach decisions. |
| `backend/risk.py` | Breach detection (temp > 10 °C or ETA > shelf life), status changes, one alert + one audit per breach. No ranking. |
| `backend/matcher.py` | Haversine, feasibility, the four weighted score components, top-3 ranking, two-stop split plan, nearest-facility explainer, rescue polyline builder. No HTTP. |
| `backend/demo_sim.py` | Headless 20-tick demo that prints the alert and the top recommendation. Not used by the app. |
| `backend/data/vehicles.json` | Six seed trucks with produce, load, temperature, shelf life, speed, route and destination. |
| `backend/data/facilities.json` | Ten seed facilities with type, position, capacity, free space and contact. |
| `backend/data/routes.json` | Six pre-computed polylines (the only "road network"). |
| `backend/data/freshroute.db` | Created at first run. The SQLite ledger; git-ignored, never committed. |
| `backend/tests/` | pytest suites: matching, risk, simulator, HTTP/WebSocket contract, ledger and CSV. |

### Frontend

| File | Responsibility (and what it is **not**) |
| ---- | --------------------------------------- |
| `frontend/src/main.jsx` | Mounts React and imports Leaflet's stylesheet. Does nothing else. |
| `frontend/src/App.jsx` | 70/30 layout, selected truck, toasts, scenario/reset handlers. No map or panel internals. |
| `frontend/src/api.js` | One small fetch wrapper per endpoint. No state. |
| `frontend/src/format.js` | Presentation helpers (hours, temperature, kilograms, rupees, CO₂e, facility labels, time). No calculations. |
| `frontend/src/hooks/useLiveState.js` | WebSocket `/events`, 2 s polling fallback, 5 s socket retry, `?poll=1` switch. No rendering. |
| `frontend/src/components/MapView.jsx` | Leaflet map, div-icon markers, grey routes, animated green rescue routes in their own pane, legend, fly-to. No data fetching. |
| `frontend/src/components/DemoControls.jsx` | The three scenario buttons, Reset, selected-truck chip, Live/Polling badge. Calls handlers from `App`. |
| `frontend/src/components/AlertPanel.jsx` | Unresolved alerts with live cargo/shelf readout and an ETA-vs-shelf-life runway bar; click to select and pan. |
| `frontend/src/components/RecommendPanel.jsx` | Fetches recommendations once per alert, renders score bars, "why" sentence, "why not the nearest?" explainer, scoring model and Accept Reroute / split plan. |
| `frontend/src/components/NotificationFeed.jsx` | Receiver notifications, newest first. |
| `frontend/src/components/ImpactCounters.jsx` | Five live counters: kg, meals, estimated ₹ value, estimated CO₂e avoided, events resolved, plus the estimate basis. |
| `frontend/src/components/AnalyticsPanel.jsx` | SQLite impact ledger: demo runs, all-time kg/₹, current run, recent rescues, top receiver and the CSV download. |
| `frontend/src/components/AuditLog.jsx` | Collapsible, newest-first audit trail plus CSV export. |
| `frontend/src/styles.css` | All dashboard styling, including the responsive stacked layout. No CSS framework. |

### Root

| File | Purpose |
| ---- | ------- |
| `AGENTS.md` | Shared project context, house rules and commands for humans and AI. |
| `ARCHITECTURE.md` | Feature → file/function map and the 8-step data flow. |
| `prompts.txt` | The original phase-by-phase build prompt. |
| `requirements.txt` | Pinned backend dependencies. |

---

## Impact assumptions

Kilograms are the only measured quantity. Everything else is a clearly labelled
estimate, defined once in `backend/state.py` (`IMPACT_RATES`) and echoed to the UI:

| Multiplier | Value | Meaning |
| ---------- | ----- | ------- |
| `meals_per_kg` | 2 | One kilogram of produce ≈ two meals |
| `value_inr_per_kg` | ₹30 | Farm-gate value of mixed produce |
| `co2e_kg_per_kg` | 2.5 | Emissions avoided per kilogram not wasted |

---

## Design decisions worth explaining to a judge

- **Explainable scoring, not a black box.** Every recommendation shows the same four
  components the server used: proximity 0.40, capacity fit 0.30, cold-chain match 0.20,
  time margin 0.10.
- **Feasibility first.** A facility is only listed if it has room for the whole load
  **and** the cargo survives the trip; otherwise the API returns a two-stop split plan.
- **A rescue is run at cruising speed.** ETAs for an alternative destination use the
  truck's healthy `cruise_kmph`, because the load is handed to a sound vehicle. That is
  also the speed restored when the dispatcher accepts.
- **One alert per breach, one audit entry per event.** Tick-by-tick spam would make the
  audit trail unreadable.
- **Time is precious on stage.** The traffic hold drains shelf life 5× faster until the
  breach is flagged, so a delay alert appears within a few seconds, then the countdown
  returns to normal while the dispatcher reads the options.
- **The nearest facility is not automatically the answer.** The recommendation response
  carries a `nearest` object so the UI can say *why* the closest site lost: no room for
  the load, no time to get there, or simply a lower total score. Judges ask this.
- **Persistence without a database server.** SQLite is embedded, file-based and in the
  Python standard library, so `git clone` and run still need zero setup. The live world
  stays in memory, so a slow disk can never stall a tick. `/reset` starts a new run but
  never deletes history — the ledger is the demo's memory.

## Non-goals

Real GPS, sensors, traffic or road routing; authentication, roles, multi-tenant
persistence; multi-city scale; production hardening. This is a demo that must be
reliable on stage.
