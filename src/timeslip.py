"""Component 04 -- ingest a drag timeslip and bind it to a run by clock time.

Manual entry (a dict) or, later, photo OCR. For the demo it seeds one DUMMY
slip whose run_clock_time matches the detected pull, so the clock-time keystone
links slip <-> run. Replace with real numbers once a slip is entered.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, latest_run_id, DB_PATH, SYNTHETIC_TAG

# DUMMY slip for a ~1000 whp Redeye on a 1/4 mile -- replace with the real card.
DEMO_SLIP = dict(
    lane="left", rt=0.452, sixty=1.348, threethirty=3.62,
    eighth_et=6.31, eighth_mph=117.8, thousand=8.19,
    quarter_et=9.78, quarter_mph=143.2,
    raw_image_path=None,
)


def ingest_slip(conn, run_id: int | None = None, slip: dict | None = None) -> int:
    slip = dict(slip or DEMO_SLIP)
    run_id = run_id or latest_run_id(conn)
    # Bind by clock time: anchor the slip to the run's start wall-clock.
    run_clock = None
    if run_id is not None:
        row = conn.execute("SELECT ts_start FROM runs WHERE run_id=?", (run_id,)).fetchone()
        run_clock = row["ts_start"] if row else None
    slip["run_clock_time"] = run_clock

    conn.execute("DELETE FROM timeslips")  # demo: single slip
    cols = ",".join(slip.keys())
    qs = ",".join("?" for _ in slip)
    cur = conn.execute(f"INSERT INTO timeslips({cols}) VALUES ({qs})", tuple(slip.values()))
    conn.commit()
    return cur.lastrowid


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    sid = ingest_slip(conn)
    s = conn.execute("SELECT * FROM timeslips WHERE slip_id=?", (sid,)).fetchone()
    print(f"component 04: slip_id={sid}  [{SYNTHETIC_TAG}]  60ft={s['sixty']}  "
          f"1/4={s['quarter_et']}@{s['quarter_mph']}  RT={s['rt']}  clock={s['run_clock_time']}")
