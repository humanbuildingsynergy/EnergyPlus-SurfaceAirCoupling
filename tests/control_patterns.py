"""Error of the daily ideal-load energy of the single room under five control patterns, with the
release and the converged configuration.

The room is single_room.py's "ideal" case without solar gain, third-order scheme. Patterns:
  always_constant     heating = cooling = 22 C all day (always controlled, never floating)
  always_step2        heating = cooling, 22 C with a step to 20 C from 08:00 to 18:00; the
                      setpoint changes only on the hour, which every timestep shares
  always_step2_nosub  the same with MaxZoneTempDiff raised to 3 C, so the 2 K step does not
                      trigger the subdivision of the HVAC timestep
  band_constant       heating 21 C, cooling 22 C all day; the floating zone spans 20.6 to 22.4 C
                      on the summer day, so it switches between floating and control at times
                      set by the solution
  band_stepped        single_room.py's band: 21/24 C from 08:00 to 18:00, 15/30 C otherwise
Writes results/single_room/control_patterns.csv: per pattern, configuration and design day (CLG
summer, HTG winter), the daily energy at 30 per hour [kWh], the number of on/off switches of the
ideal loads at 30 per hour, the relative error at 4 per hour against the 30/h run of the same
configuration (a fraction), and the order fitted from 2 to 10 per hour.
Raw runs: <runs>/control_patterns/<pattern>/<configuration>/tsNN/.
Usage (repository root): python3 tests/control_patterns.py [--configurations release converged]
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

import _common as common
import single_room as room

sys.path.insert(0, str(common.REPO))
import configurations as C  # noqa: E402

TS = [2, 3, 4, 5, 6, 10, 30]
STEP2 = common.schedules(heat=[("08:00", 22), ("18:00", 20), ("24:00", 22)],
                         cool=[("08:00", 22), ("18:00", 20), ("24:00", 22)])
# PerformancePrecisionTradeoffs field 4, MaxZoneTempDiff: subdivide the HVAC timestep only above 3 C.
NOSUB = "\n  PerformancePrecisionTradeoffs, No, ScriptF, Advanced, 3.0, 0.002;\n"
PATTERNS = {  # name: (setpoint schedules, extra input)
    "always_constant": (common.schedules(heat=[("24:00", 22)], cool=[("24:00", 22)]), ""),
    "always_step2": (STEP2, ""),
    "always_step2_nosub": (STEP2, NOSUB),
    "band_constant": (common.schedules(heat=[("24:00", 21)], cool=[("24:00", 22)]), ""),
    "band_stepped": (common.STEPPED, ""),
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--configurations", nargs="+", default=["release", "converged"])
    ap.add_argument("--patterns", nargs="+", default=list(PATTERNS), choices=list(PATTERNS))
    ap.add_argument("--runs", default=str(common.REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(common.RESULTS / "single_room"),
                    help="folder for control_patterns.csv")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    runs = Path(a.runs).resolve() / "control_patterns"
    base = (C.RELEASE / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()
    jobs, meta = [], []
    for pat in a.patterns:
        sched, extra_input = PATTERNS[pat]
        for conf in a.configurations:
            eplus, env = C.program(conf)
            for ts in TS:
                idf = room.make_idf(base, "ideal", ts, "ThirdOrderBackwardDifference")
                assert common.STEPPED in idf
                idf = common.no_solar(idf.replace(common.STEPPED, sched)) + extra_input
                name = f"{pat}/{conf}/ts{ts:02d}"
                jobs.append((str(eplus), idf, name, str(runs), True, env))
                meta.append((pat, conf, ts, name))
    common.run_all(jobs, a.workers)

    rows = []
    for pat, conf, ts, name in meta:
        for d, v in common.daily(runs / name / "eplusout.sql").items():
            rows.append({"pattern": pat, "configuration": conf, "day": d, "ts": ts, "kWh": v["kWh"],
                         "switches": v["switches"]})
    df = pd.DataFrame(rows)
    keys = ["pattern", "configuration", "day"]
    ref = df[df.ts == 30].set_index(keys)[["kWh", "switches"]]
    df = df.join(ref.rename(columns={"kWh": "kWh30", "switches": "switches30"}), on=keys)
    df["rel_err"] = (df.kWh / df.kWh30 - 1).abs()
    out = []
    for (pat, conf, d), g in df.groupby(keys):
        f = g[g.ts.isin(common.FIT)]
        out.append({"pattern": pat, "configuration": conf, "day": d, "kWh_ts30": float(g.kWh30.iloc[0]),
                    "switches_ts30": int(g.switches30.iloc[0]),
                    "rel_err_ts04": float(g[g.ts == 4].rel_err.iloc[0]), "order": common.order(f.ts, f.rel_err)})
    out = pd.DataFrame(out)
    Path(a.results).mkdir(parents=True, exist_ok=True)
    out.to_csv(Path(a.results) / "control_patterns.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 200)
    print(out.pivot_table(index=["day", "pattern"], columns="configuration",
                          values=["rel_err_ts04", "order", "switches_ts30"])
          .to_string(float_format=lambda x: f"{x:.3g}"))


if __name__ == "__main__":
    main()
