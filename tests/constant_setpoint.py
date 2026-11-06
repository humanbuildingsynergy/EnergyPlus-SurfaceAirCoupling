"""The single room held at one constant setpoint (heating = cooling = 22 C all day), so the zone is
always controlled and never floats, with and without solar gain, for the three zone air schemes.

Configurations: the release; both_faces (surfaces and air solved to agreement with the HVAC held at
its first result); converged (the HVAC also repeated in each pass). Comparing the last two shows
why the HVAC must be in the loop: without it the air moves off its setpoint.
Writes results/single_room/constant_setpoint.csv: per sky (solar: as distributed; nosolar: sky
clearness 0), configuration, scheme and design day, the daily ideal-load energy at 30 per hour
[kWh], its relative error at 4 per hour against the 30/h run of the same configuration and scheme
(a fraction), the order fitted from 2 to 10 per hour, and the largest deviation of the hour-end
zone air temperature from 22 C over all timesteps [C].
Raw runs: <runs>/constant_setpoint/<sky>/<configuration>/<scheme>_tsNN/.
Usage (repository root):
  python3 tests/constant_setpoint.py [--configurations release both_faces converged] [--runs runs]
"""

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402
import single_room as room  # noqa: E402

TS = [2, 3, 4, 5, 6, 10, 30]
FIT = [2, 3, 4, 5, 6, 10]
CONFIGURATIONS = ["release", "both_faces", "converged"]
# The setpoint schedules of single_room.py's "ideal" case, replaced by CONSTANT.
STEPPED = """  Schedule:Compact, CoolSP, , Through: 12/31, For: AllDays,
    Until: 08:00, 30, Until: 18:00, 24, Until: 24:00, 30;
  Schedule:Compact, HeatSP, , Through: 12/31, For: AllDays,
    Until: 08:00, 15, Until: 18:00, 21, Until: 24:00, 15;
"""
CONSTANT = """  Schedule:Compact, CoolSP, , Through: 12/31, For: AllDays, Until: 24:00, 22;
  Schedule:Compact, HeatSP, , Through: 12/31, For: AllDays, Until: 24:00, 22;
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--configurations", nargs="+", default=CONFIGURATIONS)
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(REPO / "results" / "single_room"),
                    help="folder for constant_setpoint.csv")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    runs = Path(a.runs).resolve() / "constant_setpoint"
    base = (C.RELEASE / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()
    jobs, meta = [], []
    for sky in ("solar", "nosolar"):
        for conf in a.configurations:
            eplus, env = C.program(conf)
            for algo in room.ALGOS:
                for ts in TS:
                    idf = room.make_idf(base, "ideal", ts, algo)
                    assert STEPPED in idf
                    idf = idf.replace(STEPPED, CONSTANT)
                    if sky == "nosolar":
                        idf = room.sub_once(r"1\.00;(\s*!- Sky Clearness)", r"0.00;\1", idf)
                    name = f"{sky}/{conf}/{algo}_ts{ts:02d}"
                    jobs.append((str(eplus), idf, name, str(runs), True, env))
                    meta.append((sky, conf, algo, ts, name))
    with ProcessPoolExecutor(a.workers) as ex:
        log = list(ex.map(room.run, jobs))
    bad = [r for r in log if r["returncode"] != 0]
    if bad:
        sys.exit(f"failed runs: {bad}")

    rows = []
    for sky, conf, algo, ts, name in meta:
        df = room.hour_end_series(runs / name / "eplusout.sql")
        for env, g in df.groupby("env"):
            loads = g[g["var"].str.startswith("Zone Ideal Loads")]  # sensible heating and cooling [J]
            air = g[g["var"].str.startswith("Zone Mean") & g.minute.isin([0, 60])]
            rows.append({"sky": sky, "configuration": conf, "algo": algo, "ts": ts,
                         "day": "CLG" if "CLG" in env else "HTG",
                         "kWh": loads.value.sum() / 3.6e6,
                         "max_abs_air_minus_22_C": float((air.value - 22.0).abs().max())})
    d = pd.DataFrame(rows)
    keys = ["sky", "configuration", "algo", "day"]
    r30 = d[d.ts == 30].set_index(keys).kWh.rename("kWh30")
    d = d.join(r30, on=keys)
    d["rel_err"] = (d.kWh / d.kWh30 - 1).abs()
    out = []
    for (sky, conf, algo, day), g in d.groupby(keys):
        f = g[g.ts.isin(FIT) & (g.rel_err > 0)]
        out.append({"sky": sky, "configuration": conf, "algo": algo, "day": day,
                    "kWh_ts30": float(g[g.ts == 30].kWh.iloc[0]),
                    "rel_err_ts04": float(g[g.ts == 4].rel_err.iloc[0]),
                    "order": round(float(np.polyfit(np.log(60.0 / f.ts), np.log(f.rel_err), 1)[0]), 2),
                    "max_abs_air_minus_22_C": float(g.max_abs_air_minus_22_C.max())})
    out = pd.DataFrame(out)
    Path(a.results).mkdir(parents=True, exist_ok=True)
    out.to_csv(Path(a.results) / "constant_setpoint.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 220)
    for col in ("rel_err_ts04", "order", "max_abs_air_minus_22_C"):
        print(f"== {col}")
        print(out.pivot_table(index=["sky", "day", "algo"], columns="configuration", values=col)[a.configurations]
              .to_string(float_format=lambda x: f"{x:.3g}"), "\n")


if __name__ == "__main__":
    main()
