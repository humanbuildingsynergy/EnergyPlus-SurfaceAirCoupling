"""Where the three largest changes in annual energy sit: by month, by hour of day and by heating
coil or fan.

The three cases of results/prototypes/largest_changes.csv (study/describe_cases.py) are run again
with the release and two passes, base input, with hourly outputs added: the meters
Heating:NaturalGas, Heating:Electricity and Fans:Electricity, and the variables Heating Coil
Heating Energy and Fan Electricity Energy for every coil and fan. Output requests do not change
the solution, and the check table confirms that the annual heating and fan energy of these runs
equal those of the study runs (case_metrics.csv). The change (two passes minus release) of the end
use named in largest_changes.csv is then summed by month, by hour of day and by component; the
component names carry the zone or air system.
Raw runs: <runs>/locate_changes/<case>/<configuration>/. Writes, in results/prototypes/:
largest_changes_check.csv, largest_changes_by_month.csv, largest_changes_by_hour.csv and
largest_changes_by_component.csv (energy in GJ).

Usage (repository root): python3 study/locate_changes.py [--cases CASE ...] [--runs DIR]
With --cases, only those of the three cases are run and the check table is printed; the results
files are written only when all three are run.
"""
import argparse
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_cases as A  # noqa: E402
import run_cases as RC  # noqa: E402

CONFIGS = ("release", "two_passes")
EXTRA = """
  Output:Meter,Heating:NaturalGas,Hourly;
  Output:Meter,Heating:Electricity,Hourly;
  Output:Meter,Fans:Electricity,Hourly;
  Output:Variable,*,Heating Coil Heating Energy,Hourly;
  Output:Variable,*,Fan Electricity Energy,Hourly;
"""


def run(job):
    case, configuration, epw, d = job
    install, env = RC.C.program(configuration)
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "in.idf").write_text((RC.INPUTS / f"{case}_base.idf").read_text(errors="replace") + EXTRA)
    p = subprocess.run([str(install / "energyplus"), "-w", str(epw), "-d", str(d), "in.idf"], cwd=d,
                       env=RC.C.run_environment(env), capture_output=True, text=True)
    return case, configuration, p.returncode


def hourly(d, names, kind):
    """Hourly values [GJ] of the named meters or variables in the weather-file run period (the
    last environment)."""
    con = sqlite3.connect(d / "eplusout.sql")
    q = """SELECT t.Month, t.Hour, rdd.KeyValue, rdd.Name, rd.Value
           FROM ReportData rd JOIN ReportDataDictionary rdd USING (ReportDataDictionaryIndex)
           JOIN Time t USING (TimeIndex)
           WHERE rdd.ReportingFrequency='Hourly' AND rdd.Name IN ({})
           AND t.EnvironmentPeriodIndex = (SELECT MAX(EnvironmentPeriodIndex) FROM Time)""".format(
        ",".join("?" * len(names)))
    df = pd.read_sql(q, con, params=names)
    con.close()
    df["GJ"] = df.Value / 1e9  # J to GJ
    df["kind"] = kind
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", nargs="*", help="run only these of the three cases")
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder for raw runs")
    ap.add_argument("--workers", type=int, default=6, help="parallel runs (6 = all at once)")
    a = ap.parse_args()
    runs = a.runs / "locate_changes"
    top = pd.read_csv(RC.RESULTS / "largest_changes.csv")
    full = not a.cases
    if a.cases:
        top = top[top.case.isin(a.cases)]
    src = pd.read_csv(RC.RESULTS / "sources.csv").set_index("case")
    jobs = [(c, conf, RC.WEATHER / src.loc[c, "weather"], runs / c / conf) for c in top.case for conf in CONFIGS]
    with ProcessPoolExecutor(min(a.workers, len(jobs))) as ex:
        res = list(ex.map(run, jobs))
    if any(rc != 0 for *_, rc in res):
        sys.exit(f"failed: {res}")

    study = pd.read_csv(RC.RESULTS / "case_metrics.csv").set_index(["case", "variant", "configuration"])
    chk, by_month, by_hour, by_comp = [], [], [], []
    for r in top.itertuples():
        meters = ["Heating:NaturalGas", "Heating:Electricity"] if r.end_use == "heating" else ["Fans:Electricity"]
        var = "Heating Coil Heating Energy" if r.end_use == "heating" else "Fan Electricity Energy"
        data = {}
        for conf in CONFIGS:
            d = runs / r.case / conf
            m = A.run_metrics(d)
            for col in ("heating_GJ", "fans_GJ"):
                chk.append({"case": r.case, "configuration": conf, "metric": col, "rerun": m[col],
                            "study": study.loc[(r.case, "base", conf), col],
                            "equal": abs(m[col] - study.loc[(r.case, "base", conf), col]) < 1e-6})
            data[conf] = (hourly(d, meters, "meter"), hourly(d, [var], "component"))
        for keys, out in ((["Month"], by_month), (["Hour"], by_hour)):
            g = {conf: data[conf][0].groupby(keys).GJ.sum() for conf in CONFIGS}
            t = pd.DataFrame({"release_GJ": g["release"], "two_passes_GJ": g["two_passes"]}).reset_index()
            t["delta_GJ"] = t.two_passes_GJ - t.release_GJ
            t.insert(0, "case", r.case)
            t.insert(1, "end_use", r.end_use)
            out.append(t)
        g = {conf: data[conf][1].groupby("KeyValue").GJ.sum() for conf in CONFIGS}
        t = pd.DataFrame({"release_GJ": g["release"], "two_passes_GJ": g["two_passes"]}).fillna(0).reset_index()
        t["delta_GJ"] = t.two_passes_GJ - t.release_GJ
        t["share_of_total_delta"] = t.delta_GJ / t.delta_GJ.sum()
        t = t.reindex(t.delta_GJ.abs().sort_values(ascending=False).index)  # largest change first
        t.insert(0, "case", r.case)
        t.insert(1, "component", var)
        by_comp.append(t)
    print(pd.DataFrame(chk).to_string(index=False))
    if not full:
        return
    pd.DataFrame(chk).to_csv(RC.RESULTS / "largest_changes_check.csv", index=False, float_format="%.6g")
    pd.concat(by_month).to_csv(RC.RESULTS / "largest_changes_by_month.csv", index=False, float_format="%.5g")
    pd.concat(by_hour).to_csv(RC.RESULTS / "largest_changes_by_hour.csv", index=False, float_format="%.5g")
    pd.concat(by_comp).to_csv(RC.RESULTS / "largest_changes_by_component.csv", index=False,
                              float_format="%.5g")


if __name__ == "__main__":
    main()
