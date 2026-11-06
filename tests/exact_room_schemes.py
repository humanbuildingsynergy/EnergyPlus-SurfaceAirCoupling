"""Room with an exact solution under all three zone air schemes, for the four configurations.

The room, inputs, timesteps and error measure of exact_room.py, with ZoneAirHeatBalanceAlgorithm
set to ThirdOrderBackwardDifference, EulerMethod and AnalyticalSolution. The exact solution
(results/exact_room/exact_solution.csv.gz, from exact_room.py) does not depend on the scheme.
Writes results/exact_room/schemes.csv: per scheme, configuration and timestep, the RMS, largest and
mean error of the zone air temperature at the zone timestep ends from day 3 [C]; the order fitted
from 4 to 20 per hour (repeated on each row of the pair); and the local order to the next timestep
of the sweep, ln(e_k / e_k+1) / ln(n_k+1 / n_k). The third-order rows repeat exact_room.py's runs
and must match its errors.csv. Column "program": the install each configuration runs with.
Raw runs: <runs>/exact_room_schemes/<scheme>/<configuration>_tsNN/.
Usage (repository root):
  python3 tests/exact_room_schemes.py [--schemes ...] [--configurations ...] [--timesteps ...]
                                      [--runs runs] [--no-runs] [--workers 24]
"""
import argparse
import re
import shutil
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import exact_room as exact

C = exact.C
SCHEMES = ["ThirdOrderBackwardDifference", "EulerMethod", "AnalyticalSolution"]


def make_idf(scheme, ts):
    return exact.sub1(r"ZoneAirHeatBalanceAlgorithm,ThirdOrderBackwardDifference;",
                  f"ZoneAirHeatBalanceAlgorithm,{scheme};", exact.make_idf(ts))


def run(job):
    scheme, conf, ts, runs = job
    d = Path(runs) / scheme / f"{conf}_ts{ts:02d}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(make_idf(scheme, ts))
    eplus, extra = C.program(conf)
    p = subprocess.run([str(eplus / "energyplus"), "-w", str(exact.EPW), "-d", str(d), "in.idf"], cwd=d,
                       env=C.run_environment(extra), capture_output=True, text=True)
    err = (d / "eplusout.err").read_text(errors="replace")
    return {"scheme": scheme, "configuration": conf, "ts": ts, "returncode": p.returncode,
            "completed": "EnergyPlus Completed Successfully" in err}


def errors(d, ref):
    z = exact.series(d, "Zone Air Temperature")
    m = exact.minute_of_year(z).to_numpy()
    step = 60 // int(re.search(r"ts(\d+)", d.name).group(1))
    keep = (m % step == 0) & (m >= exact.START)
    zz = pd.Series(z.Value.to_numpy()[keep], index=m[keep]).groupby(level=0).last()
    dev = zz.to_numpy() - ref[zz.index.to_numpy()]
    return {"n_points": len(zz), "rms_C": float(np.sqrt(np.mean(dev ** 2))),
            "max_abs_C": float(np.abs(dev).max()), "mean_C": float(dev.mean())}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--schemes", nargs="+", default=SCHEMES, choices=SCHEMES)
    ap.add_argument("--configurations", nargs="+", default=exact.CONFIGURATIONS)
    ap.add_argument("--timesteps", nargs="+", type=int, default=exact.STEPS)
    ap.add_argument("--runs", default=str(exact.REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(exact.RESULTS), help="folder for schemes.csv")
    ap.add_argument("--no-runs", action="store_true", help="reuse the EnergyPlus runs in --runs")
    ap.add_argument("--workers", type=int, default=24)
    a = ap.parse_args()
    runs = Path(a.runs).resolve() / "exact_room_schemes"
    jobs = [(s, e, ts, str(runs)) for s in a.schemes for e in a.configurations for ts in a.timesteps]
    if not a.no_runs:
        with ProcessPoolExecutor(a.workers) as ex:
            log = pd.DataFrame(list(ex.map(run, jobs)))
        bad = log[~log.completed]
        if len(bad):
            print("not completed:", bad.values.tolist())
    ref = pd.read_csv(exact.RESULTS / "exact_solution.csv.gz").T_ref_C.to_numpy()
    assert len(ref) == 525601
    rows = []
    for s, e, ts, _ in jobs:
        d = runs / s / f"{e}_ts{ts:02d}"
        ok = (d / "eplusout.err").exists() and "EnergyPlus Completed Successfully" in (d / "eplusout.err").read_text(errors="replace")
        rows.append({"scheme": s, "configuration": e, "program": "release" if e == "release" else "patched",
                     "ts": ts, "completed": ok} | (errors(d, ref) if ok else {}))
    df = pd.DataFrame(rows)
    out = []
    for (s, e), g in df.groupby(["scheme", "configuration"], sort=False):
        g = g.sort_values("ts").copy()
        f = g[g.ts.isin(exact.FIT) & g.completed]
        g["fitted_order_4_20"] = np.polyfit(np.log(60.0 / f.ts), np.log(f.rms_C), 1)[0] if len(f) >= 2 else np.nan
        n, err = g.ts.to_numpy(float), g.rms_C.to_numpy(float)
        loc = np.full(len(g), np.nan)
        loc[:-1] = np.log(err[:-1] / err[1:]) / np.log(n[1:] / n[:-1])
        g["local_order_to_next_ts"] = loc
        g["next_ts"] = list(g.ts.iloc[1:]) + [np.nan]
        out.append(g)
    df = pd.concat(out)
    Path(a.results).mkdir(parents=True, exist_ok=True)
    df.to_csv(Path(a.results) / "schemes.csv", index=False, float_format="%.6g")

    old = pd.read_csv(exact.RESULTS / "errors.csv")
    t = df[df.scheme == "ThirdOrderBackwardDifference"].merge(old, on=["configuration", "ts"])
    print(f"third-order rows against errors.csv: max |diff rms| {(t.rms_C_x - t.rms_C_y).abs().max():.3g} C")
    pd.set_option("display.width", 220)
    print(df.pivot_table(index="ts", columns=["scheme", "configuration"], values="rms_C").round(4).to_string())
    print(df.groupby(["scheme", "configuration"], sort=False).fitted_order_4_20.first().round(3).to_string())
    w = df[df.ts.isin(exact.FIT[:-1])]
    print(w.pivot_table(index="ts", columns=["scheme", "configuration"], values="local_order_to_next_ts").round(2).to_string())


if __name__ == "__main__":
    main()
