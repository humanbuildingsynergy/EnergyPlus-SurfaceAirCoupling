"""How far the single room's air leaves its setpoint band when the surfaces and air are solved to
agreement but the HVAC is held at its first result (both_faces), against the converged
configuration, which repeats the HVAC in each pass.

The room is single_room.py's "ideal" case: an ideal air system holding 21 to 24 C from 08:00 to
18:00 and 15 to 30 C otherwise. The excursion at an hour end is the distance of the zone air
temperature below the heating setpoint or above the cooling setpoint of the hour that ends there.
Reads results/single_room/<configuration>/hour_end_temperatures.csv.gz (tests/single_room.py).
Writes results/single_room/hvac_held_fixed.csv: per configuration, scheme and design day (CLG
summer, HTG winter), the largest excursion at 4 and at 30 timesteps per hour [C].
Usage (repository root): python3 tests/hvac_held_fixed.py [configuration ...]
  (default: both_faces converged)
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ROOM = REPO / "results" / "single_room"


def day(env):
    return "CLG" if "CLG" in env else "HTG"


def band(hour):
    """Heating and cooling setpoints in effect during the hour that ends at `hour` (1..24)."""
    occupied = (hour > 8) & (hour <= 18)
    return np.where(occupied, 21.0, 15.0), np.where(occupied, 24.0, 30.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("configurations", nargs="*", default=["both_faces", "converged"])
    ap.add_argument("--results", default=str(ROOM), help="folder for hvac_held_fixed.csv")
    a = ap.parse_args()
    rows = []
    for conf in a.configurations:
        t = pd.read_csv(ROOM / conf / "hour_end_temperatures.csv.gz")
        t = t[(t.case == "ideal") & t["var"].str.startswith("Zone Mean")].copy()
        t["day"] = t.env.map(day)
        hsp, csp = band(t.hour.to_numpy())
        t["excursion"] = np.maximum(hsp - t.value, 0) + np.maximum(t.value - csp, 0)
        for (algo, d), g in t.groupby(["algo", "day"]):
            rows.append({
                "configuration": conf, "algo": algo, "day": d,
                "max_excursion_ts04_C": float(g[g.ts == 4].excursion.max()),
                "max_excursion_ts30_C": float(g[g.ts == 30].excursion.max()),
            })
    df = pd.DataFrame(rows)
    out = Path(a.results)
    out.mkdir(parents=True, exist_ok=True)
    df.to_csv(out / "hvac_held_fixed.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 200)
    print(df.pivot_table(index=["day", "algo"], columns="configuration", values="max_excursion_ts04_C")
          [a.configurations].to_string(float_format=lambda x: f"{x:.3g}"))


if __name__ == "__main__":
    main()
