"""Run the full TuneTrack pipeline 01 -> 13 on a VCM Scanner CSV.

Rebuilds tunetrack.db from scratch, ingests the log, segments the pull, attaches
context (build/timeslip/weather/tire/track), scores power + traction, runs the
green-light layer, then -- behind the data-quality gate -- analyzes, forecasts,
and produces the retune advisory, and finally writes web/data.json for the portals.

If no CSV exists, a synthetic demo log is generated first. All synthetic inputs
are tagged SYNTHETIC. Read-only with respect to the PCM throughout.
"""
from __future__ import annotations
import argparse
import pathlib
import sys

from db import reset_db, ROOT

sys.path.insert(0, str(ROOT))  # so `tools` is importable when run as a script
import ingest as c01
import segment as c02
import build_state as c03
import timeslip as c04
import weather as c05
import tire_track as c06
import eval_power as c07
import eval_traction as c08
import greenlight as c09
import seed
import analyze as c10
import forecast as c11
import retune as c12
import report as c13

DEFAULT_CSV = ROOT / "samples" / "synthetic_demo.csv"


def run(csv_path: pathlib.Path) -> None:
    if not csv_path.exists():
        from tools import make_synthetic_log  # noqa
        import datetime as dt
        make_synthetic_log.write_csv(csv_path, dt.datetime(2026, 6, 20, 19, 42, 11))
        print(f"[setup] generated synthetic log -> {csv_path}")

    conn = reset_db()
    print("[01] ingest");        rep = c01.ingest(csv_path, ROOT / "channels.yaml", conn)
    print(f"      {rep['rows']} rows, {len(rep['channels_matched'])} channels, anchor {rep['anchor']}")
    print("[02] segment");       run_ids = c02.segment_log(conn, rep["log_id"])
    rid = run_ids[0]
    print(f"      run {rid}")
    print("[03] build_state");   c03.seed_build_state(conn)
    print("[04] timeslip");      c04.ingest_slip(conn, rid)
    print("[05] weather/DA");    c05.record_weather(conn, rid)
    print("[06] tire/track");    c06.record_tire_track(conn, rid)
    print("[07] power");         p = c07.score_power(conn, rid)
    print("[08] traction");      t = c08.score_traction(conn, rid)
    print("[09] greenlight");    g = c09.run(conn, rid)
    print(f"      power {p['score']} / traction {t['score']} / overall {g['summary']['overall_score']}")
    print("[--] seed portals");  seed.seed(conn)
    print("[10] analyze");       a = c10.analyze(conn)
    print(f"      gate_passed={a['gate_passed']}, knock cells {list(a['knock_cells'])}")
    print("[11] forecast");      c11.forecast_next(conn)
    print("[12] retune");        rt = c12.recommend(conn, rid)
    print(f"      {rt['n_recommendations']} advisory recs (fuel_limited={rt.get('fuel_limited')})")
    print("[13] report");        out = c13.write_report(conn)
    print(f"      wrote web/data.json ({len(out['runs'])} run(s))")
    print("done.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv", nargs="?", default=str(DEFAULT_CSV))
    a = ap.parse_args()
    run(pathlib.Path(a.csv))
