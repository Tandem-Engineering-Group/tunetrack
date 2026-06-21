# Paste this into Claude Code from the project root

Read CLAUDE.md fully — it is the source of truth, including the hard read-only-PCM
boundary. Then build the pipeline in the component order it lists (01 → 10), smoke-testing
on a sample log after each.

Start now with component 01 (ingest + normalize):
- Look in samples/ for a VCM Scanner CSV. Read its real header and the `Created`
  wall-clock anchor.
- Finalize channels.yaml against the actual column names you find (add any missing
  canonical mappings; confirm fuel pressure and the four wheel-speed channels are present
  — flag me if they are not logged).
- Create the SQLite catalog from schema.sql and load the sample into `logs` + `samples`,
  keyed on absolute timestamp.
- Print a parse report: row count, channels matched/unmatched, time span, Created anchor.

Do not write, flash, or generate any PCM calibration. This project only reads and
evaluates. When 01 passes its smoke test, stop and show me the parse report before moving
to 02.
