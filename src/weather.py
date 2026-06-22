"""Component 05 -- per-pass air model: density altitude.

Density altitude is the single most important correction for fair cross-run
comparison. It is now computed straight from the LOG (the car records
Barometric Pressure + Ambient Air Temp), so no Kestrel/manual entry is needed.
Relative humidity isn't logged, so it's assumed (DA is only weakly sensitive to
it); override via the humidity_pct arg or by passing wx= explicitly.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import math
import pathlib

from db import connect, latest_run_id, log_frame, DB_PATH, SYNTHETIC_TAG

ASSUMED_RH = 50.0
# Fallback only (no baro/ambient in the log) -- otherwise we read from the log.
DEMO_WX = dict(temp_c=29.0, humidity_pct=ASSUMED_RH, baro_kpa=99.2)


def saturation_vapor_pressure_hpa(temp_c: float) -> float:
    """Tetens approximation, hPa."""
    return 6.1078 * 10.0 ** (7.5 * temp_c / (237.3 + temp_c))


def density_altitude_ft(temp_c: float, humidity_pct: float, baro_kpa: float) -> float:
    """Density altitude in feet from station pressure (kPa), temperature (C),
    and relative humidity (%). Uses pressure altitude + ISA temperature
    deviation with a humidity (virtual-temperature) correction."""
    station_hpa = baro_kpa * 10.0
    # Pressure altitude (ft)
    pa_ft = 145366.45 * (1.0 - (station_hpa / 1013.25) ** 0.190284)
    # Vapor pressure and virtual temperature (humidity lowers density -> raises DA)
    e = (humidity_pct / 100.0) * saturation_vapor_pressure_hpa(temp_c)
    tk = temp_c + 273.15
    tv_k = tk / (1.0 - (e / station_hpa) * (1.0 - 0.622))
    tv_c = tv_k - 273.15
    # ISA temperature at this pressure altitude, and the standard DA relation
    isa_c = 15.0 - 1.98 * (pa_ft / 1000.0)
    da = pa_ft + 118.8 * (tv_c - isa_c)
    return da


def weather_from_log(conn, run_id: int, humidity_pct: float = ASSUMED_RH):
    """Derive (temp, humidity, baro) from the log: median Barometric Pressure +
    Ambient Air Temp. Returns (wx_dict, source) or (None, None) if unavailable."""
    row = conn.execute("SELECT log_id FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if not row:
        return None, None
    df = log_frame(conn, row["log_id"])
    if "baro_kpa" in df.columns and "ambient_temp_c" in df.columns and len(df):
        wx = {"temp_c": round(float(df["ambient_temp_c"].median()), 1),
              "humidity_pct": humidity_pct,
              "baro_kpa": round(float(df["baro_kpa"].median()), 2)}
        return wx, "VCM log (baro + ambient temp); RH assumed"
    return None, None


def record_weather(conn, run_id: int | None = None, wx: dict | None = None,
                   humidity_pct: float = ASSUMED_RH) -> int:
    run_id = run_id or latest_run_id(conn)
    row = conn.execute("SELECT ts_start FROM runs WHERE run_id=?", (run_id,)).fetchone() if run_id else None
    obs_time = row["ts_start"] if row else None

    source = "manual / provided"
    if wx is None and run_id is not None:
        wx, source = weather_from_log(conn, run_id, humidity_pct)
    if wx is None:
        wx, source = dict(DEMO_WX), "fallback (no baro/ambient in log)"

    da = round(density_altitude_ft(**wx), 0)
    conn.execute("DELETE FROM weather")  # demo: single observation
    cur = conn.execute(
        "INSERT INTO weather(obs_time, temp_c, humidity_pct, baro_kpa, density_altitude_ft) "
        "VALUES (?,?,?,?,?)",
        (obs_time, wx["temp_c"], wx["humidity_pct"], wx["baro_kpa"], da),
    )
    conn.commit()
    record_weather.last_source = source
    return cur.lastrowid


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    wid = record_weather(conn)
    w = conn.execute("SELECT * FROM weather WHERE wx_id=?", (wid,)).fetchone()
    print(f"component 05: wx_id={wid}  source={getattr(record_weather,'last_source','?')}  "
          f"{w['temp_c']}C / {w['humidity_pct']}% RH / {w['baro_kpa']}kPa  "
          f"-> DA {w['density_altitude_ft']:.0f} ft")
