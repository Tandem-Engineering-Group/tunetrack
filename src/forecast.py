"""Component 11 -- forecast the next pass's environment.

Projects density altitude and track temperature for the next run from the
session trend (evening cool-down) and carries an uncertainty band, plus the
tire heat-cycle count. Output -> forecast.

The cool-down model below is a simple assumption; swap for a real weather pull
or a fitted session trend once multiple passes exist.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, now_iso, SYNTHETIC_TAG, DB_PATH
from weather import density_altitude_ft

EVENING_COOLDOWN_C = 2.0   # assumed drop to the next run
DA_UNCERTAINTY_FT = 300.0


def forecast_next(conn, for_window: str = "next run (+~30 min, evening)") -> dict:
    wx = conn.execute(
        "SELECT temp_c, humidity_pct, baro_kpa, density_altitude_ft FROM weather ORDER BY wx_id DESC LIMIT 1"
    ).fetchone()
    track = conn.execute(
        "SELECT surface_temp_c FROM track_state ORDER BY track_id DESC LIMIT 1"
    ).fetchone()
    tire = conn.execute(
        "SELECT heat_cycles FROM tire_state ORDER BY tire_id DESC LIMIT 1"
    ).fetchone()

    next_temp = wx["temp_c"] - EVENING_COOLDOWN_C
    # Humidity rises a touch as it cools; keep baro fixed.
    next_da = density_altitude_ft(next_temp, min(wx["humidity_pct"] + 5, 100), wx["baro_kpa"])
    next_track = (track["surface_temp_c"] - 3.0) if track else None
    heat_cycles = (tire["heat_cycles"] + 1) if tire else None

    cur = conn.execute(
        "INSERT INTO forecast(for_window, da_ft, da_uncertainty, track_temp_c, source, "
        "tire_heat_cycles, created_at) VALUES (?,?,?,?,?,?,?)",
        (for_window, round(next_da), DA_UNCERTAINTY_FT, next_track,
         f"{SYNTHETIC_TAG}: evening cool-down model", heat_cycles, now_iso()),
    )
    conn.commit()
    return {"forecast_id": cur.lastrowid, "for_window": for_window,
            "da_ft": round(next_da), "da_now_ft": round(wx["density_altitude_ft"]),
            "da_uncertainty_ft": DA_UNCERTAINTY_FT, "track_temp_c": next_track,
            "tire_heat_cycles": heat_cycles}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    f = forecast_next(conn)
    print(f"component 11: forecast_id={f['forecast_id']}  DA {f['da_now_ft']} -> {f['da_ft']} "
          f"+/-{f['da_uncertainty_ft']:.0f} ft  track {f['track_temp_c']}C  "
          f"tire heat-cycles {f['tire_heat_cycles']}")
