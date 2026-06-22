# TuneTrack — Teams / SharePoint data wiring

Code lives in the repo (GitHub). **Data** lives in the Microsoft Teams "Track Tune"
document library, synced to this machine and up to SharePoint for the whole team.
The two never mix: **no data files are committed to git; no code lives in the Teams
library.** The pipeline reads inputs from and writes outputs to the Teams folders.

## Folder tree (in the Teams-synced library)

Detected automatically by the setup script under `…/TGCS/Track Tune - General/`:

```
01_Inbox/                raw VCM Scanner CSVs land here (the watched folder = inbox_dir)
02_Runs/                 one folder per event, named YYYY-MM-DD_Track
03_Reports/              pipeline outputs: parse reports, scorecards, retune sheets, trends, portal JSON
04_Build and Tuning/     1000-whp roadmap, parts, dyno sheets, tune revisions
05_Maintenance/          service records
06_Season 2026/          schedule, results, planning
07_Project Docs/         CLAUDE.md / HANDOFF / this file / decks / wiring diagram / portal exports
08_Archive/              superseded files
```

Each per-event folder under `02_Runs/` (e.g. `2026-07-11_GrandBend/`) holds:
`vcm_log.csv`, `timeslip.jpg`, `dragy.csv`, `kestrel.csv`, `tire_track.txt`, optional `video.mp4`.

## One-time setup

1. **Create the tree** (run on the machine with the Teams sync):
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\setup_teams_folders.ps1
   ```
   It confirms the exact library path (the name may differ slightly), builds the
   eight folders, seeds an example run folder with placeholders, and copies the
   reference docs into `07_Project Docs/`.

2. **Point the pipeline at it.** In the repo, copy the template and edit paths:
   ```powershell
   copy config.example.yaml config.yaml
   ```
   ```yaml
   inbox_dir:   "C:/Users/RL.Admin/TGCS/Track Tune - General/01_Inbox"
   runs_dir:    "C:/Users/RL.Admin/TGCS/Track Tune - General/02_Runs"
   reports_dir: "C:/Users/RL.Admin/TGCS/Track Tune - General/03_Reports"
   db_path:     "tunetrack.db"
   ```
   `config.yaml` is git-ignored. If it's absent, the pipeline falls back to
   repo-relative `samples/` and `reports_out/` so the synthetic demo still runs.

## The loop

```
Drop vcm_log.csv in 01_Inbox  ->  python src/ingest.py --inbox
   -> loads logs+samples into tunetrack.db
   -> writes a parse report (.txt + .json) into 03_Reports
   -> flags any missing REQUIRED channels (fuel pressure + 4 wheel speeds)
```

- `python src/ingest.py --inbox` processes every CSV in `inbox_dir`.
- `python src/ingest.py "path\to\one.csv"` processes a single file.
- The full pipeline (`python src/pipeline.py`) also drops a `portal_data.json`
  copy into `03_Reports` (the live web portals read `web/data.js` from the repo).

## Guardrails

- **Never commit** `tunetrack.db`, the real `config.yaml`, or anything under the
  Teams library. (All git-ignored.)
- **Read-only with respect to the PCM** — the pipeline reads logs and recommends;
  it never writes, flashes, or commands a calibration.
- Data belongs in the Teams library; code belongs in the repo.
