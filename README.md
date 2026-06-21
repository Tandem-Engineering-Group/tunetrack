# TuneTrack

Closed-loop drag-pass analysis + pre-run readiness for a 2020 Dodge Challenger SRT
Hellcat Redeye (6.2 supercharged, E85, 1,000+ whp target). It ingests HP Tuners VCM
Scanner logs and drag timeslips, correlates them by clock time, scores each pass on
**power** and **traction**, models the day's **air** and **tire/track**, runs a deep
engine analysis, forecasts the next run's conditions, and produces a **retune advisory**
for the human to apply in VCM Editor.

> **Read-only with respect to the PCM.** TuneTrack analyzes and recommends. It never
> writes, flashes, or generates a calibration. Tuning decisions stay human.

## The four portals (`web/`)

Open `web/index.html` for the hub.

| Portal | What it shows |
|--------|---------------|
| **Run data** (`runviewer.html`) | Per-pass playback: gauges, power + traction scorecards, green-light tile |
| **Engine** (`engine.html`) | Animated engine model — airflow, boost, knock, fueling, heat — with each sensor's live meaning |
| **Maintenance** (`maintenance.html`) | Service status across engine / blower / fuel / driveline / tires |
| **Season** (`season.html`) | 2026 planned runs, results, and the ET trend toward goal |

Portals run on seed data today; in the build they read `tunetrack.db` (read-only) as the
pipeline fills it.

## Pipeline (13 components)

`01` ingest → `02` segment WOT pulls → `03` build-state → `04` timeslip → `05` weather/DA
→ `06` tire/track → `07` power scorecard → `08` traction scorecard → `09` green-light
channels → **data-quality gate** → `10` deep run analysis → `11` next-run forecast →
`12` retune advisory → `13` report + season trends.

See `CLAUDE.md` for the full spec, data model, and guardrails.

## Quickstart (Claude Code)

1. Open this folder in Claude Code.
2. Paste the contents of `FIRST_PROMPT.md`.
3. Drop a VCM Scanner CSV in `samples/`.
4. Open `web/index.html` to see the portals.

## Publish / share

See `GITHUB_SETUP.md` to push this to a private repo and invite the team.

## Structure

```
CLAUDE.md         spec / source of truth (read first)
FIRST_PROMPT.md   paste into Claude Code to start
GITHUB_SETUP.md   push + team-invite steps
schema.sql        SQLite catalog DDL
channels.yaml     VCM channel alias map
src/ingest.py     component 01 stub
web/              index, runviewer, engine, maintenance, season
samples/          drop VCM CSVs here (gitignored)
```

## For the team

- Clone, then open `web/index.html` in any browser to explore the portals — no build step.
- Don't commit logs or the local DB; `.gitignore` already excludes `tunetrack.db` and
  `samples/*.csv`.
- The PCM boundary is a hard rule: this project reads and recommends only.
