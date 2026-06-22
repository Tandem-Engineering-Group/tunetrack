"""Component 03 -- registry of the car's build/tune revision over date ranges.

Seeds the current build_state for the actual car -- a 2020 Challenger SRT Hellcat
Redeye (6.2 supercharged, E85) running a 3.0" upper pulley toward a ~1,000 whp
goal. The KNOWN facts (platform, blower, 3" upper, E85, goal) are filled firmly;
the fueling/hardware fields are the most-likely spec for this combo and are
flagged "confirm" in the notes until verified -- update them here once known.

This is configuration, not measured data: the run telemetry in the demo is still
SYNTHETIC, but this combo sheet now reflects the real car. Read-only to the PCM.
"""
from __future__ import annotations
import argparse
import pathlib

from db import connect, DB_PATH

# Current build for the car. KNOWN: Redeye 6.2 SC, 3.0" upper pulley, E85,
# ~1000 whp goal. CONFIRM (best-estimate for now): pump, injectors, snout,
# ethanol %, belt PN -- edit these as the real spec is confirmed.
CURRENT_BUILD = dict(
    date_from="2026-01-01", date_to=None,
    upper_pulley="3.0 in", lower_pulley="stock",
    snout="stock 2.7L (Redeye)", pump="dual 525 lph (E85)",
    injectors="ID1300x (E85)", e85_pct=85.0,
    boost_target_psi=12.0, belt_pn="confirm PN", tune_rev="E85-base",
    notes=("2020 Hellcat Redeye 6.2 SC, 3.0in upper pulley, E85 -- ~1000 whp goal. "
           "CONFIRM: pump / injectors / snout / ethanol % / belt PN (best-estimate). "
           "Current safe base tune ~11-12 psi; 3in-pulley headroom to ~14-15 psi as "
           "fueling is validated."),
)


def seed_build_state(conn) -> int:
    conn.execute("DELETE FROM build_state")
    cols = ",".join(CURRENT_BUILD.keys())
    qs = ",".join("?" for _ in CURRENT_BUILD)
    cur = conn.execute(f"INSERT INTO build_state({cols}) VALUES ({qs})", tuple(CURRENT_BUILD.values()))
    conn.commit()
    return cur.lastrowid


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB_PATH))
    a = ap.parse_args()
    conn = connect(pathlib.Path(a.db))
    sid = seed_build_state(conn)
    print(f"component 03: seeded build_state state_id={sid} ({CURRENT_BUILD['tune_rev']}, {CURRENT_BUILD['e85_pct']}% E85)")
