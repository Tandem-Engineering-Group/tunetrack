"""Seed DUMMY portal reference data: maintenance_items + season_events.

All values are assumptions for the demo (tagged SYNTHETIC) so the maintenance
and season portals render meaningfully. Replace with real service history and
the real 2026 calendar.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, SYNTHETIC_TAG, DB_PATH

DEMO_TODAY = "2026-06-22"

# (system, name, interval_kind, interval_value, last_done, last_value)
MAINT = [
    ("blower", "Supercharger belt", "passes", 25, "2026-06-01", 0),
    ("engine", "Spark plugs", "passes", 15, "2026-05-15", 2),
    ("engine", "Engine oil & filter", "time", 120, "2026-03-10", None),
    ("blower", "Snout / blower oil", "time", 365, "2025-10-01", None),
    ("fuel", "Fuel filter", "miles", 5000, "2026-04-01", 0),
    ("tires", "Drag radials", "heat_cycles", 8, "2026-05-15", 0),
    ("driveline", "Differential fluid", "miles", 3000, "2026-02-01", 0),
]

# (date, track, type, status, target_et, link_latest_run, result_et)
SEASON = [
    ("2026-04-18", "Cecil County", "test", "done", 9.95, False, 10.02),
    ("2026-06-20", "Maple Grove", "test & tune", "done", 9.80, True, None),
    ("2026-07-11", "Maple Grove", "bracket", "next", 9.70, False, None),
    ("2026-08-22", "Atco", "test & tune", "planned", 9.60, False, None),
    ("2026-09-19", "Cecil County", "points event", "planned", 9.50, False, None),
]


def seed(conn) -> None:
    conn.execute("DELETE FROM maintenance_items")
    for system, name, kind, val, last_done, last_value in MAINT:
        conn.execute(
            "INSERT INTO maintenance_items(system, name, interval_kind, interval_value, last_done, last_value, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (system, name, kind, val, last_done, last_value, f"{SYNTHETIC_TAG}: demo interval"),
        )

    latest_run = conn.execute("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    conn.execute("DELETE FROM season_events")
    for date, track, typ, status, target, link, result_et in SEASON:
        rid = latest_run["run_id"] if (link and latest_run) else None
        note = f"{SYNTHETIC_TAG}: demo event" + (f"; result ET {result_et}" if result_et else "")
        conn.execute(
            "INSERT INTO season_events(date, track, type, status, target_et, result_run_id, notes) "
            "VALUES (?,?,?,?,?,?,?)",
            (date, track, typ, status, target, rid, note),
        )
    conn.commit()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    seed(conn)
    n_m = conn.execute("SELECT COUNT(*) AS n FROM maintenance_items").fetchone()["n"]
    n_s = conn.execute("SELECT COUNT(*) AS n FROM season_events").fetchone()["n"]
    print(f"seed: {n_m} maintenance items, {n_s} season events  [{SYNTHETIC_TAG}]")
