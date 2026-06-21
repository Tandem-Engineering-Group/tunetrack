-- TuneTrack catalog
CREATE TABLE IF NOT EXISTS logs (
  log_id INTEGER PRIMARY KEY, filename TEXT, created_wallclock TEXT,
  duration_s REAL, channel_count INTEGER, imported_at TEXT);
CREATE TABLE IF NOT EXISTS samples (
  log_id INTEGER, ts_abs TEXT, channel TEXT, value REAL);
CREATE INDEX IF NOT EXISTS ix_samples ON samples(log_id, ts_abs);
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY, log_id INTEGER, ts_start TEXT, ts_end TEXT,
  source TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS build_state (
  state_id INTEGER PRIMARY KEY, date_from TEXT, date_to TEXT, upper_pulley TEXT,
  lower_pulley TEXT, snout TEXT, pump TEXT, injectors TEXT, e85_pct REAL,
  boost_target_psi REAL, belt_pn TEXT, tune_rev TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS timeslips (
  slip_id INTEGER PRIMARY KEY, run_clock_time TEXT, lane TEXT, rt REAL, sixty REAL,
  threethirty REAL, eighth_et REAL, eighth_mph REAL, thousand REAL, quarter_et REAL,
  quarter_mph REAL, raw_image_path TEXT);
CREATE TABLE IF NOT EXISTS weather (
  wx_id INTEGER PRIMARY KEY, obs_time TEXT, temp_c REAL, humidity_pct REAL,
  baro_kpa REAL, density_altitude_ft REAL);
CREATE TABLE IF NOT EXISTS tire_state (
  tire_id INTEGER PRIMARY KEY, run_id INTEGER, compound TEXT, set_id TEXT,
  heat_cycles INTEGER, cold_psi_f REAL, cold_psi_r REAL, hot_psi_f REAL, hot_psi_r REAL,
  pyro_r_in REAL, pyro_r_center REAL, pyro_r_out REAL,
  pyro_l_in REAL, pyro_l_center REAL, pyro_l_out REAL, rollout_in REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS track_state (
  track_id INTEGER PRIMARY KEY, run_id INTEGER, surface_temp_c REAL, air_temp_c REAL,
  prep TEXT, lane TEXT, time_of_day TEXT, bite_rating REAL);
CREATE TABLE IF NOT EXISTS eval_results (
  run_id INTEGER, slip_id INTEGER, state_id INTEGER, wx_id INTEGER, tire_id INTEGER,
  track_id INTEGER, json_power TEXT, json_traction TEXT, score REAL, flags TEXT,
  created_at TEXT);

-- Portals
CREATE TABLE IF NOT EXISTS maintenance_items (
  item_id INTEGER PRIMARY KEY, system TEXT, name TEXT, interval_kind TEXT,
  interval_value REAL, last_done TEXT, last_value REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS maintenance_log (
  log_id INTEGER PRIMARY KEY, item_id INTEGER, done_at TEXT, at_value REAL, notes TEXT);
CREATE TABLE IF NOT EXISTS season_events (
  event_id INTEGER PRIMARY KEY, date TEXT, track TEXT, type TEXT, status TEXT,
  target_et REAL, result_run_id INTEGER, notes TEXT);

-- Analysis / forecast / retune (from CLAUDE.md data model)
CREATE TABLE IF NOT EXISTS analysis_results (
  analysis_id INTEGER PRIMARY KEY, run_id INTEGER, state_id INTEGER, knock_map_json TEXT,
  lambda_error_map_json TEXT, boost_vs_target_json TEXT, fuel_headroom_json TEXT,
  heat_json TEXT, passes_used INTEGER, gate_passed INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS forecast (
  forecast_id INTEGER PRIMARY KEY, for_window TEXT, da_ft REAL, da_uncertainty REAL,
  track_temp_c REAL, source TEXT, tire_heat_cycles INTEGER, created_at TEXT);
CREATE TABLE IF NOT EXISTS retune_recommendations (
  rec_id INTEGER PRIMARY KEY, analysis_id INTEGER, forecast_id INTEGER, table_target TEXT,
  cell TEXT, current_value REAL, recommended_value REAL, delta REAL, evidence TEXT,
  confidence REAL, guardrail_flag TEXT, rationale TEXT, status TEXT, created_at TEXT);
