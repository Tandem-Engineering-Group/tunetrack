"""Component 03 -- registry of the car's build/tune revision over date ranges.

Seeds one DUMMY build_state row so the rest of the pipeline has a configuration
to reference. Replace every value here with the real combo once known -- these
are assumptions, tagged SYNTHETIC in the notes.

Read-only with respect to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, SYNTHETIC_TAG, DB_PATH

# DUMMY current build -- replace with the real combo.
DEMO_BUILD = dict(
    date_from="2026-01-01", date_to=None,
    upper_pulley="3.0 in", lower_pulley="stock",
    snout="ported stock", pump="dual 525 lph (E85)",
    injectors="ID1300x2", e85_pct=85.0,
    boost_target_psi=14.0, belt_pn="Gates K080800HD", tune_rev="DEMO-r1",
    notes=f"{SYNTHETIC_TAG}: assumed build for end-to-end demo -- replace with real config",
)


def seed_build_state(conn) -> int:
    conn.execute("DELETE FROM build_state")
    cols = ",".join(DEMO_BUILD.keys())
    qs = ",".join("?" for _ in DEMO_BUILD)
    cur = conn.execute(f"INSERT INTO build_state({cols}) VALUES ({qs})", tuple(DEMO_BUILD.values()))
    conn.commit()
    return cur.lastrowid


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    sid = seed_build_state(conn)
    print(f"component 03: seeded build_state state_id={sid} ({DEMO_BUILD['tune_rev']}, {DEMO_BUILD['e85_pct']}% E85)")
