"""Component 10 -- deep, cell-resolved engine analysis (behind the gate).

Aggregates gate-passing pulls into RPM x boost cell maps: knock retard, lambda
(EQ) error vs command, boost achieved vs target, injector-duty / fuel-pressure
headroom, and heat. Output -> analysis_results.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import json
import pathlib

import pandas as pd

from db import connect, run_frame, latest_run_id, now_iso, DB_PATH
from gate import check_gate

ATM_KPA = 101.3
RPM_BIN = 500
BOOST_BIN = 2


def _cellkey(rpm, boost):
    return f"{int(rpm // RPM_BIN) * RPM_BIN}rpm/{int(boost // BOOST_BIN) * BOOST_BIN}psi"


def analyze(conn, state_id: int | None = None) -> dict:
    runs = [r["run_id"] for r in conn.execute("SELECT run_id FROM runs ORDER BY run_id")]
    frames, used = [], []
    for rid in runs:
        if check_gate(conn, rid)["passed"]:
            frames.append(run_frame(conn, rid)); used.append(rid)
    gate_passed = len(frames) > 0
    if not gate_passed:
        df = pd.concat([run_frame(conn, rid) for rid in runs]) if runs else pd.DataFrame()
    else:
        df = pd.concat(frames)

    df = df[df["map_kpa"] > ATM_KPA + 13]  # on boost only
    boost = (df["map_kpa"] - ATM_KPA) / 6.895
    cells = [_cellkey(r, b) for r, b in zip(df["engine_rpm"], boost)]
    df = df.assign(_cell=cells, _boost=boost.values)

    knock_map, lambda_map, fuel_head, boost_tgt = {}, {}, {}, {}
    for cell, g in df.groupby("_cell"):
        knock_map[cell] = round(float(g["knock_retard_total"].max()), 2)
        lambda_map[cell] = round(float(((g["eq_commanded"] - g["wb_eq_1"]) / g["eq_commanded"] * 100).mean()), 2)
        fuel_head[cell] = {"max_duty_pct": round(float(g["inj_duty_pct"].max()), 1),
                           "min_fuel_kpa": round(float(g["fuel_press_kpa"].min()))}

    target = conn.execute("SELECT boost_target_psi FROM build_state ORDER BY state_id DESC LIMIT 1").fetchone()
    target_psi = float(target["boost_target_psi"]) if target else None
    for rb, g in df.groupby((df["engine_rpm"] // RPM_BIN) * RPM_BIN):
        boost_tgt[f"{int(rb)}rpm"] = {"achieved_psi": round(float(g["_boost"].max()), 1), "target_psi": target_psi}

    heat = {"egt_peak_c": round(float(df["egt_c"].max())) if len(df) else None,
            "iat_peak_c": round(float(df["aircharge_temp_c"].max()), 1) if len(df) else None}

    state_id = state_id or (conn.execute("SELECT state_id FROM build_state ORDER BY state_id DESC LIMIT 1").fetchone() or [None])[0]
    cur = conn.execute(
        "INSERT INTO analysis_results(run_id, state_id, knock_map_json, lambda_error_map_json, "
        "boost_vs_target_json, fuel_headroom_json, heat_json, passes_used, gate_passed, created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (used[-1] if used else (runs[-1] if runs else None), state_id,
         json.dumps(knock_map), json.dumps(lambda_map), json.dumps(boost_tgt),
         json.dumps(fuel_head), json.dumps(heat), len(used), int(gate_passed), now_iso()),
    )
    conn.commit()
    return {"analysis_id": cur.lastrowid, "passes_used": len(used), "gate_passed": gate_passed,
            "knock_cells": {k: v for k, v in knock_map.items() if v > 1.0},
            "lean_cells": {k: v for k, v in lambda_map.items() if v > 3.0},
            "fuel_headroom": fuel_head, "heat": heat}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    out = analyze(conn)
    print(f"component 10: analysis_id={out['analysis_id']}  passes_used={out['passes_used']}  "
          f"gate_passed={out['gate_passed']}")
    print(f"  knock cells (>1deg): {out['knock_cells']}")
    print(f"  lean cells (>3%):    {out['lean_cells']}")
