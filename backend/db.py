"""
FreshRoute persistence and analytics store.

Responsible for: an embedded SQLite database that keeps every demo run, audit
entry and rescue, and answers the aggregate questions the ledger panel asks
(all-time kilograms, rupee value, CO2e, busiest facilities).
NOT responsible for: the live simulation state (still in memory), scoring,
risk rules or HTTP. The demo must keep working even if this file is read-only,
so every public function fails soft and returns None/{} instead of raising.

Why SQLite and not a database server: the hackathon stack forbids a DB server,
and a single file keeps `git clone && run` working with zero setup. The live
world stays in memory, so a slow disk can never stall a tick.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent / "data" / "freshroute.db"
# Override for tests or a hosted demo: FRESHROUTE_DB=:memory: or an absolute path.
DB_PATH = Path(os.environ.get("FRESHROUTE_DB", str(DEFAULT_PATH)))

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'demo'
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    entry_id TEXT,
    sim_clock TEXT,
    timestamp TEXT NOT NULL,
    event TEXT NOT NULL,
    vehicle_id TEXT,
    details TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rescues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    timestamp TEXT NOT NULL,
    sim_clock TEXT,
    vehicle_id TEXT NOT NULL,
    kg REAL NOT NULL,
    meals REAL NOT NULL,
    value_inr REAL NOT NULL,
    co2e_kg REAL NOT NULL,
    facility_ids TEXT NOT NULL DEFAULT '',
    facility_names TEXT NOT NULL DEFAULT '',
    facility_types TEXT NOT NULL DEFAULT '',
    facility_kg TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_audit_run ON audit_events(run_id);
CREATE INDEX IF NOT EXISTS idx_rescues_run ON rescues(run_id);
"""

_connection: sqlite3.Connection | None = None
_lock = threading.RLock()
_last_error: str | None = None


def _now() -> str:
    """UTC timestamp, same format the rest of the app uses."""
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    """Open (once) and migrate the SQLite file. Safe to call from any thread."""
    global _connection
    with _lock:
        if _connection is None:
            if str(DB_PATH) != ":memory:":
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            connection.row_factory = sqlite3.Row
            connection.executescript(SCHEMA)
            # Older demo ledgers predate per-stop kilograms. Add the column in
            # place so an existing history keeps working after the upgrade.
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(rescues)")}
            if "facility_kg" not in columns:
                connection.execute(
                    "ALTER TABLE rescues ADD COLUMN facility_kg TEXT NOT NULL DEFAULT ''"
                )
            connection.commit()
            _connection = connection
        return _connection


def _guard(function, *args, **kwargs):
    """
    Run one database action, but never let a disk problem break the demo.
    The first failure is printed once so it is still noticeable in the console.
    """
    global _last_error
    try:
        return function(*args, **kwargs)
    except Exception as exc:  # pragma: no cover - only runs when the disk fails
        message = f"{type(exc).__name__}: {exc}"
        if message != _last_error:
            print(f"[freshroute.db] persistence disabled: {message}")
        _last_error = message
        return None


def init() -> None:
    """Create the schema at start-up so the first request is never slow."""
    _guard(_connect)


def start_run(label: str = "demo") -> int | None:
    """Begin a new demo run. Older runs stay in the ledger for the analytics panel."""
    return _guard(_start_run, label)


def _start_run(label: str) -> int:
    connection = _connect()
    with _lock, connection:
        cursor = connection.execute(
            "INSERT INTO runs (started_at, label) VALUES (?, ?)", (_now(), label)
        )
    return int(cursor.lastrowid)


def current_run_id() -> int | None:
    """The newest run, created lazily if a caller logs before POST /reset."""
    return _guard(_current_run_id)


def _current_run_id() -> int:
    connection = _connect()
    with _lock:
        row = connection.execute("SELECT id FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    return _start_run("demo")


def log_audit(entry: dict, run_id: int | None = None) -> None:
    """Persist one audit entry exactly as the UI saw it."""
    _guard(_log_audit, entry, run_id)


def _log_audit(entry: dict, run_id: int | None) -> None:
    run = run_id or _current_run_id()
    connection = _connect()
    with _lock, connection:
        connection.execute(
            """
            INSERT INTO audit_events
                (run_id, entry_id, sim_clock, timestamp, event, vehicle_id, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run,
                entry.get("id"),
                entry.get("sim_clock"),
                entry.get("timestamp") or _now(),
                entry.get("event", "UNKNOWN"),
                entry.get("vehicle_id"),
                entry.get("details", ""),
            ),
        )


def log_rescue(
    *,
    run_id: int | None,
    timestamp: str,
    sim_clock: str,
    vehicle_id: str,
    kg: float,
    meals: float,
    value_inr: float,
    co2e_kg: float,
    facility_ids: list[str],
    facility_names: list[str],
    facility_types: list[str],
    facility_kg: list[float] | None = None,
) -> None:
    """Persist one accepted reroute so impact survives a reset or a restart."""
    _guard(
        _log_rescue,
        run_id,
        timestamp,
        sim_clock,
        vehicle_id,
        kg,
        meals,
        value_inr,
        co2e_kg,
        facility_ids,
        facility_names,
        facility_types,
        facility_kg or [],
    )


def _log_rescue(
    run_id: int | None,
    timestamp: str,
    sim_clock: str,
    vehicle_id: str,
    kg: float,
    meals: float,
    value_inr: float,
    co2e_kg: float,
    facility_ids: list[str],
    facility_names: list[str],
    facility_types: list[str],
    facility_kg: list[float],
) -> None:
    run = run_id or _current_run_id()
    connection = _connect()
    with _lock, connection:
        connection.execute(
            """
            INSERT INTO rescues
                (run_id, timestamp, sim_clock, vehicle_id, kg, meals, value_inr,
                 co2e_kg, facility_ids, facility_names, facility_types, facility_kg)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run,
                timestamp,
                sim_clock,
                vehicle_id,
                float(kg),
                float(meals),
                float(value_inr),
                float(co2e_kg),
                ",".join(facility_ids),
                ",".join(facility_names),
                ",".join(facility_types),
                ",".join(f"{float(stop_kg):.1f}" for stop_kg in facility_kg),
            ),
        )


def _split_types(value: str) -> list[str]:
    return [part for part in (value or "").split(",") if part]


def _split_kg(value: str) -> list[float]:
    """Per-stop kilograms stored as a comma-separated string, newest schema."""
    try:
        return [float(part) for part in (value or "").split(",") if part]
    except ValueError:
        return []


def analytics(recent_limit: int = 5) -> dict:
    """Aggregate every run, plus the current run and the most recent rescues."""
    return _guard(_analytics, recent_limit) or {}


def _analytics(recent_limit: int) -> dict:
    connection = _connect()
    with _lock:
        run_count = connection.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        current_row = connection.execute(
            "SELECT id FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        current_id = int(current_row["id"]) if current_row else None

        totals = connection.execute(
            """
            SELECT COUNT(*) AS rescues,
                   COALESCE(SUM(kg), 0) AS kg,
                   COALESCE(SUM(meals), 0) AS meals,
                   COALESCE(SUM(value_inr), 0) AS value_inr,
                   COALESCE(SUM(co2e_kg), 0) AS co2e_kg
            FROM rescues
            """
        ).fetchone()

        current = connection.execute(
            """
            SELECT COUNT(*) AS rescues,
                   COALESCE(SUM(kg), 0) AS kg,
                   COALESCE(SUM(value_inr), 0) AS value_inr
            FROM rescues WHERE run_id = ?
            """,
            (current_id,),
        ).fetchone()

        recent_rows = connection.execute(
            """
            SELECT sim_clock, vehicle_id, kg, value_inr, facility_names, timestamp
            FROM rescues ORDER BY id DESC LIMIT ?
            """,
            (recent_limit,),
        ).fetchall()

        all_rows = connection.execute(
            "SELECT kg, facility_names, facility_types, facility_kg FROM rescues"
        ).fetchall()

        run_rows = connection.execute(
            """
            SELECT r.id, r.started_at, r.label,
                   COALESCE(SUM(s.kg), 0) AS kg,
                   COUNT(s.id) AS rescues
            FROM runs r
            LEFT JOIN rescues s ON s.run_id = r.id
            GROUP BY r.id
            ORDER BY r.id DESC
            LIMIT 12
            """
        ).fetchall()

    by_type: dict[str, dict] = {}
    by_facility: dict[str, dict] = {}
    for row in all_rows:
        names = _split_types(row["facility_names"])
        types = _split_types(row["facility_types"])
        stop_kgs = _split_kg(row["facility_kg"])
        # Ledgers written before per-stop kilograms existed stored only the
        # total; fall back to it so old history still aggregates.
        if len(stop_kgs) != len(names):
            stop_kgs = [float(row["kg"] or 0)] * len(names)

        for facility_type, stop_kg in zip(types, stop_kgs):
            bucket = by_type.setdefault(facility_type, {"type": facility_type, "rescues": 0, "kg": 0.0})
            bucket["rescues"] += 1
            bucket["kg"] = round(bucket["kg"] + stop_kg, 1)
        for name, stop_kg in zip(names, stop_kgs):
            bucket = by_facility.setdefault(name, {"name": name, "rescues": 0, "kg": 0.0})
            bucket["rescues"] += 1
            bucket["kg"] = round(bucket["kg"] + stop_kg, 1)

    history = [
        {
            "run_id": int(row["id"]),
            "started_at": row["started_at"],
            "label": row["label"],
            "kg_rescued": round(float(row["kg"]), 1),
            "rescues": int(row["rescues"]),
            "is_current": int(row["id"]) == current_id,
        }
        for row in reversed(run_rows)
    ]

    return {
        "runs": int(run_count),
        "runs_history": history,
        "current_run": {
            "id": current_id,
            "rescues": int(current["rescues"]),
            "kg_rescued": round(float(current["kg"]), 1),
            "value_inr": round(float(current["value_inr"])),
        },
        "all_time": {
            "rescues": int(totals["rescues"]),
            "kg_rescued": round(float(totals["kg"]), 1),
            "meals_saved": round(float(totals["meals"])),
            "value_inr": round(float(totals["value_inr"])),
            "co2e_kg_avoided": round(float(totals["co2e_kg"]), 1),
        },
        "by_facility_type": sorted(by_type.values(), key=lambda item: item["kg"], reverse=True),
        "top_facilities": sorted(
            by_facility.values(), key=lambda item: item["kg"], reverse=True
        )[:3],
        "recent_rescues": [
            {
                "sim_clock": row["sim_clock"],
                "vehicle_id": row["vehicle_id"],
                "kg": round(float(row["kg"]), 1),
                "value_inr": round(float(row["value_inr"])),
                "facility_names": _split_types(row["facility_names"]),
                "timestamp": row["timestamp"],
            }
            for row in recent_rows
        ],
    }


def audit_rows() -> list[dict]:
    """Every persisted audit entry, oldest first, for CSV export."""
    return _guard(_audit_rows) or []


def _audit_rows() -> list[dict]:
    connection = _connect()
    with _lock:
        rows = connection.execute(
            """
            SELECT run_id, sim_clock, timestamp, event, vehicle_id, details
            FROM audit_events ORDER BY id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]
