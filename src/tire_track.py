"""Component 06 -- capture tire_state + track_state for a run.

DUMMY values for the demo. The pyrometer cross-tread profile and pressures here
feed the traction scorecard's physical read; replace with real measurements.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, latest_run_id, DB_PATH, SYNTHETIC_TAG

# DUMMY tire set + post-run pyrometer (center hotter than edges -> a touch high).
DEMO_TIRE = dict(
    compound="MT ET Street R 315/40-18", set_id="A", heat_cycles=6,
    cold_psi_f=32.0, cold_psi_r=16.0, hot_psi_f=34.5, hot_psi_r=18.4,
    pyro_r_in=78.0, pyro_r_center=86.0, pyro_r_out=79.0,
    pyro_l_in=77.0, pyro_l_center=85.0, pyro_l_out=78.0,
    rollout_in=105.8,
    notes=f"{SYNTHETIC_TAG}: assumed tire set/pyro for demo",
)

# DUMMY track conditions (warm evening, PJ1 prep).
DEMO_TRACK = dict(
    surface_temp_c=38.0, air_temp_c=29.0, prep="PJ1",
    lane="left", time_of_day="19:42", bite_rating=8.0,
)


def record_tire_track(conn, run_id: int | None = None) -> tuple[int, int]:
    run_id = run_id or latest_run_id(conn)
    conn.execute("DELETE FROM tire_state WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM track_state WHERE run_id=?", (run_id,))

    tire = dict(DEMO_TIRE, run_id=run_id)
    cols = ",".join(tire.keys()); qs = ",".join("?" for _ in tire)
    tid = conn.execute(f"INSERT INTO tire_state({cols}) VALUES ({qs})", tuple(tire.values())).lastrowid

    track = dict(DEMO_TRACK, run_id=run_id)
    cols = ",".join(track.keys()); qs = ",".join("?" for _ in track)
    trid = conn.execute(f"INSERT INTO track_state({cols}) VALUES ({qs})", tuple(track.values())).lastrowid

    conn.commit()
    return tid, trid


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    tid, trid = record_tire_track(conn)
    print(f"component 06: tire_id={tid}, track_id={trid}  [{SYNTHETIC_TAG}]  "
          f"surface {DEMO_TRACK['surface_temp_c']}C / prep {DEMO_TRACK['prep']}")
