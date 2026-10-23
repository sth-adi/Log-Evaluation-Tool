"""Synthetic hybrid Formula Student log generator.

Produces two CSV files that mimic what a combustion ECU and a hybrid control
unit (HCU) might log during a practice session, so the importer, downsampler
and (later) alignment tools can be developed and tested before real logs exist.

IMPORTANT: channel names, units and layouts here are INVENTED. They are not the
Life Racing F88R export format. Replace/extend the importer mapping profile once
a real log is available.

The two files deliberately differ in the ways real logs do:
  * different sample rates (ECU 100 Hz, HCU 50 Hz)
  * different time columns (ECU: seconds, HCU: milliseconds)
  * a clock offset between the two (HCU starts logging 2.35 s later)
  * a short ECU data dropout (frames missing, not zero-filled)

Usage:
    python tools/generate_logs.py --out samples/synthetic --laps 5 --seed 7
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ECU_HZ = 100
HCU_HZ = 50
HCU_CLOCK_OFFSET_S = 2.35  # HCU log starts this long after the ECU log
LAP_S = 46.0

# HCU state codes (invented)
STATE_NAMES = {
    0: "OFF",
    1: "PRECHARGE",
    2: "READY",
    3: "CRUISE",
    4: "ASSIST",
    5: "REGEN",
    6: "CHARGE",
    7: "LIMP",
}

GEAR_RATIOS = {1: 780.0, 2: 560.0, 3: 450.0, 4: 370.0, 5: 320.0}  # engine rpm per (m/s), invented
UPSHIFT_RPM = 11500
DOWNSHIFT_RPM = 6500


def _speed_profile(t: np.ndarray) -> np.ndarray:
    """A repeatable lap-like speed trace (m/s) built from straights and corners."""
    phase = (t % LAP_S) / LAP_S * 2 * np.pi
    v = (
        19.0
        + 9.0 * np.sin(phase * 2 + 0.4)
        + 5.0 * np.sin(phase * 5 + 1.1)
        + 2.5 * np.sin(phase * 9)
    )
    return np.clip(v, 8.0, 34.0)


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    k = np.ones(n) / n
    return np.convolve(x, k, mode="same")


def simulate(laps: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    duration = laps * LAP_S + 6.0  # a few seconds of warm-up/idle at the start
    dt = 1.0 / ECU_HZ
    t = np.arange(0, duration, dt)
    n = t.size

    # --- vehicle motion -----------------------------------------------------
    warmup = t < 4.0
    speed = np.where(warmup, 0.0, _speed_profile(t - 4.0))
    speed = _smooth(speed, 15)
    accel = np.gradient(speed, dt)  # m/s^2

    throttle = np.clip(35 + accel * 14 + rng.normal(0, 1.2, n), 0, 100)
    throttle = np.where(warmup, 0.0, throttle)
    braking = np.clip(-accel * 9, 0, 100)
    throttle = np.where(braking > 8, 0.0, throttle)

    # --- gearbox (simple hysteresis shifter) --------------------------------
    gear = np.zeros(n, dtype=int)
    rpm = np.zeros(n)
    g = 1
    for i in range(n):
        if warmup[i]:
            gear[i] = 0
            rpm[i] = 1400 + rng.normal(0, 25)
            continue
        r = speed[i] * GEAR_RATIOS[g]
        if r > UPSHIFT_RPM and g < 5:
            g += 1
        elif r < DOWNSHIFT_RPM and g > 1:
            g -= 1
        gear[i] = g
        rpm[i] = max(1500.0, speed[i] * GEAR_RATIOS[g] + rng.normal(0, 40))

    # --- ECU channels -------------------------------------------------------
    map_kpa = 30 + throttle * 0.72 + rng.normal(0, 0.8, n)
    lam = 1.0 - 0.12 * (throttle > 85) + rng.normal(0, 0.008, n)
    coolant = 62 + 24 * (1 - np.exp(-t / 120)) + rng.normal(0, 0.15, n)
    vbat = 13.6 - 0.35 * (rpm < 2000) + rng.normal(0, 0.03, n)

    ecu = pd.DataFrame(
        {
            "Time": np.round(t, 3),  # seconds
            "RPM": np.round(rpm, 0),
            "TPS": np.round(throttle, 1),
            "MAP": np.round(map_kpa, 1),
            "Lambda": np.round(lam, 3),
            "ECT": np.round(coolant, 1),
            "Gear": gear,
            "VehicleSpeed": np.round(speed * 3.6, 1),  # km/h
            "BattVolts": np.round(vbat, 2),
        }
    )

    # ECU data dropout: ~0.6 s of missing rows about 45% through the log (rows removed, not zeroed)
    drop_start = int(0.45 * n)
    ecu = ecu.drop(index=range(drop_start, drop_start + int(0.6 / dt))).reset_index(drop=True)

    # --- HCU channels (50 Hz, own clock) ------------------------------------
    hcu_t = np.arange(0, duration - HCU_CLOCK_OFFSET_S, 1.0 / HCU_HZ)  # HCU-local time
    ecu_idx = np.clip(((hcu_t + HCU_CLOCK_OFFSET_S) / dt).astype(int), 0, n - 1)
    h_thr = throttle[ecu_idx]
    h_brk = braking[ecu_idx]
    h_spd = speed[ecu_idx]
    m = hcu_t.size
    hdt = 1.0 / HCU_HZ

    torque_req = np.clip(h_thr * 1.1, 0, 110)  # Nm at the ICE shaft
    soc = np.zeros(m)
    soc[0] = 78.0
    state = np.zeros(m, dtype=int)
    motor_tq = np.zeros(m)
    pack_v = np.zeros(m)
    pack_i = np.zeros(m)
    motor_temp = np.zeros(m)
    inv_temp = np.zeros(m)
    motor_temp[0] = 38.0
    inv_temp[0] = 34.0
    fault = np.zeros(m, dtype=int)
    motor_rpm = np.zeros(m)

    fault_t0 = 0.7 * duration  # one injected derate event about 70% through the log
    fault_t1 = fault_t0 + 2.0

    for k in range(m):
        tt = hcu_t[k]
        if tt < 0.5:
            s = 0
        elif tt < 1.5:
            s = 1
        elif tt + HCU_CLOCK_OFFSET_S < 4.0:  # car still stationary in the pits
            s = 2
        elif h_brk[k] > 12:
            s = 5
        elif h_thr[k] > 78 and soc[max(k - 1, 0)] > 25:
            s = 4
        elif h_thr[k] < 30 and soc[max(k - 1, 0)] < 70:
            s = 6
        else:
            s = 3

        if fault_t0 <= tt < fault_t1:
            s = 7
            fault[k] = 0x12  # invented code: motor over-temperature derate

        tq = {4: 24.0, 5: -16.0, 6: -5.0, 7: 0.0}.get(s, 0.0)
        if s == 4:  # assist fades with speed
            tq *= np.clip(1.25 - h_spd[k] / 40.0, 0.2, 1.0)
        motor_tq[k] = tq + rng.normal(0, 0.15)
        state[k] = s

        m_rpm = h_spd[k] * 52.0  # invented motor-to-wheel ratio
        motor_rpm[k] = m_rpm
        mech_kw = motor_tq[k] * m_rpm * 2 * np.pi / 60 / 1000.0
        elec_kw = mech_kw / 0.92 if mech_kw > 0 else mech_kw * 0.90

        v_open = 40.0 + 8.0 * (soc[max(k - 1, 0)] / 100.0)
        i = 0.0
        if s in (4, 5, 6):
            i = elec_kw * 1000.0 / max(v_open, 30.0)
        pack_i[k] = i + rng.normal(0, 0.4)
        pack_v[k] = v_open - 0.018 * pack_i[k] + rng.normal(0, 0.05)

        if k > 0:
            # small pack (3 Ah) so SOC visibly swings over a lap
            soc[k] = np.clip(soc[k - 1] - pack_i[k] * hdt / (3600.0 * 3.0) * 100.0, 0, 100)
            heat = abs(motor_tq[k]) * 0.012 + (abs(pack_i[k]) ** 2) * 0.00003
            motor_temp[k] = motor_temp[k - 1] + heat * hdt - (motor_temp[k - 1] - 35) * 0.004 * hdt
            inv_temp[k] = inv_temp[k - 1] + (abs(pack_i[k]) * 0.006) * hdt - (inv_temp[k - 1] - 32) * 0.006 * hdt

    hcu = pd.DataFrame(
        {
            "Timestamp_ms": np.round(hcu_t * 1000.0).astype(int),
            "HCU_State": state,
            "Torque_Req_Nm": np.round(torque_req, 1),
            "Motor_Torque_Nm": np.round(motor_tq, 2),
            "Motor_Speed_rpm": np.round(motor_rpm, 0),
            "Pack_Voltage_V": np.round(pack_v, 2),
            "Pack_Current_A": np.round(pack_i, 2),
            "SOC_pct": np.round(soc, 2),
            "Motor_Temp_C": np.round(motor_temp + rng.normal(0, 0.1, m), 1),
            "Inverter_Temp_C": np.round(inv_temp + rng.normal(0, 0.1, m), 1),
            "Fault_Code": fault,
        }
    )
    return ecu, hcu


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=Path("samples/synthetic"))
    ap.add_argument("--laps", type=int, default=5)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    ecu, hcu = simulate(args.laps, args.seed)
    ecu_path = args.out / "synthetic_ecu.csv"
    hcu_path = args.out / "synthetic_hcu.csv"
    ecu.to_csv(ecu_path, index=False)
    hcu.to_csv(hcu_path, index=False)

    print(f"ECU: {len(ecu):>7} rows @ ~{ECU_HZ} Hz -> {ecu_path}")
    print(f"HCU: {len(hcu):>7} rows @ ~{HCU_HZ} Hz -> {hcu_path}")
    print(f"HCU clock offset vs ECU: {HCU_CLOCK_OFFSET_S} s (HCU logs later)")
    print("HCU state codes:", ", ".join(f"{k}={v}" for k, v in STATE_NAMES.items()))


if __name__ == "__main__":
    main()
