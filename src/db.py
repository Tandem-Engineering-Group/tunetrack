"""Shared SQLite helpers for the TuneTrack pipeline.

Read-only with respect to the PCM. This catalog only stores log/analysis data;
nothing here writes, flashes, or transmits a calibration.
"""
from __future__ import annotations
import sqlite3
import pathlib
import datetime as dt

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "tunetrack.db"
SCHEMA = ROOT / "schema.sql"

# Canonical absolute-timestamp format used across the pipeline.
TS_FMT = "%Y-%m-%d %H:%M:%S.%f"

# Marker stamped on every row that came from generated/assumed data rather than
# a real VCM Scanner log or measurement. Surfaced on the portals so synthetic
# figures are never mistaken for real ones.
SYNTHETIC_TAG = "SYNTHETIC"


def now_iso() -> str:
    return dt.datetime.now().strftime(TS_FMT)


def connect(db_path: pathlib.Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection, schema: pathlib.Path | None = None) -> None:
    conn.executescript((schema or SCHEMA).read_text())
    conn.commit()


def reset_db(db_path: pathlib.Path | None = None) -> sqlite3.Connection:
    """Drop the catalog and rebuild it from schema.sql (idempotent full runs)."""
    p = db_path or DB_PATH
    if p.exists():
        p.unlink()
    conn = connect(p)
    init_db(conn)
    return conn


def _to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Long samples (ts_abs, channel, value) -> wide frame indexed by ts_abs,
    with an added ``t_rel`` elapsed-seconds column."""
    if df.empty:
        return df
    wide = df.pivot_table(index="ts_abs", columns="channel", values="value", aggfunc="mean").sort_index()
    ts = pd.to_datetime(wide.index)
    wide.insert(0, "t_rel", (ts - ts[0]).total_seconds())
    return wide


def log_frame(conn: sqlite3.Connection, log_id: int) -> pd.DataFrame:
    """Wide channel frame for an entire log."""
    df = pd.read_sql_query(
        "SELECT ts_abs, channel, value FROM samples WHERE log_id=?", conn, params=(log_id,)
    )
    return _to_wide(df)


def run_frame(conn: sqlite3.Connection, run_id: int) -> pd.DataFrame:
    """Wide channel frame for a single run's WOT window."""
    row = conn.execute(
        "SELECT log_id, ts_start, ts_end FROM runs WHERE run_id=?", (run_id,)
    ).fetchone()
    if row is None:
        return pd.DataFrame()
    df = pd.read_sql_query(
        "SELECT ts_abs, channel, value FROM samples "
        "WHERE log_id=? AND ts_abs>=? AND ts_abs<=?",
        conn, params=(row["log_id"], row["ts_start"], row["ts_end"]),
    )
    return _to_wide(df)


def latest_run_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT run_id FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    return row["run_id"] if row else None


def ensure_eval_row(conn: sqlite3.Connection, run_id: int) -> None:
    """Create the single eval_results row for a run (linking the latest context
    foreign keys) if it doesn't exist yet. Components 07/08/09 update columns."""
    if conn.execute("SELECT 1 FROM eval_results WHERE run_id=?", (run_id,)).fetchone():
        return

    def _one(sql, args=()):
        r = conn.execute(sql, args).fetchone()
        return r[0] if r else None

    slip = _one("SELECT slip_id FROM timeslips ORDER BY slip_id DESC LIMIT 1")
    wx = _one("SELECT wx_id FROM weather ORDER BY wx_id DESC LIMIT 1")
    tire = _one("SELECT tire_id FROM tire_state WHERE run_id=? ORDER BY tire_id DESC LIMIT 1", (run_id,))
    track = _one("SELECT track_id FROM track_state WHERE run_id=? ORDER BY track_id DESC LIMIT 1", (run_id,))
    state = _one("SELECT state_id FROM build_state ORDER BY state_id DESC LIMIT 1")
    conn.execute(
        "INSERT INTO eval_results(run_id, slip_id, state_id, wx_id, tire_id, track_id, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (run_id, slip, state, wx, tire, track, now_iso()),
    )
    conn.commit()
