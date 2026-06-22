"""Component 02 -- detect WOT pulls and write `runs`.

A pull is a sustained wide-open-throttle + boosted segment:
    TPS >= 95%  AND  MAP >= boost threshold, held for >= min duration.
Short dropouts are bridged. A manual clock-time window can also be supplied.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import datetime as dt
import pathlib

import pandas as pd

from db import connect, log_frame, now_iso, TS_FMT, DB_PATH

TPS_MIN = 95.0
MAP_MIN = 130.0      # kPa (~4 psi of boost) -- clearly on the pull
MAX_GAP_S = 0.5      # bridge brief dropouts
MIN_DUR_S = 1.0


def _segments(times: list[dt.datetime], mask: list[bool]):
    """Yield (start, end) datetime pairs for contiguous True regions, bridging
    gaps up to MAX_GAP_S."""
    segs, start, last = [], None, None
    for ts, on in zip(times, mask):
        if on:
            if start is None:
                start = ts
            last = ts
        else:
            if start is not None and (ts - last).total_seconds() > MAX_GAP_S:
                segs.append((start, last))
                start = None
    if start is not None:
        segs.append((start, last))
    return [(s, e) for s, e in segs if (e - s).total_seconds() >= MIN_DUR_S]


def segment_log(conn, log_id: int) -> list[int]:
    df = log_frame(conn, log_id)
    if df.empty or "tps_pct" not in df or "map_kpa" not in df:
        raise SystemExit("segment: need tps_pct and map_kpa channels in the log")

    times = [dt.datetime.strptime(s, TS_FMT) for s in df.index]
    mask = ((df["tps_pct"] >= TPS_MIN) & (df["map_kpa"] >= MAP_MIN)).tolist()
    segs = _segments(times, mask)

    conn.execute("DELETE FROM runs WHERE log_id=?", (log_id,))
    run_ids = []
    for s, e in segs:
        win = df[(pd.to_datetime(df.index) >= s) & (pd.to_datetime(df.index) <= e)]
        peak_rpm = float(win["engine_rpm"].max()) if "engine_rpm" in win else None
        peak_map = float(win["map_kpa"].max())
        peak_boost = round((peak_map - 101.3) / 6.895, 1)
        notes = f"auto WOT pull; peak {peak_rpm:.0f} rpm, {peak_boost:.1f} psi boost"
        cur = conn.execute(
            "INSERT INTO runs(log_id, ts_start, ts_end, source, notes) VALUES (?,?,?,?,?)",
            (log_id, s.strftime(TS_FMT), e.strftime(TS_FMT), "auto-wot", notes),
        )
        run_ids.append(cur.lastrowid)
    conn.commit()
    return run_ids


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--log-id", type=int, default=1)
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    ids = segment_log(conn, a.log_id)
    print(f"component 02: detected {len(ids)} run(s) -> run_id {ids}")
    for r in conn.execute("SELECT run_id, ts_start, ts_end, notes FROM runs"):
        print(f"  run {r['run_id']}: {r['ts_start']} -> {r['ts_end']}  ({r['notes']})")
