"""Heat capacity that the one-step lag adds to the air of the room with an exact solution.

With massless surfaces, each inside surface temperature is a function of the air temperature,
Ts = S(Tz). The lagged surfaces read Tz from the previous step, Tz - dt dTz/dt to first order, so
the convection term loses sum_i h_i A_i S'_i dt dTz/dt. Moved to the left side, this is an extra
heat capacity sum_i h_i A_i S'_i dt on the air node.

Room as in exact_room.py: 1ZoneUncontrolled geometry, inside convection fixed at 3 W/(m2 K), outside
at 20 W/(m2 K), walls R13LAYER and roof R31LAYER (Material:NoMass), floor massless and adiabatic,
no long-wave exchange. The air capacity uses the mean pressure of the Denver weather file and the
mean air temperature of the exact solution, with dry air (humidity changes it by under 0.1%).
Reads the weather file and results/exact_room/exact_solution.csv.gz. Writes
results/exact_room/lag_heat_capacity.csv: per timestep, the heat capacity of the air and the one
the lag adds [MJ/K], their ratio, and the time constant of the room with and without it [h].
Usage (repository root): python3 tests/lag_heat_capacity.py
"""
import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "exact_room"
H_IN, H_OUT = 3.0, 20.0                     # W/(m2 K), fixed in exact_room.py
L, H = 15.24, 4.572                         # m, plan side and height of the zone
R_WALL, R_ROOF = 2.290965, 5.456            # m2 K/W, from the input file
EPW = ROOT / "weather/USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw"
REF = OUT / "exact_solution.csv.gz"         # exact solution, exact_room.py


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--results", default=str(OUT), help="folder for lag_heat_capacity.csv")
    a = ap.parse_args()
    p = pd.read_csv(EPW, skiprows=8, header=None)[9].mean()     # Pa, mean station pressure
    t_mean = pd.read_csv(REF)["T_ref_C"].mean()                 # C, mean zone air temperature
    rho = p / (287.0 * (t_mean + 273.15))       # dry air, kg/m3, as Psychrometrics.hh with w = 0
    c_air = rho * L * L * H * 1004.84           # J/K

    # Slope of each inside surface temperature with respect to the air temperature
    surfaces = []
    for name, area, r in [("walls", 4 * L * H, R_WALL), ("roof", L * L, R_ROOF)]:
        u = 1.0 / (1.0 / H_OUT + r + 1.0 / H_IN)
        surfaces.append((name, area, 1.0 - u / H_IN, u))
    surfaces.append(("floor (adiabatic)", L * L, 1.0, 0.0))   # its face follows the air exactly
    hAs = sum(H_IN * a * s for _, a, s, _ in surfaces)        # W/K
    ua = sum(a * u for _, a, _, u in surfaces)                # W/K, to the outdoors

    rows = []
    for n in [1, 2, 4, 6, 10, 20, 30, 60]:
        dt = 3600.0 / n
        extra = hAs * dt
        rows.append({"timesteps_per_hour": n, "air_capacity_MJ_per_K": c_air / 1e6,
                     "added_capacity_MJ_per_K": extra / 1e6, "ratio_added_to_air": extra / c_air,
                     "time_constant_true_h": c_air / ua / 3600,
                     "time_constant_lagged_h": (c_air + extra) / ua / 3600})
    out = Path(a.results)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(out / "lag_heat_capacity.csv", index=False, float_format="%.4g")
    print(f"sum h A dTs/dTz = {hAs:.1f} W/K, UA = {ua:.1f} W/K, air {c_air / 1e6:.3f} MJ/K")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
