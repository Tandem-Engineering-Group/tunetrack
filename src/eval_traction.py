"""Component 08 -- traction scorecard for a pull.

Two independent reads on launch pressure: the outcome read (60-ft + live rear
slip from wheel speeds) and the physical read (pyrometer cross-tread profile),
plus a convergence check between them. The Delta-60ft-per-psi sensitivity model
needs several passes; with one it reports "insufficient data".

Writes json_traction into the run's eval_results row.
Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import json
import pathlib

from db import connect, run_frame, ensure_eval_row, latest_run_id, DB_PATH

SPIN_THRESHOLD_PCT = 3.0


def score_traction(conn, run_id: int) -> dict:
    df = run_frame(conn, run_id)
    if df.empty:
        raise SystemExit("eval_traction: empty run frame")
    flags, deductions = [], 0

    # --- live rear slip from wheel speeds ---
    front = (df["wheel_speed_fl"] + df["wheel_speed_fr"]) / 2.0
    rear = (df["wheel_speed_rl"] + df["wheel_speed_rr"]) / 2.0
    valid = front > 3.0
    slip_pct = ((rear - front) / front * 100).where(valid)
    peak_slip = float(slip_pct.max()) if valid.any() else 0.0
    spin = slip_pct > SPIN_THRESHOLD_PCT
    if spin.any():
        win = df.loc[spin.fillna(False), "t_rel"]
        spin_window = [round(float(win.min()), 2), round(float(win.max()), 2)]
    else:
        spin_window = None
    slip_block = {"peak_pct": round(peak_slip, 1), "spin_window_s": spin_window}
    if peak_slip > 10:
        flags.append({"sev": "FLAG", "metric": "slip", "msg": f"{peak_slip:.0f}% peak launch slip"}); deductions += 15
    elif peak_slip > 5:
        deductions += 6

    # --- 60-ft from the bound timeslip ---
    slip_row = conn.execute(
        "SELECT t.sixty, t.quarter_et, t.quarter_mph FROM eval_results e "
        "JOIN timeslips t ON t.slip_id=e.slip_id WHERE e.run_id=?", (run_id,)
    ).fetchone()
    sixty = float(slip_row["sixty"]) if slip_row and slip_row["sixty"] is not None else None
    sixty_block = {"sixty_ft_s": sixty}
    if sixty is not None and sixty > 1.45:
        flags.append({"sev": "FLAG", "metric": "60ft", "msg": f"60-ft {sixty:.3f}s (soft launch)"}); deductions += 10

    # --- physical read: pyrometer cross-tread ---
    tire = conn.execute(
        "SELECT cold_psi_r, pyro_r_in, pyro_r_center, pyro_r_out, pyro_l_in, pyro_l_center, pyro_l_out "
        "FROM tire_state WHERE run_id=? ORDER BY tire_id DESC LIMIT 1", (run_id,)
    ).fetchone()
    pyro_block, pyro_call = None, None
    if tire:
        center = (tire["pyro_r_center"] + tire["pyro_l_center"]) / 2.0
        edges = (tire["pyro_r_in"] + tire["pyro_r_out"] + tire["pyro_l_in"] + tire["pyro_l_out"]) / 4.0
        d = center - edges
        pyro_call = "over-inflated (center hot)" if d > 4 else "under-inflated (edges hot)" if d < -4 else "even"
        pyro_block = {"center_c": round(center, 1), "edge_c": round(edges, 1),
                      "center_minus_edge_c": round(d, 1), "call": pyro_call,
                      "launch_psi": tire["cold_psi_r"]}

    # --- convergence: do the two reads agree on direction? ---
    outcome_call = "lower pressure / more bite" if peak_slip > 8 else "near optimal"
    converge = {"outcome_read": outcome_call, "pyro_read": pyro_call}
    if pyro_call and (
        (pyro_call.startswith("over") and "lower" not in outcome_call and peak_slip <= 8)
        or (pyro_call.startswith("under") and peak_slip > 8)
    ):
        converge["agree"] = False
        flags.append({"sev": "INFO", "metric": "convergence", "msg": "outcome and pyrometer reads disagree on pressure"})
    else:
        converge["agree"] = True

    # --- sensitivity model needs multiple passes ---
    npass = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    sensitivity = {"available": npass >= 3,
                   "note": "need >=3 passes across pressures/temps" if npass < 3 else "fitted"}

    score = max(0, 100 - deductions)
    traction = {"score": score, "slip": slip_block, "sixty": sixty_block,
                "pyro": pyro_block, "convergence": converge, "sensitivity": sensitivity,
                "flags": flags}
    ensure_eval_row(conn, run_id)
    conn.execute("UPDATE eval_results SET json_traction=? WHERE run_id=?", (json.dumps(traction), run_id))
    conn.commit()
    return traction


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    rid = a.run_id or latest_run_id(conn)
    tr = score_traction(conn, rid)
    print(f"component 08: traction score {tr['score']}/100  peak slip {tr['slip']['peak_pct']}%  "
          f"60ft {tr['sixty']['sixty_ft_s']}  pyro {tr['pyro']['call'] if tr['pyro'] else 'n/a'}")
