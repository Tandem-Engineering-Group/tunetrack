"""Component 07 -- power / safety scorecard for a pull.

Knock, lambda-vs-command, belt slip, injector duty, fuel pressure, heat soak,
EGT. Writes json_power into the run's eval_results row. Safety findings are the
point here -- they later drive the retune guardrails (fuel/safety outrank power).

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import json
import pathlib

from db import connect, run_frame, ensure_eval_row, latest_run_id, DB_PATH

ATM_KPA = 101.3


def _boost_psi(map_kpa):
    return (map_kpa - ATM_KPA) / 6.895


def _cell(rpm: float, boost: float) -> str:
    rb = int(rpm // 500) * 500
    bb = int(boost // 2) * 2
    return f"{rb}-{rb+500} rpm / {bb}-{bb+2} psi"


def score_power(conn, run_id: int) -> dict:
    df = run_frame(conn, run_id)
    if df.empty:
        raise SystemExit("eval_power: empty run frame")
    boost = _boost_psi(df["map_kpa"])
    flags, deductions = [], 0

    # --- knock ---
    knock = df["knock_retard_total"]
    kpeak = float(knock.max())
    ki = knock.idxmax()
    krpm = float(df.loc[ki, "engine_rpm"]); kboost = float(boost.loc[ki])
    knock_block = {"peak_deg": round(kpeak, 2), "cell": _cell(krpm, kboost),
                   "rpm": round(krpm), "boost_psi": round(kboost, 1)}
    if kpeak > 2.0:
        flags.append({"sev": "HARD", "metric": "knock", "msg": f"{kpeak:.1f}deg retard @ {knock_block['cell']}"}); deductions += 30
    elif kpeak > 1.0:
        flags.append({"sev": "FLAG", "metric": "knock", "msg": f"{kpeak:.1f}deg retard @ {knock_block['cell']}"}); deductions += 10

    # --- lambda vs command (lean excursion above ~10 psi) ---
    m = boost > 10
    lean_pct = ((df["eq_commanded"] - df["wb_eq_1"]) / df["eq_commanded"] * 100).where(m)
    peak_lean = float(lean_pct.max()) if m.any() else 0.0
    lean_block = {"peak_lean_pct": round(peak_lean, 1)}
    if peak_lean > 3.0:
        li = lean_pct.idxmax()
        lean_block["cell"] = _cell(float(df.loc[li, "engine_rpm"]), float(boost.loc[li]))
        flags.append({"sev": "FLAG", "metric": "lambda", "msg": f"{peak_lean:.1f}% lean @ {lean_block['cell']}"}); deductions += 12

    # --- injector duty ---
    duty_peak = float(df["inj_duty_pct"].max())
    duty_block = {"peak_pct": round(duty_peak, 1)}
    if duty_peak > 90:
        flags.append({"sev": "HARD", "metric": "inj_duty", "msg": f"{duty_peak:.0f}% injector duty"}); deductions += 20
    elif duty_peak > 85:
        flags.append({"sev": "FLAG", "metric": "inj_duty", "msg": f"{duty_peak:.0f}% injector duty (approaching limit)"}); deductions += 8

    # --- fuel pressure droop under WOT ---
    base = float(df["fuel_press_kpa"].iloc[: max(1, len(df) // 10)].median())
    fmin = float(df["fuel_press_kpa"].min())
    drop = base - fmin
    fuel_block = {"base_kpa": round(base), "min_kpa": round(fmin), "drop_kpa": round(drop)}
    if drop > 15:
        flags.append({"sev": "FLAG", "metric": "fuel_press", "msg": f"fuel pressure dropped {drop:.0f} kPa under WOT (pump signing off)"}); deductions += 12

    # --- belt slip signature: boost falls while rpm still climbing ---
    belt = {"suspected": False}
    bi = boost.idxmax()
    after = df.loc[bi:]
    if len(after) > 3:
        end_boost = float(boost.loc[after.index[-1]])
        end_rpm = float(after["engine_rpm"].iloc[-1]); peak_rpm_after = float(after["engine_rpm"].max())
        if (float(boost.loc[bi]) - end_boost) > 1.5 and end_rpm > float(df.loc[bi, "engine_rpm"]) + 300:
            belt = {"suspected": True, "departure_rpm": round(float(df.loc[bi, "engine_rpm"]))}
            flags.append({"sev": "FLAG", "metric": "belt", "msg": f"boost departure ~{belt['departure_rpm']} rpm (suspected belt slip)"}); deductions += 10

    # --- EGT band + heat soak ---
    egt_peak = float(df["egt_c"].max())
    egt_block = {"peak_c": round(egt_peak)}
    if egt_peak > 900:
        flags.append({"sev": "FLAG", "metric": "egt", "msg": f"EGT {egt_peak:.0f}C above safe band"}); deductions += 12
    iat_block = {"start_c": round(float(df["aircharge_temp_c"].iloc[0]), 1),
                 "end_c": round(float(df["aircharge_temp_c"].iloc[-1]), 1)}
    iat_block["rise_c"] = round(iat_block["end_c"] - iat_block["start_c"], 1)

    score = max(0, 100 - deductions)
    power = {
        "score": score, "knock": knock_block, "lambda": lean_block,
        "inj_duty": duty_block, "fuel_press": fuel_block, "belt": belt,
        "egt": egt_block, "heat_soak": iat_block, "flags": flags,
    }
    ensure_eval_row(conn, run_id)
    conn.execute("UPDATE eval_results SET json_power=? WHERE run_id=?", (json.dumps(power), run_id))
    conn.commit()
    return power


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    rid = a.run_id or latest_run_id(conn)
    p = score_power(conn, rid)
    print(f"component 07: power score {p['score']}/100  flags={[f['metric'] for f in p['flags']]}")
    for f in p["flags"]:
        print(f"  [{f['sev']}] {f['metric']}: {f['msg']}")
