"""Measured order of accuracy of the single room and its error at four timesteps per hour, per
configuration, against the run with 30 timesteps per hour of the same configuration and scheme.

Reads results/single_room/<configuration>/hour_end_temperatures.csv.gz (tests/single_room.py).
Writes, in results/single_room/:
  observed_order_ref30.csv  measured order (slope of log RMS error against log timestep length,
                            fitted from 2 to 10 timesteps per hour) per case, design day (CLG
                            summer, HTG winter), scheme and variable (air: zone air; surface: the
                            median over the six inside faces), one column per configuration
  rms_error_ts04_ref30.csv  RMS error of the zone air temperature at 4 per hour [C]
Usage (repository root): python3 tests/single_room_orders.py [configuration ...]
  (default: release converged)
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
ROOM = REPO / "results" / "single_room"
# When most errors of a fit are below this, they are round-off and their slope is not an order, so
# the order is left blank (the converged configuration on the winter design day of two cases).
ROUND_OFF = 1e-9  # C


def day(env):
    return "CLG" if "CLG" in env else "HTG"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("configurations", nargs="*", default=["release", "converged"])
    ap.add_argument("--results", default=str(ROOM), help="folder for the two tables")
    a = ap.parse_args()
    labels = a.configurations
    out = Path(a.results)
    out.mkdir(parents=True, exist_ok=True)

    # Same-grid reference. EnergyPlus derives the conduction transfer functions from a grid with
    # node spacing sqrt(2 alpha dt) and 6 to 19 nodes per layer. For the room's 4 in concrete floor
    # that is 6 nodes up to 30/h and 9 nodes at 60/h, so errors against the 60/h run would include
    # a fixed spatial offset. The 30/h run shares the 6-node grid with every coarser timestep.
    h = []
    for label in labels:
        d = pd.read_csv(ROOM / label / "hour_end_temperatures.csv.gz").assign(configuration=label)
        h.append(d[d.ts.isin([2, 3, 4, 5, 6, 10, 30])])
    h = pd.concat(h)
    h["day"] = h.env.map(day)
    h["what"] = h["var"].map(lambda v: "air" if v.startswith("Zone Mean") else "surface")
    k = ["configuration", "case", "day", "algo", "what", "key"]
    ref = h[h.ts == 30].set_index(k + ["hour", "minute"]).value.rename("ref")
    h = h.join(ref, on=k + ["hour", "minute"])
    h["e"] = h.value - h.ref
    rms30 = h[h.ts < 30].groupby(k + ["ts"]).e.apply(lambda e: float(np.sqrt((e ** 2).mean()))).reset_index()
    o30 = []
    for kk, g in rms30.groupby(k):
        g = g[g.e > 0]
        if len(g) >= 3 and g.e.median() > ROUND_OFF:
            o30.append(dict(zip(k, kk)) | {"order": float(np.polyfit(np.log(60.0 / g.ts), np.log(g.e), 1)[0])})
    o30 = (pd.DataFrame(o30).groupby(["case", "day", "algo", "what", "configuration"]).order.median()
           .unstack("configuration")[labels].round(2))
    o30.to_csv(out / "observed_order_ref30.csv")
    r30 = (rms30[(rms30.what == "air") & (rms30.ts == 4)]
           .pivot_table(index=["case", "day", "algo"], columns="configuration", values="e")[labels])
    r30.to_csv(out / "rms_error_ts04_ref30.csv", float_format="%.4g")

    pd.set_option("display.width", 200)
    pd.set_option("display.max_rows", 200)
    print("Measured order against the 30/h run (same conduction grid), fitted from 2 to 10/h")
    print(o30.to_string())
    print("\nRMS error of the zone air temperature at 4/h [C]")
    print(r30.to_string(float_format=lambda x: f"{x:.3g}"))


if __name__ == "__main__":
    main()
