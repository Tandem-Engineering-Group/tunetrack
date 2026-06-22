"""Component 13 -- reports + the read-only JSON the portals consume.

Reads the catalog and writes web/data.json: per-pass scorecards (power +
traction), the green-light readiness, the retune advisory sheet, deep-analysis
maps, the forecast, maintenance status, and the season trend. Portals render
this file; they never touch the calibration or the DB directly.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import pathlib

import pandas as pd

from db import connect, run_frame, now_iso, ROOT, SYNTHETIC_TAG, DB_PATH
from seed import DEMO_TODAY
from greenlight import readiness as greenlight_readiness
from config import load_config

ATM_KPA = 101.3
OUT = ROOT / "web" / "data.json"

# Channel -> (label, plain-English meaning, unit) for the engine portal.
# Order roughly follows the airflow path. Only channels present in the log are shown.
SENSORS = {
    "engine_rpm": ("Engine speed", "Crankshaft RPM — how fast the engine is turning.", "rpm"),
    "vehicle_speed": ("Vehicle speed", "Road speed from the non-driven wheels.", "mph"),
    "trans_gear": ("Gear", "Current trans gear — context for where boost/knock happen in the pull.", ""),
    "baro_kpa": ("Barometric", "Ambient air pressure; boost is measured above this, not a fixed 101 kPa.", "kPa"),
    "map_kpa": ("Manifold pressure", "Absolute pressure in the intake; above barometric is boost.", "kPa"),
    "boost_psi": ("Boost (true)", "MAP minus barometric — the real boost the blower is making.", "psi"),
    "sc_bypass_pos": ("Blower bypass", "Supercharger bypass position; closes to build boost, opens off-throttle.", "%"),
    "total_airflow": ("Airflow", "Total mass airflow into the engine — load indicator.", "g/s"),
    "tps_pct": ("Throttle", "Driver throttle command; 100% is wide open.", "%"),
    "aircharge_temp_c": ("Intake air temp", "Charge-air temp after the blower/intercooler — heat soak risk.", "deg C"),
    "actual_spark_deg": ("Actual spark", "Timing the PCM is actually running right now.", "deg"),
    "mbt_spark_deg": ("MBT spark", "Best-torque timing target; the gap to Actual Spark is your knock margin.", "deg"),
    "knock_retard_total": ("Knock retard", "Timing pulled to stop detonation — want ~0.", "deg"),
    "knock_sensor_1": ("Knock sensor", "Raw knock-sensor activity; spikes flag detonation events.", "V"),
    "eq_commanded": ("Commanded EQ", "Air/fuel the tune is asking for; >1 is rich.", "EQ"),
    "wb_eq_1": ("Measured EQ", "What the wideband actually sees; should track command.", "EQ"),
    "fuel_press_kpa": ("Fuel pressure", "Rail pressure; a drop under load means the pump is signing off.", "kPa"),
    "fuel_press_desired_kpa": ("Desired fuel press", "Commanded rail pressure — compare to actual to catch a fueling shortfall.", "kPa"),
    "inj_duty_pct": ("Injector duty", "Derived from pulse width; near 100% means no fuel headroom left.", "%"),
    "egt_c": ("Exhaust temp", "Exhaust gas temperature — fueling/timing heat indicator.", "deg C"),
    "ect_c": ("Coolant temp", "Engine coolant temperature.", "deg C"),
    "ltr_coolant_c": ("LTR coolant", "Low-temp radiator loop feeding the intercooler.", "deg C"),
    "ltr_pump_rpm": ("LTR pump", "Intercooler coolant pump speed.", "rpm"),
    "oil_temp_c": ("Oil temp", "Engine oil temperature.", "deg C"),
    "oil_press_kpa": ("Oil pressure", "Engine oil pressure.", "kPa"),
    "torque_actual": ("Actual torque", "Engine torque estimate; vs Expected shows if a limiter is holding it back.", "N m"),
    "cm_voltage": ("System voltage", "Control-module supply voltage.", "V"),
}


def _d(row):
    return dict(row) if row is not None else None


def _series(df: pd.DataFrame, n: int = 120) -> dict:
    if df.empty:
        return {}
    idx = list(range(0, len(df), max(1, len(df) // n)))
    s = df.iloc[idx]

    def col(c, nd):
        return s[c].round(nd).tolist() if c in s.columns else None

    boost = (s["boost_psi"] if "boost_psi" in s.columns else (s["map_kpa"] - ATM_KPA) / 6.895).round(1)
    ws = ["wheel_speed_fl", "wheel_speed_fr", "wheel_speed_rl", "wheel_speed_rr"]
    if all(c in s.columns for c in ws):
        front = (s["wheel_speed_fl"] + s["wheel_speed_fr"]) / 2
        rear = (s["wheel_speed_rl"] + s["wheel_speed_rr"]) / 2
        slip = (((rear - front) / front.where(front > 3) * 100)).round(1).fillna(0).tolist()
    else:
        slip = [None] * len(s)   # no wheel-speed channels -> live slip unavailable
    return {
        "t": s["t_rel"].round(2).tolist(),
        "engine_rpm": s["engine_rpm"].round(0).tolist(),
        "vehicle_speed": col("vehicle_speed", 1),
        "boost_psi": boost.tolist(),
        "knock": col("knock_retard_total", 2),
        "actual_spark": col("actual_spark_deg", 1),
        "eq_cmd": col("eq_commanded", 3),
        "eq_meas": col("wb_eq_1", 3),
        "inj_duty": col("inj_duty_pct", 1),
        "fuel_press": col("fuel_press_kpa", 0),
        "rear_slip_pct": slip,
    }


def _engine_snapshot(df: pd.DataFrame) -> list:
    if df.empty:
        return []
    boost = (df["map_kpa"] - ATM_KPA) / 6.895
    peak_i = (df["engine_rpm"] * boost.clip(lower=0)).idxmax()
    row = df.loc[peak_i]
    out = []
    for ch, (label, meaning, unit) in SENSORS.items():
        if ch in df.columns:
            out.append({"channel": ch, "label": label, "meaning": meaning,
                        "unit": unit, "value_at_peak": round(float(row[ch]), 2)})
    return out


def _maintenance(conn) -> list:
    today = dt.date.fromisoformat(DEMO_TODAY)
    n_runs = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    hc = conn.execute("SELECT heat_cycles FROM tire_state ORDER BY tire_id DESC LIMIT 1").fetchone()
    counters = {"passes": 12 + n_runs, "miles": 4200, "heat_cycles": (hc["heat_cycles"] if hc else 0)}
    items = []
    for it in conn.execute("SELECT * FROM maintenance_items ORDER BY item_id"):
        kind, interval = it["interval_kind"], it["interval_value"]
        if kind == "time":
            last = dt.date.fromisoformat(it["last_done"]) if it["last_done"] else today
            used, detail = (today - last).days, f"{(today - last).days} of {interval:.0f} days"
        else:
            cur = counters.get(kind, 0)
            used = cur - (it["last_value"] or 0)
            detail = f"{used:.0f} of {interval:.0f} {kind}"
        pct = used / interval if interval else 0
        status = "overdue" if pct >= 1.0 else "due-soon" if pct >= 0.8 else "ok"
        items.append({"system": it["system"], "name": it["name"], "kind": kind,
                      "used_pct": round(min(pct, 1.5) * 100), "status": status, "detail": detail})
    return items


def _season(conn) -> list:
    out = []
    for ev in conn.execute("SELECT * FROM season_events ORDER BY date"):
        result_et = None
        if ev["result_run_id"]:
            r = conn.execute(
                "SELECT t.quarter_et FROM eval_results e JOIN timeslips t ON t.slip_id=e.slip_id "
                "WHERE e.run_id=?", (ev["result_run_id"],)).fetchone()
            result_et = r["quarter_et"] if r else None
        if result_et is None and ev["notes"] and "result ET" in ev["notes"]:
            result_et = float(ev["notes"].split("result ET")[-1].strip())
        out.append({"date": ev["date"], "track": ev["track"], "type": ev["type"],
                    "status": ev["status"], "target_et": ev["target_et"], "result_et": result_et})
    return out


def build_report(conn) -> dict:
    build = _d(conn.execute("SELECT * FROM build_state ORDER BY state_id DESC LIMIT 1").fetchone())

    runs = []
    for r in conn.execute("SELECT * FROM runs ORDER BY run_id"):
        rid = r["run_id"]
        ev = _d(conn.execute("SELECT * FROM eval_results WHERE run_id=?", (rid,)).fetchone()) or {}
        power = json.loads(ev.get("json_power") or "{}")
        traction = json.loads(ev.get("json_traction") or "{}")
        flags = json.loads(ev.get("flags") or "[]")
        slip = _d(conn.execute(
            "SELECT * FROM timeslips WHERE slip_id=?", (ev.get("slip_id"),)).fetchone()) if ev.get("slip_id") else None
        wx = _d(conn.execute("SELECT * FROM weather WHERE wx_id=?", (ev.get("wx_id"),)).fetchone()) if ev.get("wx_id") else None
        tire = _d(conn.execute("SELECT * FROM tire_state WHERE tire_id=?", (ev.get("tire_id"),)).fetchone()) if ev.get("tire_id") else None
        track = _d(conn.execute("SELECT * FROM track_state WHERE track_id=?", (ev.get("track_id"),)).fetchone()) if ev.get("track_id") else None
        df = run_frame(conn, rid)
        runs.append({
            "run_id": rid, "ts_start": r["ts_start"], "ts_end": r["ts_end"], "notes": r["notes"],
            "scores": {"overall": ev.get("score"),
                       "power": power.get("score"), "traction": traction.get("score")},
            "flags": flags, "power": power, "traction": traction,
            "readiness": greenlight_readiness(conn, rid),
            "live_slip": all(c in df.columns for c in
                             ["wheel_speed_fl", "wheel_speed_fr", "wheel_speed_rl", "wheel_speed_rr"]),
            "timeslip": slip, "weather": wx, "tire": tire, "track": track,
            "series": _series(df), "engine_snapshot": _engine_snapshot(df),
        })

    analysis = _d(conn.execute("SELECT * FROM analysis_results ORDER BY analysis_id DESC LIMIT 1").fetchone())
    if analysis:
        for k in ("knock_map_json", "lambda_error_map_json", "boost_vs_target_json", "fuel_headroom_json", "heat_json"):
            analysis[k] = json.loads(analysis[k] or "{}")
    forecast = _d(conn.execute("SELECT * FROM forecast ORDER BY forecast_id DESC LIMIT 1").fetchone())
    retune = [_d(x) for x in conn.execute("SELECT * FROM retune_recommendations ORDER BY rec_id")]

    return {
        "meta": {
            "generated_at": now_iso(),
            "data_source": SYNTHETIC_TAG,
            "disclaimer": "SYNTHETIC demo data — generated, not measured. Read-only; no calibration is written or flashed.",
            "car": "2020 Dodge Challenger SRT Hellcat Redeye",
        },
        "build_state": build,
        "runs": runs,
        "analysis": analysis,
        "forecast": forecast,
        "retune": retune,
        "maintenance": _maintenance(conn),
        "season": _season(conn),
    }


def write_report(conn, out: pathlib.Path = OUT) -> dict:
    rep = build_report(conn)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(rep, indent=2, default=str)
    out.write_text(payload)
    # Also emit a JS global so the portals load even from file:// (no fetch/CORS).
    (out.parent / "data.js").write_text(f"window.TUNETRACK_DATA = {payload};\n")
    # And drop a copy into the Teams reports_dir for the team/archive (best-effort).
    try:
        rdir = pathlib.Path(load_config()["reports_dir"])
        rdir.mkdir(parents=True, exist_ok=True)
        (rdir / "portal_data.json").write_text(payload)
    except Exception:
        pass
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    rep = write_report(conn, pathlib.Path(a.out))
    print(f"component 13: wrote {a.out}")
    print(f"  runs={len(rep['runs'])}  retune recs={len(rep['retune'])}  "
          f"maintenance items={len(rep['maintenance'])}  season events={len(rep['season'])}")
