"""The update of each zone air scheme in the room with an exact solution, computed outside
EnergyPlus with the surfaces lagged (as in the release) and in agreement with the air (the state
the passes converge to), to check that the converged program's error belongs to the scheme.

The room has massless layers, so each inside face is algebraic in the air and outdoor
temperatures: Ts_i = a_i Tz + b_i To with a_i = h_i / (h_i + U'_i), b_i = 1 - a_i (U'_i from the
face to outdoor air, 0 for the adiabatic floor). The zone air update of each scheme
(ZoneTempPredictorCorrector.cc, correctAirTemp), with A = sum h_i A_i, B = sum h_i A_i Ts_i and
C = rho cp V / dt:
  third-order  Tz = (B + C (3 T1 - 1.5 T2 + T3 / 3)) / (11/6 C + A)
  Euler        Tz = (C T1 + B) / (C + A)
  analytical   Tz = (T1 - B / A) exp(-A / C) + B / A
is applied at each zone timestep in two ways: lagged (B from the faces solved with the previous
step's air temperature T1) and converged (B from the faces at the new Tz; solved exactly, as B is
linear in Tz). Unlike EnergyPlus, the update never subdivides the HVAC timestep. To(t) and Pb(t) are
exact_room.py's forcing; rho uses Pb, T1 and the converged configuration's mean humidity ratio
(from its 60/h run in <runs>/exact_room/converged_ts60).
Reads results/exact_room/surface_constants.csv, exact_solution.csv.gz and schemes.csv. Writes
results/exact_room/scheme_updates.csv: per scheme and timestep, the RMS error at the zone timestep
ends from day 3 of the lagged and the converged update, and of EnergyPlus's release and converged
configuration for comparison [C].
Usage (repository root): python3 tests/exact_room_updates.py [--runs runs]
"""
import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

import exact_room as exact

SCHEMES = ["ThirdOrderBackwardDifference", "EulerMethod", "AnalyticalSolution"]


def simulate(scheme, ts, coupled, a_i, hA, vol, w, To, Pb, T0):
    dt = 3600.0 / ts
    step = 60 // ts
    A = hA.sum()
    alpha = float((hA * a_i).sum())          # dB/dTz
    beta = float((hA * (1 - a_i)).sum())     # dB/dTo
    n = 525600 // step
    T = np.empty(n + 1)
    T[0] = T0
    hist = [T0, T0, T0]
    cp = 1.00484e3 + 1.85895e3 * w
    for k in range(1, n + 1):
        m = k * step
        to = To(m)
        T1 = hist[0]
        C = Pb(m) / (287.0 * (T1 + 273.15) * (1 + 1.6077687 * w)) * cp * vol / dt
        if not coupled:
            B = alpha * T1 + beta * to
            if scheme == "ThirdOrderBackwardDifference":
                z = (B + C * (3 * hist[0] - 1.5 * hist[1] + hist[2] / 3)) / (11 / 6 * C + A)
            elif scheme == "EulerMethod":
                z = (C * T1 + B) / (C + A)
            else:
                z = (T1 - B / A) * np.exp(-A / C) + B / A
        else:  # B = alpha z + beta to, solve the linear equation in z
            if scheme == "ThirdOrderBackwardDifference":
                z = (beta * to + C * (3 * hist[0] - 1.5 * hist[1] + hist[2] / 3)) / (11 / 6 * C + A - alpha)
            elif scheme == "EulerMethod":
                z = (C * T1 + beta * to) / (C + A - alpha)
            else:
                e = np.exp(-A / C)
                z = (T1 * e + (1 - e) * beta * to / A) / (1 - (1 - e) * alpha / A)
        T[k] = z
        hist = [z, hist[0], hist[1]]
    return T, step


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default=str(exact.REPO / "runs"),
                    help="folder of raw runs holding exact_room/converged_ts60")
    ap.add_argument("--results", default=str(exact.RESULTS), help="folder for scheme_updates.csv")
    a = ap.parse_args()
    c = pd.read_csv(exact.RESULTS / "surface_constants.csv")
    up = np.where(c.boundary.str.lower() == "outdoors", 1.0 / (c.R + 1.0 / exact.HO), 0.0)
    a_i = (exact.HI / (exact.HI + up))
    hA = exact.HI * c.area_m2.to_numpy()
    floor = c[c.type.str.lower() == "floor"].area_m2.sum()
    zmax = max(float(z) for z in re.findall(r"[-\d.]+,[-\d.]+,([-\d.]+);?\s*!- X,Y,Z", exact.make_idf(4)))
    vol = floor * zmax
    tdb, pb = exact.epw()
    To, Pb = exact.forcing(tdb), exact.forcing(pb)
    w = exact.series(Path(a.runs) / "exact_room" / "converged_ts60", "Zone Air Humidity Ratio").Value.mean()
    ref = pd.read_csv(exact.RESULTS / "exact_solution.csv.gz").T_ref_C.to_numpy()
    ep = pd.read_csv(exact.RESULTS / "schemes.csv").set_index(["scheme", "configuration", "ts"])
    rows = []
    for s in SCHEMES:
        for ts in (4, 6, 10, 20):
            out = {"scheme": s, "ts": ts}
            for coupled, name in ((False, "lagged"), (True, "converged")):
                T, step = simulate(s, ts, coupled, a_i, hA, vol, w, To, Pb, ref[0])
                m = np.arange(len(T)) * step
                k = m >= exact.START
                out[f"model_{name}_rms_C"] = float(np.sqrt(np.mean((T[k] - ref[m[k]]) ** 2)))
            out["eplus_release_rms_C"] = ep.loc[(s, "release", ts), "rms_C"]
            out["eplus_converged_rms_C"] = ep.loc[(s, "converged", ts), "rms_C"]
            rows.append(out)
    df = pd.DataFrame(rows)
    Path(a.results).mkdir(parents=True, exist_ok=True)
    df.to_csv(Path(a.results) / "scheme_updates.csv", index=False, float_format="%.5g")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
