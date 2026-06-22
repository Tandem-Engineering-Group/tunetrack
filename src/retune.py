"""Component 12 -- bounded, evidence-tagged retune ADVISORY (behind the gate).

HARD BOUNDARY: this never writes, flashes, or generates a calibration. It emits
rows in retune_recommendations (a sheet + a VCM Editor diff list) for a human to
review and apply in VCM Editor.

Guardrails enforced here:
  * Pulling timing where knock appeared is always allowed (safety).
  * Fuel/safety outrank power: if injector duty / fuel pressure show the fuel
    system is maxed, recommend fixing fueling first and WITHHOLD timing/boost adds.
  * Never recommend beyond demonstrated-safe values; new territory is flagged
    "step in incrementally", not handed over as a number.
  * Every recommendation carries evidence, magnitude, confidence, and rationale.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import json
import pathlib

from db import connect, latest_run_id, now_iso, DB_PATH
from gate import check_gate

DUTY_LIMIT_HARD = 90.0


def _insert(conn, **kw):
    kw.setdefault("status", "proposed")
    kw["created_at"] = now_iso()
    cols = ",".join(kw.keys()); qs = ",".join("?" for _ in kw)
    conn.execute(f"INSERT INTO retune_recommendations({cols}) VALUES ({qs})", tuple(kw.values()))


def recommend(conn, run_id: int | None = None) -> dict:
    run_id = run_id or latest_run_id(conn)
    gate = check_gate(conn, run_id)
    analysis = conn.execute("SELECT * FROM analysis_results ORDER BY analysis_id DESC LIMIT 1").fetchone()
    fc = conn.execute("SELECT * FROM forecast ORDER BY forecast_id DESC LIMIT 1").fetchone()
    aid = analysis["analysis_id"] if analysis else None
    fid = fc["forecast_id"] if fc else None

    conn.execute("DELETE FROM retune_recommendations")  # demo: regenerate
    if not gate["passed"]:
        conn.commit()
        return {"gate_passed": False, "n_recommendations": 0,
                "note": "run failed data-quality gate; scored only, no retune issued"}

    knock_map = json.loads(analysis["knock_map_json"] or "{}")
    lambda_map = json.loads(analysis["lambda_error_map_json"] or "{}")
    fuel_head = json.loads(analysis["fuel_headroom_json"] or "{}")

    # Is the fuel system maxed? (duty at/above hard limit, or a flagged pressure droop)
    max_duty = max((c["max_duty_pct"] for c in fuel_head.values()), default=0.0)
    power_flags = []
    er = conn.execute("SELECT flags FROM eval_results WHERE run_id=?", (run_id,)).fetchone()
    if er and er["flags"]:
        power_flags = json.loads(er["flags"])
    fuel_press_flag = any(f.get("metric") == "fuel_press" for f in power_flags)
    belt_flag = any(f.get("metric") == "belt" for f in power_flags)
    fuel_limited = max_duty >= DUTY_LIMIT_HARD or fuel_press_flag

    recs = []

    # 1) SPARK -- always allowed to pull where knock was seen.
    for cell, kr in sorted(knock_map.items(), key=lambda kv: -kv[1]):
        if kr > 1.0:
            pull = -round(max(kr, 1.0) * 2) / 2  # round to 0.5deg, at least the observed retard
            _insert(conn, analysis_id=aid, forecast_id=fid,
                    table_target="Spark Advance (High Octane) RPM x MAP",
                    cell=cell, current_value=None, recommended_value=None, delta=pull,
                    evidence=f"peak {kr:.1f}deg knock retard @ {cell}",
                    confidence=0.9, guardrail_flag=None,
                    rationale=f"Pull {abs(pull):.1f}deg here; knock is direct evidence, pulling timing is always safe.")
            recs.append(("spark", cell, pull))

    # 2) FUELING outranks power.
    if fuel_limited:
        _insert(conn, analysis_id=aid, forecast_id=fid,
                table_target="Fuel system (hardware) + base fuel pressure",
                cell="top-end / high boost", current_value=None, recommended_value=None, delta=None,
                evidence=f"injector duty {max_duty:.0f}% (>= {DUTY_LIMIT_HARD:.0f}% hard limit)"
                         + ("; WOT fuel-pressure droop flagged" if fuel_press_flag else ""),
                confidence=0.9, guardrail_flag="FUEL_LIMIT",
                rationale="Fuel system is at its limit. Add delivery capacity (pump/injectors) or raise "
                          "base pressure BEFORE any timing or boost increase. Fuel/safety outrank power.")
        recs.append(("fuel", "top-end", None))
        # Withhold power adds explicitly.
        _insert(conn, analysis_id=aid, forecast_id=fid,
                table_target="Timing / boost ADDS",
                cell="all", current_value=None, recommended_value=None, delta=None,
                evidence="fuel system maxed (see fueling recommendation)",
                confidence=0.95, guardrail_flag="WITHHELD",
                rationale="Timing-add and boost-increase suggestions withheld until fueling headroom is restored.")
        recs.append(("withhold", "all", None))
    else:
        # Only richen lean cells when fueling has headroom.
        for cell, lean in lambda_map.items():
            if lean > 3.0:
                _insert(conn, analysis_id=aid, forecast_id=fid,
                        table_target="Commanded EQ / fuel (RPM x MAP)",
                        cell=cell, current_value=None, recommended_value=None, delta=round(lean, 1),
                        evidence=f"{lean:.1f}% lean vs command @ {cell}",
                        confidence=0.7, guardrail_flag=None,
                        rationale=f"Add ~{lean:.0f}% commanded fuel to close the lean excursion.")
                recs.append(("eq", cell, lean))

    # 3) BOOST target.
    if belt_flag:
        _insert(conn, analysis_id=aid, forecast_id=fid,
                table_target="Boost / belt",
                cell="high rpm", current_value=None, recommended_value=None, delta=None,
                evidence="boost-departure signature (suspected belt slip)",
                confidence=0.6, guardrail_flag=None,
                rationale="Check belt tension/wrap before commanding more boost; the curve is falling off mechanically.")
        recs.append(("belt", "high rpm", None))
    elif fuel_limited:
        _insert(conn, analysis_id=aid, forecast_id=fid,
                table_target="Boost target",
                cell="all", current_value=None, recommended_value=None, delta=0.0,
                evidence=f"forecast DA {fc['da_ft'] if fc else 'n/a'} ft (denser next run)",
                confidence=0.7, guardrail_flag="FUEL_LIMIT",
                rationale="Hold boost target; do not raise into denser air while fuel-limited.")
        recs.append(("boost", "all", 0.0))

    # 4) LAUNCH pressure from pyro + slip, cross-checked.
    tr = conn.execute("SELECT json_traction FROM eval_results WHERE run_id=?", (run_id,)).fetchone()
    traction = json.loads(tr["json_traction"]) if tr and tr["json_traction"] else {}
    pyro = traction.get("pyro") or {}
    slip = traction.get("slip") or {}
    if pyro.get("call", "").startswith("over") or (slip.get("peak_pct") or 0) > 8:
        cur_psi = pyro.get("launch_psi")
        rec_psi = round(cur_psi - 1.5, 1) if cur_psi is not None else None
        track_t = fc["track_temp_c"] if fc else None
        _insert(conn, analysis_id=aid, forecast_id=fid,
                table_target="Launch tire pressure (rear, cold)",
                cell=f"forecast track {track_t}C" if track_t is not None else "launch",
                current_value=cur_psi, recommended_value=rec_psi,
                delta=(rec_psi - cur_psi) if (cur_psi is not None and rec_psi is not None) else None,
                evidence=f"pyro {pyro.get('call','?')}, peak slip {slip.get('peak_pct','?')}%",
                confidence=0.6, guardrail_flag="STEP_IN",
                rationale="Drop ~1.5 psi (small step into new territory) to settle launch spin; verify on the next pass.")
        recs.append(("launch_psi", "rear", rec_psi))

    conn.commit()
    return {"gate_passed": True, "fuel_limited": fuel_limited, "n_recommendations": len(recs), "recs": recs}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", type=int, default=None)
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    out = recommend(conn)
    print(f"component 12: gate_passed={out['gate_passed']}  fuel_limited={out.get('fuel_limited')}  "
          f"{out['n_recommendations']} recommendations (ADVISORY ONLY -- never flashed)")
    for r in conn.execute("SELECT table_target, cell, delta, guardrail_flag, evidence FROM retune_recommendations"):
        gf = f"[{r['guardrail_flag']}] " if r["guardrail_flag"] else ""
        d = f"{r['delta']:+g} " if r["delta"] is not None else ""
        print(f"  {gf}{r['table_target']} @ {r['cell']}: {d}-- {r['evidence']}")
