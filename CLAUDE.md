# TuneTrack — Drag Pass Evaluation Pipeline

> Claude Code project bootstrap. Read top to bottom before scaffolding.
> Suggested location: `C:\011 TuneTrack` (rename to fit the numbered convention).

## What this is

A **post-run analysis + pre-run readiness** system for a 2020 Dodge Challenger SRT
Hellcat Redeye (6.2 supercharged, target 1,000+ whp on E85). It ingests HP Tuners
**VCM Scanner** datalogs and **drag-strip timeslips**, correlates them by wall-clock
time, scores each pass on both **power** and **traction**, models the day's **air**
and the **tire/track** behavior, and surfaces a pre-stage **green light** confirming
every controllable variable is in its modeled window before you launch. Once a run's
data is validated, it runs a **deep engine analysis**, **forecasts the next run's
conditions**, and produces a **retune advisory** — a bounded, evidence-tagged set of
recommended changes for the human to apply in VCM Editor.

## Hard boundary (do not cross)

Read-only with respect to the PCM. Never writes, flashes, or generates calibration
files; never connects to the vehicle to command anything. It reads logs and live data
and evaluates them. Tuning changes remain a human decision made in VCM Editor.

The **retune advisory** (components 10–12) is bound by the same line: it outputs a
recommendation sheet and a VCM Editor diff list — human-readable change proposals with
evidence — and **never** emits a ready-to-flash calibration. Additional guardrails:
- Never recommend beyond demonstrated-safe values. Anything into new territory (more
  spark or boost than has been proven on this combo) is flagged "step in incrementally,"
  not handed over as a number to dial.
- Fuel and safety outrank power. If injector duty or fuel pressure indicates the fuel
  system is maxed, recommend fixing fueling first and withhold timing-add suggestions
  until there is headroom.
- Every recommendation carries its evidence (which pass/cell), magnitude, confidence,
  and a one-line rationale. The human reviews, applies, and runs a validation pass.

## Operating philosophy

You can't remove variables — you account for them. Controllable variables (temps,
pressures, fuel) get held inside a modeled window and confirmed green before staging.
Uncontrollable ones (air, track surface) get modeled and corrected so comparisons are
fair and targets shift with conditions. Driver reaction time is tracked as its own
variable, separate from the car.

## Stack

- Windows (Threadripper), Claude Code desktop. In-car: VCM Scanner on the Surface.
- Python 3.11+, `pandas`, `sqlite3` (stdlib), `pyarrow`
- OCR (timeslip photos): `pytesseract` + Tesseract, or hand images to Claude
- Charts (later): `plotly`
- One SQLite catalog: `tunetrack.db`

## The keystone: clock-time correlation

VCM Scanner logs carry a wall-clock start (e.g. `Created: 2026-06-20 11:00:53 AM`);
each row is elapsed seconds from it.

```
target_row_time = log_created_wallclock + row_elapsed_seconds
pull_window     = rows where |target_row_time - run_clock_time| <= window_seconds
```

Ingest MUST capture each log's `Created` anchor. Locate a pass by (a) the reported
clock time or (b) auto WOT segmentation. Default window ±20 s, snap to nearest WOT pull.

## In-car green-light layer (VCM Scanner, on the Surface)

Recommended home: VCM Scanner on the Surface — it is the only in-car tool that sees the
enhanced channels (LTR coolant, real boost, fuel pressure, injector duty). A second OBD
reader/tablet is limited to generic PIDs and risks bus contention with the MPVI; a
dedicated dash is a hardware project that still can't read PCM-internal values without
CAN work. The green light is a **pre-stage gate** — glance as you stage, then eyes on
the tree.

Build it as **calculated channels** bound to gauges:

- **`ready_go`** — boolean AND of all in-window conditions, e.g.
  `ECT in [a,b] AND IAT < x AND fuel_press > y AND ltr_coolant in [c,d] AND boost_ok`.
  Output 1/0; bind to one large gauge, green at 1, red at 0. On red, the contributing
  channel that fell out is identifiable.
- **`rear_slip_pct`** — from wheel-speed logging: driven (rear) vs non-driven (front),
  `slip = (rear_speed - front_speed) / front_speed`. Live launch-spin measurement.

> Confirm exact math-channel expression syntax against the installed VCM Scanner version.
> The app mirrors the same readiness tile + checklist that the window inputs are populated.

## Portals (`web/`)

Four self-contained front-end portals share one read-only data layer. Today they run on
seed data; in the build they read `tunetrack.db` (read-only views) as the pipeline fills
it. None of them write to the PCM.

- `index.html` — **hub** linking the four portals.
- `runviewer.html` — **run data**: per-pass playback, gauges, power + traction scorecards,
  green-light tile. Driven by `runs` + `samples` + `eval_results`.
- `engine.html` — **engine portal**: animated engine model with each sensor's live meaning.
  Driven (later) by a selected run's `samples`; today a simulation.
- `maintenance.html` — **service status** across engine/blower/fuel/driveline/tires with
  OK / due-soon / overdue. Driven by `maintenance_items` + `maintenance_log`.
- `season.html` — **2026 planned runs**, results, and the ET-vs-goal trend. Driven by
  `season_events` joined to per-event results from the pipeline.

Wiring step (later): a tiny read-only API (or a static JSON export written by `13_report`)
feeds the portals from `tunetrack.db`. Keep the portals dumb — they render data, never
mutate the calibration.

## Build order (components)

1. **`01_ingest_normalize`** — Parse VCM CSV, read `Created` anchor, map channels via
   alias table, write tidy `samples` keyed on absolute timestamp. Emit a parse report.
2. **`02_segment_runs`** — Detect WOT pulls (`TPS>=95%` + sustained MAP rise). Tag
   start/end → `runs`. Accept a manual clock time to carve a window.
3. **`03_build_state`** — Registry of car config per date range (pulley, snout, pump,
   injectors, E85 %, boost target, belt, tune rev).
4. **`04_timeslip_ingest`** — Manual or photo OCR: RT, 60', 330', 1/8 ET+MPH, 1000',
   1/4 ET+MPH, run clock time, lane.
5. **`05_weather_da`** — Per-pass conditions + computed **density altitude**. Required
   for valid cross-run comparison.
6. **`06_tire_track`** — Capture `tire_state` + `track_state` per pass (see model below).
7. **`07_eval_power`** — Power/safety scorecard (knock, lambda, belt slip, injector duty,
   fuel pressure, heat soak, EGT).
8. **`08_eval_traction`** — Traction scorecard (60-ft vs slip, pyrometer profile,
   pressure sensitivity model).
9. **`09_greenlight`** — Define/maintain the `ready_go` + `rear_slip_pct` calc-channel
   definitions; readiness checklist in the app.

> **Data-quality gate.** Components 10–12 run only after a run passes validation: log
> covers the full pull, required channels present (incl. fuel pressure + wheel speeds),
> timeslip + DA attached, no clipped/dropped samples. A run that fails the gate is
> scored but excluded from retune recommendations.

10. **`10_analyze`** — Deep, cell-resolved engine analysis, aggregated across passes:
    knock retard by RPM×boost cell; measured-vs-commanded lambda map; actual spark and
    knock margin; boost curve vs target + belt-slip departure RPM; injector-duty and
    fuel-pressure headroom vs RPM; IAT/aircharge and EGT heat. Output → `analysis_results`.
11. **`11_forecast`** — Predict the next pass's environment: density altitude + track
    temp from the session trend (evening cool-down) and/or a weather pull for the track
    location/time; tire heat-cycle state. Output → `forecast` with uncertainty.
12. **`12_retune`** — Translate analysis + forecast into a bounded, evidence-tagged
    change set mapped to VCM Editor tables (spark by cell, commanded EQ, boost target,
    launch pressure). Enforce the guardrails in the Hard boundary section. Output →
    `retune_recommendations` (a sheet + a diff list). **Never flashes.**
13. **`13_report`** — Per-pass scorecard (power + traction), the retune sheet, and
    season trends.

## Data model (SQLite — `tunetrack.db`)

- `logs(log_id, filename, created_wallclock, duration_s, channel_count, imported_at)`
- `samples(log_id, ts_abs, channel, value)` — index (log_id, ts_abs)
- `runs(run_id, log_id, ts_start, ts_end, source, notes)`
- `build_state(state_id, date_from, date_to, upper_pulley, lower_pulley, snout, pump,
  injectors, e85_pct, boost_target_psi, belt_pn, tune_rev, notes)`
- `timeslips(slip_id, run_clock_time, lane, rt, sixty, threethirty, eighth_et,
  eighth_mph, thousand, quarter_et, quarter_mph, raw_image_path)`
- `weather(wx_id, obs_time, temp_c, humidity_pct, baro_kpa, density_altitude_ft)`
- `tire_state(tire_id, run_id, compound, set_id, heat_cycles, cold_psi_f, cold_psi_r,
  hot_psi_f, hot_psi_r, pyro_r_in, pyro_r_center, pyro_r_out, pyro_l_in, pyro_l_center,
  pyro_l_out, rollout_in, notes)`
- `track_state(track_id, run_id, surface_temp_c, air_temp_c, prep['PJ1'|'VHT'|'none'],
  lane, time_of_day, bite_rating)`
- `eval_results(run_id, slip_id, state_id, wx_id, tire_id, track_id, json_power,
  json_traction, score, flags, created_at)`
- `analysis_results(analysis_id, run_id or session_id, state_id, knock_map_json,
  lambda_error_map_json, boost_vs_target_json, fuel_headroom_json, heat_json,
  passes_used, gate_passed, created_at)`
- `forecast(forecast_id, for_window, da_ft, da_uncertainty, track_temp_c, source,
  tire_heat_cycles, created_at)`
- `retune_recommendations(rec_id, analysis_id, forecast_id, table_target, cell,
  current_value, recommended_value, delta, evidence, confidence, guardrail_flag,
  rationale, status['proposed'|'applied'|'rejected'], created_at)`
- `maintenance_items(item_id, system, name, interval_kind['miles'|'passes'|'time'|
  'heat_cycles'|'event'], interval_value, last_done, last_value, notes)`
- `maintenance_log(log_id, item_id, done_at, at_value, notes)`
- `season_events(event_id, date, track, type, status['planned'|'next'|'done'|'cancelled'],
  target_et, result_run_id, notes)`

## Channel alias map (config: `channels.yaml`)

Finalize against the real CSV header. Canonical → known variants:

```yaml
engine_rpm:         ["Engine RPM"]
vehicle_speed:      ["Vehicle Speed"]
ect_c:              ["Engine Coolant Temp"]
oil_temp_c:         ["Engine Oil Temp"]
oil_press_kpa:      ["Engine Oil Pressure"]
ltr_coolant_c:      ["LTR Coolant Temp", "Low Temp Rad Coolant"]
ltr_pump_rpm:       ["LTR Pump Speed"]
aircharge_temp_c:   ["Aircharge Temperature", "IAT"]
map_kpa:            ["Manifold Absolute Pressure", "Sensed MAP"]
tps_pct:            ["Throttle Position (SAE)", "TPS"]
knock_retard_total: ["Total Knock Retard"]
eq_commanded:       ["Equivalence Ratio Commanded"]
wb_eq_1:            ["WB EQ Ratio 1 (SAE) (2)", "WB EQ Ratio 1"]
wb_eq_2:            ["WB EQ Ratio 2"]
inj_duty_pct:       ["Injector Duty", "INJ Duty"]
egt_c:              ["Exhaust Gas Temperature"]
stft_b1:            ["Short Term Fuel Trim Bank 1"]
ltft_b1:            ["Long Term Fuel Trim Bank 1"]
# ADD: fuel_press_kpa (E85 survival metric — must be logged)
# ADD: wheel speeds for slip — driven vs non-driven:
wheel_speed_rl:     ["Wheel Speed RL", "Rear Left Wheel Speed"]
wheel_speed_rr:     ["Wheel Speed RR", "Rear Right Wheel Speed"]
wheel_speed_fl:     ["Wheel Speed FL", "Front Left Wheel Speed"]
wheel_speed_fr:     ["Wheel Speed FR", "Front Right Wheel Speed"]
```

## Power / safety scorecard (per pull)

- Knock: peak total retard + the exact RPM/MAP cell. FLAG >1.0° under boost; HARD >2.0°.
- Lambda vs command: FLAG lean excursion >3% above ~10 psi.
- Belt slip (post-pulley priority): boost rising then falling at high RPM while command
  holds → suspected slip; call the departure RPM; cross-check trap MPH.
- Injector duty: FLAG >85%, HARD >90%.
- Fuel pressure: FLAG any WOT drop vs base (pump signing off).
- Heat soak: IAT trend across staged passes vs ET/MPH falloff.
- EGT: flag outside safe band for the blend.

## Traction scorecard (per pull)

Two independent reads on optimal launch pressure:

- **Outcome read** — 60-ft and peak `rear_slip_pct` as a function of launch pressure
  and track temp → sensitivity model (Δ60-ft per psi, per °C). Predict tonight's optimal
  launch pressure from conditions.
- **Physical read** — pyrometer cross-tread profile after the run. Center > edges =
  over-inflated; edges > center = under-inflated. A pressure call independent of ET.
- **Live spin** — `rear_slip_pct` time-series locates the spin window
  ("spun 1.2–1.8 s, drop 2 psi") instead of inferring from a slow 60-ft.
- Convergence check: flag when outcome read and pyrometer read disagree on pressure.

## Retune advisory stage (components 10–12)

Runs after the data-quality gate. Closes the loop: analyze the validated pass(es) →
forecast the next run's conditions → recommend the tune for those conditions → human
applies in VCM Editor → validation pass feeds back.

What the recommendations look like (each row in `retune_recommendations`):
- **Spark** — pull N° at the specific RPM×boost cells where knock appeared, with margin;
  conservatively add back only where margin is large and no knock was seen across passes.
- **Commanded EQ / fueling** — richen lean cells; but if injector duty or fuel pressure
  shows the fuel system is maxed, withhold timing adds and recommend fueling fixes first.
- **Boost target** — adjust for the forecast DA (denser air next run shifts the curve);
  if belt slip was detected, recommend tension/wrap check rather than commanding more.
- **Launch pressure** — from the traction sensitivity model at the forecast track temp,
  cross-checked against the pyrometer read; flag when the two disagree.

Each recommendation is advisory only — evidence + magnitude + confidence + guardrail
flag — emitted as a sheet and a VCM Editor diff list. Nothing is flashed. After the
human applies and runs again, the next pass validates the change (did KR clear at that
cell? did the lean spot resolve?) and the loop continues.

## Cross-run trends

- ET / trap MPH vs **DA-corrected** baseline (never raw).
- Trap MPH = power; ET / 60-ft = traction. Divergence says chase power vs traction.
- Recurring knock cell → a specific tune target (report, do not act).
- Boost-vs-RPM drift over time → belt/pulley health.
- Launch-pressure sweet spot vs track temp → the tire/track response surface.
- Driver RT consistency, tracked separately.

## Kickoff checklist

1. Drop a sample VCM CSV in `./samples/`; finalize `channels.yaml` + confirm the
   `Created` timestamp format and that wheel-speed + fuel-pressure channels are logging.
2. Enter current `build_state` (post 3" upper pulley, current pump/injectors, E85 %).
3. Draft the `ready_go` and `rear_slip_pct` calc-channel expressions for VCM Scanner.
4. Build 01→13 in order, smoke-testing on the sample log after each. Components 10–12
   (analysis, forecast, retune advisory) come last and run behind the data-quality gate.
5. First deliverable: one real pass + timeslip + DA + tire/track row → full scorecard,
   then a retune sheet for a forecast next-run condition.
