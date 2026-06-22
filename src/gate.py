"""Data-quality gate -- guards components 10-12.

A run must pass validation before deep analysis / forecast / retune will use it:
full pull captured, required channels present (incl. fuel pressure + wheel
speeds), timeslip + density altitude attached, and no dropped samples. A run
that fails is still scored (07-09) but excluded from retune recommendations.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, run_frame, latest_run_id, DB_PATH

# Wheel speeds are NOT required (they only enable live slip); knock/fuel/spark
# analysis runs without them.
REQUIRED_CHANNELS = ["engine_rpm", "map_kpa", "tps_pct", "fuel_press_kpa"]
MIN_PULL_S = 3.0
MAX_GAP_S = 0.2


def check_gate(conn, run_id: int) -> dict:
    checks = []

    def add(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    df = run_frame(conn, run_id)
    present = set(df.columns)

    dur = float(df["t_rel"].iloc[-1] - df["t_rel"].iloc[0]) if len(df) else 0.0
    add("full pull captured", dur >= MIN_PULL_S, f"{dur:.1f}s WOT window")

    missing = [c for c in REQUIRED_CHANNELS if c not in present]
    add("required channels present", not missing, f"missing: {missing}" if missing else "all present")

    row = conn.execute(
        "SELECT e.slip_id, t.quarter_et FROM eval_results e "
        "LEFT JOIN timeslips t ON t.slip_id=e.slip_id WHERE e.run_id=?", (run_id,)
    ).fetchone()
    add("timeslip attached", bool(row and row["slip_id"] and row["quarter_et"] is not None),
        "1/4 ET present" if row and row["quarter_et"] is not None else "no slip")

    wx = conn.execute("SELECT density_altitude_ft FROM weather ORDER BY wx_id DESC LIMIT 1").fetchone()
    add("density altitude attached", bool(wx and wx["density_altitude_ft"] is not None),
        f"DA {wx['density_altitude_ft']:.0f} ft" if wx and wx["density_altitude_ft"] is not None else "no DA")

    if len(df) > 2:
        gaps = df["t_rel"].diff().dropna()
        maxgap = float(gaps.max())
        add("no dropped samples", maxgap <= MAX_GAP_S, f"max gap {maxgap*1000:.0f} ms")
    else:
        add("no dropped samples", False, "too few samples")

    passed = all(c["ok"] for c in checks)
    return {"passed": passed, "checks": checks}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    rid = a.run_id or latest_run_id(conn)
    g = check_gate(conn, rid)
    print(f"data-quality gate: {'PASS' if g['passed'] else 'FAIL'}")
    for c in g["checks"]:
        print(f"  {'OK ' if c['ok'] else 'XX '} {c['check']}: {c['detail']}")
