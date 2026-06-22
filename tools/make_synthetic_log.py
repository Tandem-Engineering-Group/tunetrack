"""Generate a realistic *synthetic* VCM Scanner CSV for end-to-end demo runs.

Rebuilt to mirror the real HP Tuners logs (Alea McLellan, 2026-06): the channel
set matches what the car actually logs -- per-cylinder Injector Pulse Width (not a
duty channel), Barometric Pressure, Actual Spark + MBT, Desired vs actual Fuel
Pressure, Supercharger Bypass, gear/shift, torque model, misfire -- and there are
NO wheel-speed channels (so the pipeline runs traction off 60-ft + pyro). The tune
is modelled boost-limited (~11 psi) to match the `ZHT ... boost limited` cal.

All synthetic. NOTHING here touches the vehicle or a calibration.
"""
from __future__ import annotations
import argparse
import pathlib
import datetime as dt
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (name, unit) in column order. Names match channels.yaml variants.
COLUMNS = [
    ("Offset", "s"), ("Engine RPM", "RPM"), ("Vehicle Speed", "MPH"),
    ("Trans Current Gear", ""), ("Shift ID", ""),
    ("Barometric Pressure", "kPa"), ("Manifold Absolute Pressure", "kPa"),
    ("Throttle Position (SAE)", "%"),
    ("Ambient Air Temp", "deg C"),
    ("Aircharge Temperature", "deg C"), ("Engine Coolant Temp", "deg C"),
    ("Engine Oil Temp", "deg C"), ("Engine Oil Pressure", "kPa"),
    ("LTR Coolant Temp", "deg C"), ("LTR Pump Speed", "RPM"),
    ("Total Airflow", "g/s"), ("Cylinder Airmass", "mg"),
    ("Supercharger Bypass Pos 1", "%"),
    ("Actual Spark", "deg"), ("MBT Advance", "deg"),
    ("Total Knock Retard", "deg"), ("Knock Sensor 1", "V"), ("Knock Sensor 2", "V"),
    ("Equivalence Ratio Commanded", ""), ("WB EQ Ratio 1 (SAE) (2)", ""), ("WB EQ Ratio 2", ""),
    ("Desired Fuel Pressure", "kPa"), ("Fuel Pressure (SAE)", "kPa"),
] + [(f"Injector Pulse Width Cyl {i}", "ms") for i in range(1, 9)] + [
    ("Exhaust Gas Temperature", "deg C"),
    ("Actual Torque", "N m"), ("Expected Torque", "N m"), ("Driver Demand Torque", "N m"),
    ("Control Module Voltage (SAE)", "V"),
] + [(f"Misfire Current Cylinder #{i}", "") for i in range(1, 9)]

BOOST_TARGET_KPA = 175.0  # ~11 psi over baro (boost-limited)


def build(seed: int = 7):
    rng = np.random.default_rng(seed)
    dt_s = 0.04
    t = np.arange(0.0, 20.0 + dt_s / 2, dt_s)
    n = len(t)

    def nz(s):
        return rng.normal(0.0, s, n)

    launch_t, lift_t = 3.0, 15.0
    stage = (t >= 2.4) & (t < launch_t)
    wot = (t >= launch_t) & (t < lift_t)
    coast = t >= lift_t
    lean = (t >= 12.5) & (t < lift_t)

    tps = np.zeros(n); tps[stage] = 35.0; tps[wot] = 100.0
    tps = np.clip(tps + nz(0.3), 0, 100)
    load = tps / 100.0

    pull = np.clip((t - launch_t) / (lift_t - launch_t), 0, 1)
    speed = np.where(t < launch_t, 0.0, 135.0 * np.sqrt(pull))
    speed = np.where(coast, 135.0 * np.exp(-(t - lift_t) / 8.0), speed)
    speed = np.clip(speed + nz(0.2), 0, None)

    # RPM sawtooth across gears
    rpm = np.full(n, 820.0); rpm[stage] = 1850.0
    shift_t = [launch_t, 4.6, 6.6, 9.2, 12.4]; gear_lo = [3800, 4300, 4500, 4700, 4900]
    rw = np.zeros(n); gear = np.ones(n); shiftid = np.ones(n)
    for i, ts in enumerate(shift_t):
        te = shift_t[i + 1] if i + 1 < len(shift_t) else lift_t
        seg = (t >= ts) & (t < te)
        rw[seg] = gear_lo[i] + (t[seg] - ts) / max(te - ts, 1e-6) * (6300 - gear_lo[i])
        gear[seg] = i + 1; shiftid[seg] = i + 1
    rpm = np.where(wot, rw, rpm)
    rpm = np.where(coast, np.maximum(820.0, 6300.0 * np.exp(-(t - lift_t) / 1.5)), rpm)
    gear[coast] = 5
    rpm = rpm + nz(15)

    baro = 99.0 + nz(0.05)
    map_kpa = np.full(n, 38.0); map_kpa[stage] = 110.0
    map_kpa = np.where(wot, BOOST_TARGET_KPA - 55.0 * np.exp(-(t - launch_t) / 0.5), map_kpa)
    map_kpa = np.where(coast, 34.0, map_kpa)
    map_kpa = np.clip(map_kpa + nz(1.0), 20, 240)
    boost_psi = np.clip((map_kpa - baro) / 6.895, -2, None)

    # knock event (flaggable, not catastrophic) + a tiny second blip
    knock = np.zeros(n)
    k1 = (t >= 5.4) & (t < 6.3); knock[k1] = 1.2 * np.exp(-((t[k1] - 5.85) / 0.22) ** 2)
    knock = np.clip(knock + np.where(wot, np.abs(nz(0.02)), 0.0), 0, None)
    ks1 = 0.25 + np.abs(nz(0.04)) + knock * 0.9
    ks2 = 0.25 + np.abs(nz(0.04)) + knock * 0.8

    mbt = np.where(boost_psi > 3, 18.0 - boost_psi * 0.2, 30.0) + nz(0.2)
    actual_spark = mbt - 3.0 - knock          # running a few deg under MBT, minus any retard
    actual_spark = np.where(boost_psi > 3, actual_spark, mbt - 1.0) + nz(0.15)

    eq_cmd = np.where(boost_psi > 3, 1.28, 1.00) + nz(0.003)
    eq_meas = eq_cmd.copy(); eq_meas[lean] -= np.linspace(0, 0.05, int(lean.sum()))  # mild top-end lean
    eq_meas = eq_meas + nz(0.004)
    eq_meas2 = eq_meas + nz(0.01)

    # healthy fuel system (boost-limited safe tune): pressure holds
    fp_des = np.full(n, 580.0)
    fp = np.full(n, 580.0); fp[wot] = 578.0; fp = fp + nz(2.0)

    # injector duty target -> per-cylinder pulse width (ms);  duty% = pw*rpm/1200
    duty = 9.0 + load * (rpm / 6300.0) * 71.0          # ~80% peak
    duty = np.clip(duty + nz(0.4), 4, 95)
    pw = duty * 1200.0 / np.clip(rpm, 300, None)        # ms
    inj = {i: pw * (1 + (i - 4) * 0.004) + nz(0.02) for i in range(1, 9)}

    egt = 420.0 + np.where(t < launch_t, 0.0, 360.0 * pull)
    egt = np.where(coast, 420.0 + 360.0 * np.exp(-(t - lift_t) / 20.0), egt) + nz(4)

    ect = 88.0 + 0.16 * np.clip(t - launch_t, 0, None) + nz(0.2)
    oilt = 96.0 + 0.22 * np.clip(t - launch_t, 0, None) + nz(0.3)
    oilp = 280.0 + (rpm / 6300.0) * 220.0 + nz(4)
    ltr = 41.0 + 0.10 * np.clip(t - launch_t, 0, None) + nz(0.2)
    ltr_pump = 1500.0 + load * 2700.0 + nz(40)
    iat = 38.0 + 0.6 * np.clip(t - launch_t, 0, None) + boost_psi.clip(0) * 0.3 + nz(0.4)
    ambient = 29.0 + nz(0.08)   # outside air temp (steady) -> density altitude

    airflow = 6.0 + (rpm / 6300.0) * (map_kpa / BOOST_TARGET_KPA) * 540.0 * load + nz(3)
    cyl_air = airflow * 1.4 + nz(2)
    sc_bypass = np.clip(100.0 * (1.0 - load) + np.where(wot, 4.0, 0.0), 0, 100) + nz(0.5)

    tq_demand = load * 900.0 + nz(3)
    tq_actual = np.where(wot, 880.0 * (map_kpa / BOOST_TARGET_KPA), load * 850.0) + nz(6)
    tq_expected = tq_actual + np.where(boost_psi > 6, 25.0, 0.0)   # limiter holds actual below expected
    cmv = 14.0 + nz(0.05)

    cols = {
        "Offset": t, "Engine RPM": rpm, "Vehicle Speed": speed,
        "Trans Current Gear": gear, "Shift ID": shiftid,
        "Barometric Pressure": baro, "Manifold Absolute Pressure": map_kpa,
        "Throttle Position (SAE)": tps, "Ambient Air Temp": ambient, "Aircharge Temperature": iat,
        "Engine Coolant Temp": ect, "Engine Oil Temp": oilt, "Engine Oil Pressure": oilp,
        "LTR Coolant Temp": ltr, "LTR Pump Speed": ltr_pump,
        "Total Airflow": airflow.clip(0), "Cylinder Airmass": cyl_air.clip(0),
        "Supercharger Bypass Pos 1": sc_bypass,
        "Actual Spark": actual_spark, "MBT Advance": mbt,
        "Total Knock Retard": knock, "Knock Sensor 1": ks1, "Knock Sensor 2": ks2,
        "Equivalence Ratio Commanded": eq_cmd, "WB EQ Ratio 1 (SAE) (2)": eq_meas, "WB EQ Ratio 2": eq_meas2,
        "Desired Fuel Pressure": fp_des, "Fuel Pressure (SAE)": fp,
        "Exhaust Gas Temperature": egt,
        "Actual Torque": tq_actual, "Expected Torque": tq_expected, "Driver Demand Torque": tq_demand,
        "Control Module Voltage (SAE)": cmv,
    }
    for i in range(1, 9):
        cols[f"Injector Pulse Width Cyl {i}"] = inj[i].clip(0)
        cols[f"Misfire Current Cylinder #{i}"] = np.zeros(n)
    return t, cols


def _fmt(name, v):
    if name == "Offset":
        return f"{v:.3f}"
    if name in ("Engine RPM", "LTR Pump Speed", "Exhaust Gas Temperature"):
        return f"{v:.0f}"
    if name in ("Trans Current Gear", "Shift ID") or name.startswith("Misfire"):
        return f"{int(round(v))}"
    if name in ("Total Knock Retard", "Knock Sensor 1", "Knock Sensor 2"):
        return f"{v:.2f}"
    if name.startswith("Injector Pulse Width"):
        return f"{v:.3f}"
    if name in ("Equivalence Ratio Commanded", "WB EQ Ratio 1 (SAE) (2)", "WB EQ Ratio 2", "Control Module Voltage (SAE)"):
        return f"{v:.3f}"
    if name in ("Engine Oil Pressure", "Desired Fuel Pressure", "Fuel Pressure (SAE)",
                "Manifold Absolute Pressure", "Barometric Pressure", "Total Airflow",
                "Cylinder Airmass", "Actual Torque", "Expected Torque", "Driver Demand Torque"):
        return f"{v:.0f}"
    return f"{v:.1f}"


def write_csv(out: pathlib.Path, created: dt.datetime, seed: int = 7) -> int:
    _, cols = build(seed)
    names = [c[0] for c in COLUMNS]; units = [c[1] for c in COLUMNS]
    n = len(cols["Offset"])
    lines = [
        "VCM Scanner 4.8.20 (SYNTHETIC DEMO LOG -- not a real capture)",
        "Vehicle: 2020 Dodge Challenger SRT Hellcat Redeye",
        f"Created: {created.strftime('%-m/%-d/%Y %-I:%M:%S %p')}",
        f"Log Duration: {cols['Offset'][-1]:.2f} s",
        "",
        ",".join(names), ",".join(units),
    ]
    for i in range(n):
        lines.append(",".join(_fmt(nm, float(cols[nm][i])) for nm in names))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write a synthetic VCM Scanner CSV.")
    ap.add_argument("--out", default=str(ROOT / "samples" / "synthetic_demo.csv"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--created", default="2026-06-20 19:42:11", help="wallclock anchor 'YYYY-MM-DD HH:MM:SS'")
    a = ap.parse_args()
    created = dt.datetime.strptime(a.created, "%Y-%m-%d %H:%M:%S")
    rows = write_csv(pathlib.Path(a.out), created, a.seed)
    print(f"wrote {rows} rows, {len(COLUMNS)} channels -> {a.out}")
