"""Component 09 -- green-light readiness layer.

Maintains the `ready_go` + `rear_slip_pct` VCM Scanner calc-channel definitions
(written to web/calc_channels.json for the in-car layout and the portal), runs a
pre-stage readiness checklist against the staging sample, and finalizes the run's
eval_results (overall score + merged flags).

NOTE: the math-channel expression syntax/token names must be confirmed against
the installed VCM Scanner version before pasting them into a layout.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import pathlib

from db import connect, log_frame, ensure_eval_row, latest_run_id, ROOT, TS_FMT, DB_PATH

# Pre-stage window thresholds (controllable variables held inside their window).
WINDOW = {
    "ect_c": (82.0, 98.0),
    "aircharge_temp_c": (None, 50.0),
    "fuel_press_kpa": (550.0, None),
    "ltr_coolant_c": (30.0, 55.0),
}

CALC_CHANNELS = {
    "_note": "VCM Scanner math channels -- CONFIRM token names + syntax against your installed version.",
    "ready_go": {
        "description": "1 when every controllable pre-stage variable is in its window, else 0.",
        "expression": (
            "(({SAE.ECT.C}>=82)&&({SAE.ECT.C}<=98)) && ({SAE.IAT.C}<50) && "
            "({Fuel.RailPressure.kPa}>550) && (({LTR.Coolant.C}>=30)&&({LTR.Coolant.C}<=55)) ? 1 : 0"
        ),
        "gauge": "single large tile, green @ 1 / red @ 0",
    },
    "rear_slip_pct": {
        "description": "Live launch slip: driven (rear) vs non-driven (front) wheel speed.",
        "expression": (
            "((({Wheel.Speed.RL.MPH}+{Wheel.Speed.RR.MPH})/2) - "
            "(({Wheel.Speed.FL.MPH}+{Wheel.Speed.FR.MPH})/2)) / "
            "max((({Wheel.Speed.FL.MPH}+{Wheel.Speed.FR.MPH})/2),1) * 100"
        ),
        "gauge": "line gauge, marker at spin threshold ~3-5%",
    },
    "window": WINDOW,
}


def write_calc_channels() -> pathlib.Path:
    out = ROOT / "web" / "calc_channels.json"
    out.write_text(json.dumps(CALC_CHANNELS, indent=2))
    return out


def _check(value, lo, hi):
    ok = True
    if lo is not None and value < lo:
        ok = False
    if hi is not None and value > hi:
        ok = False
    return ok


def readiness(conn, run_id: int) -> dict:
    row = conn.execute("SELECT log_id, ts_start FROM runs WHERE run_id=?", (run_id,)).fetchone()
    df = log_frame(conn, row["log_id"])
    start = row["ts_start"]
    staging = df[df.index < start]
    sample = (staging.iloc[-1] if len(staging) else df.iloc[0])

    checks = []
    all_ok = True
    for ch, (lo, hi) in WINDOW.items():
        if ch not in sample:
            continue
        val = float(sample[ch])
        ok = _check(val, lo, hi)
        all_ok = all_ok and ok
        checks.append({"channel": ch, "value": round(val, 1), "lo": lo, "hi": hi, "ok": ok})
    return {"ready_go": all_ok, "checks": checks,
            "staging_at": str(sample.name) if hasattr(sample, "name") else None}


def finalize(conn, run_id: int) -> dict:
    ensure_eval_row(conn, run_id)
    row = conn.execute("SELECT json_power, json_traction FROM eval_results WHERE run_id=?", (run_id,)).fetchone()
    power = json.loads(row["json_power"]) if row["json_power"] else {}
    traction = json.loads(row["json_traction"]) if row["json_traction"] else {}
    pscore = power.get("score", 0); tscore = traction.get("score", 0)
    overall = round(0.6 * pscore + 0.4 * tscore, 1)
    flags = (power.get("flags", []) + traction.get("flags", []))
    conn.execute("UPDATE eval_results SET score=?, flags=? WHERE run_id=?",
                 (overall, json.dumps(flags), run_id))
    conn.commit()
    return {"overall_score": overall, "power_score": pscore, "traction_score": tscore,
            "n_flags": len(flags)}


def run(conn, run_id: int) -> dict:
    path = write_calc_channels()
    ready = readiness(conn, run_id)
    summary = finalize(conn, run_id)
    return {"calc_channels_path": str(path), "readiness": ready, "summary": summary}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    rid = a.run_id or latest_run_id(conn)
    out = run(conn, rid)
    r = out["readiness"]; s = out["summary"]
    print(f"component 09: ready_go={r['ready_go']}  overall {s['overall_score']}/100 "
          f"(power {s['power_score']}, traction {s['traction_score']}), {s['n_flags']} flags")
    for c in r["checks"]:
        print(f"  {'OK ' if c['ok'] else 'OUT'} {c['channel']}={c['value']} (window {c['lo']}..{c['hi']})")
    print(f"  calc channels -> {out['calc_channels_path']}")
