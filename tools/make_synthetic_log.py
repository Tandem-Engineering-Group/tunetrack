"""Generate a realistic *synthetic* VCM Scanner CSV for end-to-end demo runs.

This stands in for a real HP Tuners export until one is provided. The pass is
deterministic (seeded) and deliberately contains: a clean idle/stage, a WOT
pull with gear shifts, a knock event in one RPM/boost cell, a top-end lean
excursion, injector duty climbing toward its limit, a fuel-pressure droop, and
launch wheel slip -- so every downstream scorecard / analysis has something
real-shaped to chew on.

ASSUMPTIONS baked in (to be confirmed against a real export, then deleted):
  * A short metadata preamble, then a `Created: <wallclock>` line.
  * One channel-name header row, then a units row, then data rows.
  * First column is elapsed-seconds `Offset`.
Channel names match the canonical variants in channels.yaml.

NOTHING here touches the vehicle or a calibration. It only writes a CSV file.
"""
from __future__ import annotations
import argparse
import pathlib
import datetime as dt
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]

# (name, unit) in column order. Names map via channels.yaml.
COLUMNS = [
    ("Offset", "s"),
    ("Engine RPM", "RPM"),
    ("Vehicle Speed", "MPH"),
    ("Engine Coolant Temp", "deg C"),
    ("Engine Oil Temp", "deg C"),
    ("Engine Oil Pressure", "kPa"),
    ("LTR Coolant Temp", "deg C"),
    ("Aircharge Temperature", "deg C"),
    ("Manifold Absolute Pressure", "kPa"),
    ("Throttle Position (SAE)", "%"),
    ("Total Knock Retard", "deg"),
    ("Equivalence Ratio Commanded", ""),
    ("WB EQ Ratio 1 (SAE) (2)", ""),
    ("Injector Duty", "%"),
    ("Exhaust Gas Temperature", "deg C"),
    ("Fuel Rail Pressure", "kPa"),
    ("Wheel Speed RL", "MPH"),
    ("Wheel Speed RR", "MPH"),
    ("Wheel Speed FL", "MPH"),
    ("Wheel Speed FR", "MPH"),
]


def build(seed: int = 7):
    rng = np.random.default_rng(seed)
    dt_s = 0.04
    t = np.arange(0.0, 20.0 + dt_s / 2, dt_s)
    n = len(t)

    def nz(scale):
        return rng.normal(0.0, scale, n)

    launch_t, lift_t = 3.0, 15.0
    stage = (t >= 2.4) & (t < launch_t)
    wot = (t >= launch_t) & (t < lift_t)
    coast = t >= lift_t
    lean = (t >= 12.5) & (t < lift_t)  # top-end lean / fuel-limited zone

    # Throttle
    tps = np.zeros(n)
    tps[stage] = 35.0
    tps[wot] = 100.0
    tps = np.clip(tps + nz(0.3), 0, 100)

    # Vehicle speed (non-driven ~ front wheels)
    pull = np.clip((t - launch_t) / (lift_t - launch_t), 0, 1)
    speed = np.where(t < launch_t, 0.0, 135.0 * np.sqrt(pull))
    speed = np.where(coast, 135.0 * np.exp(-(t - lift_t) / 8.0), speed)
    speed = np.clip(speed + nz(0.2), 0, None)
    front = speed.copy()

    # Rear wheel slip: launch spin decaying, small residual under power
    slip = np.zeros(n)
    spin = (t >= launch_t) & (t < launch_t + 2.0)
    slip[spin] = 0.13 * np.exp(-(t[spin] - launch_t) / 0.8)
    slip[wot] += 0.015
    rear = front * (1.0 + slip)

    # RPM: idle -> brake-torque stage -> sawtooth across gears -> decay on lift
    rpm = np.full(n, 820.0)
    rpm[stage] = 1850.0
    shift_t = [launch_t, 4.6, 6.6, 9.2, 12.4]
    gear_lo = [3800, 4300, 4500, 4700, 4900]
    rw = np.zeros(n)
    for i, ts in enumerate(shift_t):
        te = shift_t[i + 1] if i + 1 < len(shift_t) else lift_t
        seg = (t >= ts) & (t < te)
        rw[seg] = gear_lo[i] + (t[seg] - ts) / max(te - ts, 1e-6) * (6300 - gear_lo[i])
    rpm = np.where(wot, rw, rpm)
    rpm = np.where(coast, np.maximum(820.0, 6300.0 * np.exp(-(t - lift_t) / 1.5)), rpm)
    rpm = rpm + nz(15)

    # Manifold pressure / boost
    map_kpa = np.full(n, 40.0)
    map_kpa[stage] = 120.0
    map_kpa = np.where(wot, 198.0 - 60.0 * np.exp(-(t - launch_t) / 0.5), map_kpa)
    map_kpa = np.where(coast, 35.0, map_kpa)
    map_kpa = np.clip(map_kpa + nz(1.2), 20, 260)
    boost_psi = np.clip((map_kpa - 101.3) / 6.895, -2, None)

    # Knock retard: a flaggable event mid-pull + a tiny second blip
    knock = np.zeros(n)
    k1 = (t >= 5.4) & (t < 6.4)
    knock[k1] = 1.3 * np.exp(-((t[k1] - 5.9) / 0.25) ** 2)
    k2 = (t >= 9.4) & (t < 9.9)
    knock[k2] = 0.6 * np.exp(-((t[k2] - 9.6) / 0.15) ** 2)
    knock = np.clip(knock + np.where(wot, np.abs(nz(0.03)), 0.0), 0, None)

    # Commanded vs measured EQ (rich under boost; lean drift at top end)
    eq_cmd = np.where(boost_psi > 3, 1.28, 1.00) + nz(0.003)
    eq_meas = eq_cmd.copy()
    eq_meas[lean] -= np.linspace(0, 0.075, int(lean.sum()))
    eq_meas = eq_meas + nz(0.004)

    # Injector duty: rises with rpm*load, pushed toward limit at top end
    duty = 9.0 + (rpm / 6300.0) * (boost_psi.clip(0) / 14.0) * 82.0
    duty = np.where(wot, duty, 9.0 + nz(0.5))
    duty[lean] += 6.0
    duty = np.clip(duty + nz(0.4), 5, 99)

    # Fuel rail pressure: base, drooping at top-end demand (pump signing off)
    fp = np.full(n, 585.0)
    fp[wot] = 580.0
    fp[lean] -= np.linspace(0, 48, int(lean.sum()))
    fp = fp + nz(2.0)

    # EGT, temps, oil pressure
    egt = 420.0 + np.where(t < launch_t, 0.0, 380.0 * pull)
    egt = np.where(coast, 420.0 + 380.0 * np.exp(-(t - lift_t) / 20.0), egt) + nz(4)
    ect = 88.0 + 0.18 * np.clip(t - launch_t, 0, None) + nz(0.2)
    oilt = 96.0 + 0.25 * np.clip(t - launch_t, 0, None) + nz(0.3)
    oilp = 280.0 + (rpm / 6300.0) * 220.0 + nz(4)
    ltr = 41.0 + 0.12 * np.clip(t - launch_t, 0, None) + nz(0.2)
    iat = 38.0 + 0.7 * np.clip(t - launch_t, 0, None) + boost_psi.clip(0) * 0.3 + nz(0.4)

    cols = {
        "Offset": t,
        "Engine RPM": rpm,
        "Vehicle Speed": speed,
        "Engine Coolant Temp": ect,
        "Engine Oil Temp": oilt,
        "Engine Oil Pressure": oilp,
        "LTR Coolant Temp": ltr,
        "Aircharge Temperature": iat,
        "Manifold Absolute Pressure": map_kpa,
        "Throttle Position (SAE)": tps,
        "Total Knock Retard": knock,
        "Equivalence Ratio Commanded": eq_cmd,
        "WB EQ Ratio 1 (SAE) (2)": eq_meas,
        "Injector Duty": duty,
        "Exhaust Gas Temperature": egt,
        "Fuel Rail Pressure": fp,
        "Wheel Speed RL": rear + nz(0.15),
        "Wheel Speed RR": rear + nz(0.15),
        "Wheel Speed FL": front + nz(0.1),
        "Wheel Speed FR": front + nz(0.1),
    }
    return t, cols


def _fmt(name: str, v: float) -> str:
    if name == "Offset":
        return f"{v:.3f}"
    if name == "Engine RPM":
        return f"{v:.0f}"
    if name in ("Total Knock Retard",):
        return f"{v:.2f}"
    if name in ("Equivalence Ratio Commanded", "WB EQ Ratio 1 (SAE) (2)"):
        return f"{v:.3f}"
    if name in ("Engine Oil Pressure", "Fuel Rail Pressure", "Exhaust Gas Temperature"):
        return f"{v:.0f}"
    return f"{v:.1f}"


def write_csv(out: pathlib.Path, created: dt.datetime, seed: int = 7) -> int:
    _, cols = build(seed)
    names = [c[0] for c in COLUMNS]
    units = [c[1] for c in COLUMNS]
    n = len(cols["Offset"])
    lines = [
        "VCM Scanner 4.8.20 (SYNTHETIC DEMO LOG -- not a real capture)",
        "Vehicle: 2020 Dodge Challenger SRT Hellcat Redeye",
        f"Created: {created.strftime('%-m/%-d/%Y %-I:%M:%S %p')}",
        f"Log Duration: {cols['Offset'][-1]:.2f} s",
        "",
        ",".join(names),
        ",".join(units),
    ]
    for i in range(n):
        lines.append(",".join(_fmt(name, float(cols[name][i])) for name in names))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Write a synthetic VCM Scanner CSV.")
    ap.add_argument("--out", default=str(ROOT / "samples" / "synthetic_demo.csv"))
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--created", default="2026-06-20 19:42:11",
                    help="wallclock anchor, 'YYYY-MM-DD HH:MM:SS'")
    a = ap.parse_args()
    created = dt.datetime.strptime(a.created, "%Y-%m-%d %H:%M:%S")
    rows = write_csv(pathlib.Path(a.out), created, a.seed)
    print(f"wrote {rows} rows -> {a.out}")
