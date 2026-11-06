"""Accuracy against runtime in three prototype buildings in Denver (medium office, primary school,
standalone retail): does the coupled solution reach a given accuracy at less runtime than the
release?

Each base input from study/prepare_inputs.py is changed only in its timestep and by one hourly
output, Zone Mean Air Temperature, which the air temperature error needs. Three phases:
  reference  the converged configuration at 60 per hour (the reference) and at 30 per hour (a check
             on the reference), run in parallel
  timed      release, one pass and two passes at 4, 6, 10, 15, 20, 30 and 60 per hour, run one at
             a time, three repeats. The repeats are the outer loop, so a slow drift of the machine
             spreads over all conditions. Nothing else should run on the machine meanwhile.
  analyze    errors against the reference, median wall times and the runtime test
Errors: relative error of annual heating and of annual cooling energy (defined as in
analyze_cases.py), and the RMS difference of hourly zone mean air temperature over the conditioned
zones (zones named by a ZoneControl:Thermostat, directly or through a ZoneList) and all hours of the
year. Runtime test, per building and error measure: the release's runtime needed to reach the error
of two passes at 4 per hour, interpolated on logarithmic scales along the release's timesteps (first
crossing), divided by the runtime of two passes at 4 per hour. When the release does not reach that
error at 60 per hour, the ratio is reported as a lower bound, release at 60 per hour / two passes
at 4 per hour. The coupled solution counts as faster when the ratio of the air temperature error is
at least 2 in every building.
Raw runs: <runs>/accuracy_runtime/<case>/<configuration>_tsNN/ (repeats 2 and 3 are deleted after
timing). Writes, in results/prototypes/: accuracy_runtime_reference_runs.csv,
accuracy_runtime_timed_runs.csv, accuracy_runtime_errors.csv and accuracy_runtime_summary.csv.

Usage (repository root):
  python3 study/accuracy_runtime.py reference [--cases ...]
  python3 study/accuracy_runtime.py timed [--cases ...] [--configurations ...] [--timesteps ...] [--redo]
  python3 study/accuracy_runtime.py analyze
"timed" skips runs already in accuracy_runtime_timed_runs.csv and saves that file after every run,
so it can be stopped and restarted. With --redo it runs the chosen runs again and replaces their
rows, for example to time a subset on another machine.
"""

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_cases as A  # noqa: E402
import run_cases as RC  # noqa: E402

BUILDINGS = ["OfficeMedium_Denver", "SchoolPrimary_Denver", "RetailStandalone_Denver"]
STEPS = [4, 6, 10, 15, 20, 30, 60]
TIMED = ["release", "one_pass", "two_passes"]
REPEATS = 3
EPW = RC.WEATHER / "USA_CO_Denver-Aurora-Buckley.AFB_.724695_TMY3.epw"


def make_idf(case, ts):
    t = (RC.INPUTS / f"{case}_base.idf").read_text(errors="replace")
    n = len(re.findall(r"^\s*Timestep,\s*\d+\s*;", t, re.M | re.I))
    if n != 1:
        sys.exit(f"{case}: {n} Timestep objects")
    t = re.sub(r"^(\s*Timestep,\s*)\d+(\s*;)", rf"\g<1>{ts}\2", t, flags=re.M | re.I)
    return t + "\n  Output:Variable,*,Zone Mean Air Temperature,Hourly;\n"


def run(case, configuration, ts, d):
    """One run; returns its wall time [s] and whether it completed."""
    install, env = RC.C.program(configuration)
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(make_idf(case, ts))
    t0 = time.perf_counter()
    p = subprocess.run([str(install / "energyplus"), "-w", str(EPW), "-d", str(d), "in.idf"], cwd=d,
                       env=RC.C.run_environment(env), capture_output=True, text=True)
    wall = time.perf_counter() - t0
    err = (d / "eplusout.err").read_text(errors="replace") if (d / "eplusout.err").exists() else ""
    return {"case": case, "configuration": configuration, "ts": ts, "wall_s": round(wall, 2),
            "completed": "EnergyPlus Completed Successfully" in err and p.returncode == 0}


def reference_job(j):
    case, ts, runs = j
    return run(case, "converged", ts, runs / case / f"converged_ts{ts:02d}")


def conditioned_zones(case):
    """Upper-case names of the zones controlled by a ZoneControl:Thermostat, with zone lists
    expanded."""
    t = (RC.INPUTS / f"{case}_base.idf").read_text(errors="replace")
    zones = set()
    for body in re.findall(r"^\s*ZoneControl:Thermostat,\s*\n([^;]*);", t, re.M | re.I):
        fields = [re.sub(r"!.*", "", x).strip().rstrip(",").strip() for x in body.splitlines()]
        zones.add(fields[1].upper())  # field 2: zone or zone list name
    lists = {}
    for body in re.findall(r"^\s*ZoneList,\s*\n([^;]*);", t, re.M | re.I):
        fields = [re.sub(r"!.*", "", x).strip().rstrip(",").strip() for x in body.splitlines()]
        lists[fields[0].upper()] = [z.upper() for z in fields[1:] if z]
    out = set()
    for z in zones:
        out |= set(lists.get(z, [z]))
    return out


def air(d, zones):
    """Hourly zone mean air temperature [C] of the given zones in the weather-file run period."""
    con = sqlite3.connect(d / "eplusout.sql")
    q = """SELECT t.Month, t.Day, t.Hour, rdd.KeyValue, rd.Value
           FROM ReportData rd JOIN ReportDataDictionary rdd USING (ReportDataDictionaryIndex)
           JOIN Time t USING (TimeIndex)
           WHERE rdd.Name='Zone Mean Air Temperature' AND rdd.ReportingFrequency='Hourly'
           AND t.EnvironmentPeriodIndex = (SELECT MAX(EnvironmentPeriodIndex) FROM Time)"""
    df = pd.read_sql(q, con)
    con.close()
    df = df[df.KeyValue.str.upper().isin(zones)]
    return df.set_index(["Month", "Day", "Hour", "KeyValue"]).Value


def annual(d):
    m = A.run_metrics(d)
    return m["heating_GJ"], m["cooling_GJ"]


def cmd_reference(a):
    jobs = [(c, ts, a.runs / "accuracy_runtime") for c in a.cases for ts in (60, 30)]
    with ProcessPoolExecutor(len(jobs)) as ex:
        res = list(ex.map(reference_job, jobs))
    path = RC.RESULTS / "accuracy_runtime_reference_runs.csv"
    df = pd.DataFrame(res)
    if set(a.cases) != set(BUILDINGS) and path.exists():  # keep the other buildings' rows
        old = pd.read_csv(path)
        df = pd.concat([old[~old.case.isin(a.cases)], df])
    df.to_csv(path, index=False)
    print(df.to_string(index=False))


def cmd_timed(a):
    runs = a.runs / "accuracy_runtime"
    path = RC.RESULTS / "accuracy_runtime_timed_runs.csv"
    done = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["case", "configuration", "ts", "repeat"])
    rows = done.to_dict("records")
    key = lambda r: (r["case"], r["configuration"], int(r["ts"]), int(r["repeat"]))
    chosen = [(c, conf, ts, k) for k in range(1, a.repeats + 1) for c in a.cases for conf in a.configurations
              for ts in a.timesteps]
    if a.redo:  # drop the chosen runs' rows (at the first save), so an interrupted redo resumes without --redo
        rows = [r for r in rows if key(r) not in set(chosen)]
    have = {key(r) for r in rows}
    todo = [t for t in chosen if t not in have]
    print(f"{len(todo)} timed runs to do, started {time.strftime('%H:%M %Z')}", flush=True)
    for i, (c, conf, ts, k) in enumerate(todo, 1):
        d = runs / c / f"{conf}_ts{ts:02d}" if k == 1 else runs / "repeat" / f"{c}_{conf}_ts{ts:02d}"
        r = run(c, conf, ts, d) | {"repeat": k}
        if k > 1:
            shutil.rmtree(d, ignore_errors=True)  # the outputs do not change between repeats
        rows.append(r)
        pd.DataFrame(rows).to_csv(path, index=False)  # saved after every run
        print(f"{time.strftime('%H:%M')} {i}/{len(todo)} {c} {conf} {ts}/h repeat {k}: {r['wall_s']} s",
              flush=True)


def first_crossing(x, y, target):
    """Smallest x (log-log interpolated) at which y falls to target, along increasing x, and whether
    it does at all."""
    for i in range(len(x)):
        if y[i] <= target:
            if i == 0:
                return x[0], True
            lx = np.interp(np.log(target), [np.log(y[i]), np.log(y[i - 1])], [np.log(x[i]), np.log(x[i - 1])])
            return float(np.exp(lx)), True
    return float(x[-1]), False


def cmd_analyze(a):
    runs_dir = a.runs / "accuracy_runtime"
    runs = pd.read_csv(RC.RESULTS / "accuracy_runtime_timed_runs.csv")
    if not runs.completed.all():
        print("incomplete timed runs:",
              runs[~runs.completed][["case", "configuration", "ts", "repeat"]].values.tolist())
    wall = runs[runs.completed].groupby(["case", "configuration", "ts"]).wall_s.median()
    rows = []
    for c in BUILDINGS:
        zones = conditioned_zones(c)
        ref_d = runs_dir / c / "converged_ts60"
        a_ref = air(ref_d, zones)
        h_ref, c_ref = annual(ref_d)
        for conf, ts, d in [("converged", 30, runs_dir / c / "converged_ts30")] + [
                (conf, ts, runs_dir / c / f"{conf}_ts{ts:02d}") for conf in TIMED for ts in STEPS]:
            a_ = air(d, zones)
            h, cl = annual(d)
            j = pd.concat([a_, a_ref], axis=1, keys=["x", "ref"]).dropna()  # hours present in both
            rows.append({"case": c, "configuration": conf, "ts": ts, "n_zones": len(zones),
                         "heating_err": abs(h / h_ref - 1) if h_ref else np.nan,
                         "cooling_err": abs(cl / c_ref - 1) if c_ref else np.nan,
                         "air_rms_C": float(np.sqrt(((j.x - j.ref) ** 2).mean())),
                         "n_air_values": len(j),
                         "wall_s_median": wall.get((c, conf, ts), np.nan)})
    err = pd.DataFrame(rows)
    err.to_csv(RC.RESULTS / "accuracy_runtime_errors.csv", index=False, float_format="%.6g")

    summ = []
    for c in BUILDINGS:
        g = err[err.case == c].set_index(["configuration", "ts"])
        for meas in ("air_rms_C", "heating_err", "cooling_err"):
            target = g.loc[("two_passes", 4), meas]
            r = g.loc["release"].loc[STEPS]
            ts_star, reached = first_crossing(np.array(STEPS, float), r[meas].values, target)
            t_star = float(np.exp(np.interp(np.log(ts_star), np.log(STEPS), np.log(r.wall_s_median.values))))
            summ.append({"case": c, "measure": meas, "two_passes_ts04_error": target,
                         "release_ts_needed": ts_star, "release_reached": reached,
                         "release_runtime_needed_s": t_star,
                         "two_passes_ts04_runtime_s": g.loc[("two_passes", 4), "wall_s_median"],
                         "ratio": t_star / g.loc[("two_passes", 4), "wall_s_median"],
                         "ratio_is_lower_bound": not reached})
    sm = pd.DataFrame(summ)
    sm.to_csv(RC.RESULTS / "accuracy_runtime_summary.csv", index=False, float_format="%.4g")
    print(sm.to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("phase", choices=["reference", "timed", "analyze"])
    ap.add_argument("--cases", nargs="*", default=BUILDINGS, choices=BUILDINGS)
    ap.add_argument("--configurations", nargs="*", default=TIMED, choices=TIMED, help="timed phase only")
    ap.add_argument("--timesteps", nargs="*", type=int, default=STEPS, choices=STEPS, help="timed phase only")
    ap.add_argument("--repeats", type=int, default=REPEATS, help="timed phase only (paper: 3)")
    ap.add_argument("--redo", action="store_true",
                    help="timed phase only: run the chosen runs again even if they are already in the file")
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder for raw runs")
    a = ap.parse_args()
    {"reference": cmd_reference, "timed": cmd_timed, "analyze": cmd_analyze}[a.phase](a)


if __name__ == "__main__":
    main()
