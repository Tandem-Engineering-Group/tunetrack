"""Component 01 -- ingest + normalize a VCM Scanner CSV into the TuneTrack catalog.

Read-only with respect to the PCM. This module only reads logs.

The header/preamble layout of a VCM Scanner export varies by version, so this
parser is defensive: it scans the top of the file for the `Created` anchor,
auto-detects the channel-name header row (the row that best matches known
channels), skips an optional units row, maps columns via channels.yaml, and
writes `logs` + `samples` keyed on absolute timestamp.

    absolute_time(row) = created_wallclock + Offset_seconds

When a real export arrives, confirm the `Created` format and header layout and
trim whatever assumptions here are unnecessary.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import io
import json
import pathlib
import re

import pandas as pd
import yaml

from db import connect, init_db, now_iso, TS_FMT, ROOT, DB_PATH
from config import load_config

# Channels that MUST be present for a valid pass (hard-flagged if missing).
REQUIRED = {
    "core (segmentation)": ["engine_rpm", "map_kpa", "tps_pct"],
    "fuel safety": ["fuel_press_kpa"],
}
# Nice-to-have channels: their absence degrades a feature but doesn't block the run.
RECOMMENDED = {
    "live launch-slip (wheel speeds)": ["wheel_speed_rl", "wheel_speed_rr",
                                        "wheel_speed_fl", "wheel_speed_fr"],
}

# Tokens that identify the elapsed-time column.
TIME_TOKENS = {"offset", "time", "offset (s)", "time (s)", "offset(s)", "time(s)", "sae.time"}

# Accepted `Created:` wallclock formats (extend as real exports reveal more).
CREATED_FORMATS = [
    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S",
    "%Y-%m-%d %I:%M:%S %p", "%Y-%m-%d %H:%M:%S",
    "%m/%d/%Y %I:%M %p", "%d/%m/%Y %H:%M:%S",
]


def load_aliases(path: pathlib.Path) -> dict[str, str]:
    """variant column name (lowercased) -> canonical name."""
    raw = yaml.safe_load(path.read_text())
    out: dict[str, str] = {}
    for canon, variants in raw.items():
        for v in variants:
            out[v.strip().lower()] = canon
    return out


def _clean(name: str) -> str:
    return name.strip().strip('"').strip().lower()


def match_channel(col: str, aliases: dict[str, str]) -> str | None:
    """Match a column name to a canonical channel. Tries the full cleaned name
    first (so alias strings that legitimately contain parentheses still match),
    then strips trailing unit-like ``(...)`` groups and retries."""
    n = _clean(col)
    if n in aliases:
        return aliases[n]
    while re.search(r"\s*\([^()]*\)\s*$", n):
        n = re.sub(r"\s*\([^()]*\)\s*$", "", n).strip()
        if n in aliases:
            return aliases[n]
    return None


def read_created_anchor(lines: list[str]) -> tuple[str | None, dt.datetime | None]:
    """Find and parse the `Created:` wallclock from the file preamble."""
    for line in lines[:30]:
        m = re.search(r"Created[:\s]+(.+)", line, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1).strip().strip('"').strip()
        for fmt in CREATED_FORMATS:
            try:
                return raw, dt.datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return raw, None  # found the line but couldn't parse the format
    return None, None


def find_header_row(lines: list[str], aliases: dict[str, str]) -> int:
    """Index of the channel-name header row: the line whose comma-split tokens
    best match known channels (and/or contains a time column)."""
    best_idx, best_score = 0, -1
    for i, line in enumerate(lines[:40]):
        tokens = next(csv.reader([line]), [])
        if len(tokens) < 2:
            continue
        score = sum(1 for tok in tokens if match_channel(tok, aliases))
        if any(_clean(tok) in TIME_TOKENS for tok in tokens):
            score += 1
        if score > best_score:
            best_idx, best_score = i, score
    return best_idx


def ingest(csv_path: pathlib.Path, channels_yaml: pathlib.Path, conn=None) -> dict:
    aliases = load_aliases(channels_yaml)
    text = csv_path.read_text(errors="ignore")
    lines = text.splitlines()

    created_raw, created_dt = read_created_anchor(lines)
    header_idx = find_header_row(lines, aliases)

    # Read from the detected header row. Drop a units row (any leading row whose
    # time column isn't numeric) and any all-blank columns.
    df = pd.read_csv(io.StringIO(text), skiprows=header_idx)
    df = df.dropna(axis=1, how="all")
    df.columns = [str(c) for c in df.columns]

    # Identify the time/offset column.
    time_col = next((c for c in df.columns if _clean(c) in TIME_TOKENS), df.columns[0])
    df[time_col] = pd.to_numeric(df[time_col], errors="coerce")
    df = df.dropna(subset=[time_col]).reset_index(drop=True)  # drops units row

    # Map channels.
    matched: dict[str, str] = {}   # source column -> canonical
    unmatched: list[str] = []
    for col in df.columns:
        if col == time_col:
            continue
        canon = match_channel(col, aliases)
        if canon:
            matched[col] = canon
        else:
            unmatched.append(col)

    duration_s = float(df[time_col].max() - df[time_col].min()) if len(df) else 0.0
    anchor = created_dt or dt.datetime.fromtimestamp(csv_path.stat().st_mtime)
    anchor_source = "Created" if created_dt else "file mtime (fallback)"

    report = {
        "file": csv_path.name,
        "created_raw": created_raw,
        "anchor": anchor.strftime(TS_FMT),
        "anchor_source": anchor_source,
        "header_row": header_idx,
        "time_column": time_col,
        "rows": len(df),
        "duration_s": round(duration_s, 2),
        "channels_matched": sorted(set(matched.values())),
        "channels_unmatched": unmatched,
    }
    present = set(matched.values())
    report["required_missing"] = {g: [c for c in chans if c not in present] for g, chans in REQUIRED.items()}
    report["required_missing"] = {k: v for k, v in report["required_missing"].items() if v}
    report["recommended_missing"] = {g: [c for c in chans if c not in present] for g, chans in RECOMMENDED.items()}
    report["recommended_missing"] = {k: v for k, v in report["recommended_missing"].items() if v}

    # ---- write logs + samples ----
    if conn is not None:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO logs(filename, created_wallclock, duration_s, channel_count, imported_at) "
            "VALUES (?,?,?,?,?)",
            (csv_path.name, anchor.strftime(TS_FMT), round(duration_s, 3), len(matched), now_iso()),
        )
        log_id = cur.lastrowid

        rows = []
        offsets = df[time_col].tolist()
        for src_col, canon in matched.items():
            series = pd.to_numeric(df[src_col], errors="coerce")
            for off, val in zip(offsets, series):
                if pd.isna(val):
                    continue
                ts_abs = (anchor + dt.timedelta(seconds=float(off))).strftime(TS_FMT)
                rows.append((log_id, ts_abs, canon, float(val)))
        cur.executemany("INSERT INTO samples(log_id, ts_abs, channel, value) VALUES (?,?,?,?)", rows)
        conn.commit()
        report["log_id"] = log_id
        report["samples_written"] = len(rows)

    return report


def format_report_text(rep: dict) -> str:
    lines = ["=== TuneTrack ingest report (component 01) ==="]
    for k in ("file", "created_raw", "anchor", "anchor_source", "header_row",
              "time_column", "rows", "duration_s", "log_id", "samples_written"):
        if k in rep:
            lines.append(f"{k:>18}: {rep[k]}")
    lines.append(f"{'matched':>18}: {len(rep['channels_matched'])} -> {rep['channels_matched']}")
    lines.append(f"{'unmatched':>18}: {rep['channels_unmatched']}")
    if rep.get("required_missing"):
        lines.append("")
        lines.append("  !! REQUIRED CHANNELS MISSING (scoring needs these):")
        for group, chans in rep["required_missing"].items():
            lines.append(f"     - {group}: {chans}")
    else:
        lines.append(f"{'required':>18}: all present (core + fuel pressure)")
    if rep.get("recommended_missing"):
        lines.append("  note: optional channels not logged (feature disabled, run still scores):")
        for group, chans in rep["recommended_missing"].items():
            lines.append(f"     - {group}: {chans}")
    return "\n".join(lines)


def print_report(rep: dict) -> None:
    print("\n" + format_report_text(rep))


def write_parse_report(rep: dict, reports_dir) -> pathlib.Path:
    """Write the parse report (.txt + .json) into the reports directory (03_Reports)."""
    rdir = pathlib.Path(reports_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    base = pathlib.Path(rep["file"]).stem
    txt = rdir / f"parse_report_{base}_{stamp}.txt"
    txt.write_text(format_report_text(rep) + "\n")
    (rdir / f"parse_report_{base}_{stamp}.json").write_text(json.dumps(rep, indent=2, default=str))
    return txt


def process_inbox(inbox_dir, channels_yaml, conn, reports_dir) -> list[dict]:
    """Ingest every CSV in the watched inbox folder, writing a parse report for each."""
    inbox = pathlib.Path(inbox_dir)
    csvs = sorted(inbox.glob("*.csv"))
    if not csvs:
        print(f"component 01: no CSVs found in inbox {inbox}")
        return []
    out = []
    for csv_path in csvs:
        rep = ingest(csv_path, pathlib.Path(channels_yaml), conn)
        print_report(rep)
        p = write_parse_report(rep, reports_dir)
        print(f"{'report ->':>18}: {p}")
        out.append(rep)
    return out


if __name__ == "__main__":
    cfg = load_config()
    ap = argparse.ArgumentParser(description="Component 01 — ingest VCM Scanner CSV(s).")
    ap.add_argument("csv", nargs="?", help="a single CSV to ingest (omit when using --inbox)")
    ap.add_argument("--inbox", action="store_true",
                    help=f"process every CSV in inbox_dir ({cfg['inbox_dir']})")
    ap.add_argument("--channels", default=str(ROOT / "channels.yaml"))
    ap.add_argument("--db", default=cfg["db_path"])
    ap.add_argument("--reports", default=cfg["reports_dir"], help="where parse reports are written")
    ap.add_argument("--no-write", action="store_true", help="parse + report only, no DB write")
    ap.add_argument("--no-report-file", action="store_true", help="don't write a report file")
    a = ap.parse_args()

    conn = None
    if not a.no_write:
        conn = connect(pathlib.Path(a.db))
        init_db(conn)

    if a.inbox:
        process_inbox(cfg["inbox_dir"], a.channels, conn, a.reports)
    elif a.csv:
        rep = ingest(pathlib.Path(a.csv), pathlib.Path(a.channels), conn)
        print_report(rep)
        if not a.no_report_file:
            print(f"{'report ->':>18}: {write_parse_report(rep, a.reports)}")
    else:
        ap.error("provide a CSV path, or use --inbox to process the watched folder")
