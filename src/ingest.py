"""Component 01 — ingest + normalize a VCM Scanner CSV into the TuneTrack catalog.

STUB: the header/timestamp parsing is finalized against the real export. VCM Scanner
CSV layouts vary (metadata rows, units rows, channel naming), so confirm against
samples/ before trusting the column logic below.

Read-only with respect to the PCM. This module only reads logs.
"""
from __future__ import annotations
import argparse, sqlite3, datetime as dt, pathlib, re
import pandas as pd, yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
DB = ROOT / "tunetrack.db"

def load_aliases(path: pathlib.Path) -> dict[str, str]:
    """variant column name (lower) -> canonical name."""
    raw = yaml.safe_load(path.read_text())
    out = {}
    for canon, variants in raw.items():
        for v in variants:
            out[v.strip().lower()] = canon
    return out

def read_created_anchor(csv_path: pathlib.Path):
    """VCM Scanner writes a 'Created: <wallclock>' near the top. TODO: confirm exact
    location/format against a real export and parse to a datetime."""
    head = csv_path.read_text(errors="ignore").splitlines()[:15]
    for line in head:
        m = re.search(r"Created[:\s]+(.+)", line)
        if m:
            return m.group(1).strip()
    return None  # fall back to file mtime if absent

def ingest(csv_path: pathlib.Path, channels_yaml: pathlib.Path) -> dict:
    aliases = load_aliases(channels_yaml)
    created = read_created_anchor(csv_path)
    # TODO: skiprows to the real header row once confirmed.
    df = pd.read_csv(csv_path)
    matched, unmatched = {}, []
    for col in df.columns:
        canon = aliases.get(col.strip().lower())
        (matched.__setitem__(col, canon) if canon else unmatched.append(col))
    report = {
        "file": csv_path.name,
        "created_anchor": created,
        "rows": len(df),
        "channels_matched": sorted(set(matched.values())),
        "channels_unmatched": unmatched,
    }
    # TODO: write logs + samples rows here once header logic is locked.
    return report

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--channels", default=str(ROOT / "channels.yaml"))
    a = ap.parse_args()
    rep = ingest(pathlib.Path(a.csv), pathlib.Path(a.channels))
    print("\n=== TuneTrack ingest report ===")
    for k, v in rep.items():
        print(f"{k:>20}: {v}")
