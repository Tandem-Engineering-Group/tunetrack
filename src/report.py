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

ATM_KPA = 101.3
OUT = ROOT / "web" / "data.json"

# Channel -> (label, plain-English meaning, unit) for the engine portal.
SENSORS = {
    "engine_rpm": ("Engine speed", "Crankshaft RPM — how fast the engine is turning.", "rpm"),
    "vehicle_speed": ("Vehicle speed", "Road speed from the non-driven wheels.", "mph"),
    "map_kpa": ("Manifold pressure", "Absolute pressure in the intake; above ~101 kPa is boost.", "kPa"),
    "tps_pct": ("Throttle", "Driver throttle command; 100% is wide open.", "%"),
    "knock_retard_total": ("Knock retard", "Timing the PCM pulled to stop detonation — want ~0.", "deg"),
    "eq_commanded": ("Commanded EQ", "Air/fuel the tune is asking for; >1 is rich.", "EQ"),
    "wb_eq_1": ("Measured EQ", "What the wideband actually sees; should track command.", "EQ"),
    "inj_duty_pct": ("Injector duty", "How long the injectors stay open — near 100% is maxed.", "%"),
    "fuel_press_kpa": ("Fuel pressure", "Rail pressure; a drop under load means the pump is signing off.", "kPa"),
    "ect_c": ("Coolant temp", "Engine coolant temperature.", "deg C"),
    "aircharge_temp_c": ("Intake air temp", "Charge-air temp after the blower/intercooler — heat soak risk.", "deg C"),
    "ltr_coolant_c": ("LTR coolant", "Low-temp radiator loop feeding the intercooler.", "deg C"),
    "oil_temp_c": ("Oil temp", "Engine oil temperature.", "deg C"),
    "oil_press_kpa": ("Oil pressure", "Engine oil pressure.", "kPa"),
    "egt_c": ("Exhaust temp", "Exhaust gas temperature — fueling/timing heat indicator.", "deg C"),
}


def _d(row):
    return dict(row) if row is not None else None


def _series(df: pd.DataFrame, n: int = 120) -> dict:
    if df.empty:
        return {}
    idx = list(range(0, len(df), max(1, len(df) // n)))
    s = df.iloc[idx]
    boost = ((s["map_kpa"] - ATM_KPA) / 6.895).round(1)
    front = (s["wheel_speed_fl"] + s["wheel_speed_fr"]) / 2
    rear = (s["wheel_speed_rl"] + s["wheel_speed_rr"]) / 2
    slip = (((rear - front) / front.where(front > 3) * 100)).round(1).fillna(0)
    return {
        "t": s["t_rel"].round(2).tolist(),
        "engine_rpm": s["engine_rpm"].round(0).tolist(),
        "vehicle_speed": s["vehicle_speed"].round(1).tolist(),
        "boost_psi": boost.tolist(),
        "knock": s["knock_retard_total"].round(2).tolist(),
        "eq_cmd": s["eq_commanded"].round(3).tolist(),
        "eq_meas": s["wb_eq_1"].round(3).tolist(),
        "inj_duty": s["inj_duty_pct"].round(1).tolist(),
        "fuel_press": s["fuel_press_kpa"].round(0).tolist(),
        "rear_slip_pct": slip.tolist(),
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
