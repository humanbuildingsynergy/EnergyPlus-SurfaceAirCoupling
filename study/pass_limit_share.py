"""How much of each annual change from the release to two passes falls in the timesteps in which
the converged configuration ended at its pass limit, in the two buildings where that is frequent.

Cases: hospital and outpatient health care in all three climates, where the converged
configuration ends 39 to 75% of its timesteps at the limit of 50 passes (converged_pass_limit.csv).
Runs: the study's base inputs plus timestep meters, with the release and two passes, and with the
converged configuration with SURFACE_AIR_LOG=1, which reports every zone timestep that ends at the
limit (reporting only; the run is checked against the study's converged run).
For each zone timestep t of the run period, the change d(t) = two passes(t) - release(t) of heating
(Heating meters, electricity and natural gas), cooling (Cooling meters, electricity and natural gas),
fans (Fans:Electricity) and site energy (all *:Facility meters). "At the limit" = the timesteps in
which the converged configuration ended at its pass limit. Columns, per case and quantity:
  release_GJ, two_passes_GJ        annual sums of the meters
  change_pct                       annual change from the release to two passes (%)
  change_pct_not_at_limit          the same over the timesteps not at the limit only
  change_pct_at_limit              the same over the timesteps at the limit only
  share_of_change_at_limit         sum of d over the timesteps at the limit / sum of d
  share_of_abs_change_at_limit     the same for |d|
  share_of_release_at_limit        share of the release's end use that falls in those timesteps
  converged_vs_study_*_pct         converged run here against the study's converged run (%)
  site_meters_vs_tabular_pct_release   site meters against the tabular site total, release (%)
Inputs written to <PROTOTYPES>/pass_limit_share/. Raw runs:
<runs>/pass_limit_share/<case>/<configuration>/. Writes results/prototypes/pass_limit_share.csv.

Usage (repository root): python3 study/pass_limit_share.py [--cases ...] [--no-runs] [--runs DIR]
--no-runs analyzes existing runs. With --cases, the table is printed and not written.
"""

import argparse
import re
import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_cases as A  # noqa: E402
import run_cases as RC  # noqa: E402

CASES = [f"{b}_{c}" for b in ("Hospital", "OutPatientHealthCare") for c in ("Miami", "Denver", "InternationalFalls")]
CONFIGS = ("release", "two_passes", "converged")
INPUTS = RC.C.PROTOTYPES / "pass_limit_share"
METERS = ["Heating:Electricity", "Heating:NaturalGas", "Cooling:Electricity", "Cooling:NaturalGas",
          "Fans:Electricity", "Electricity:Facility", "NaturalGas:Facility", "DistrictHeatingWater:Facility",
          "DistrictCooling:Facility", "DistrictHeatingSteam:Facility", "Propane:Facility", "FuelOilNo2:Facility"]
GROUPS = {"heating": ["Heating:Electricity", "Heating:NaturalGas"], "cooling": ["Cooling:Electricity", "Cooling:NaturalGas"],
          "fans": ["Fans:Electricity"], "site": [m for m in METERS if m.endswith(":Facility")]}
STEPS_PER_HOUR = 6  # the timestep of every prototype file
# Start of the line that SURFACE_AIR_LOG=1 writes for each zone timestep at the pass limit:
# environment, month/day, hour of day (1-24) and timestep within the hour. Only this start is
# matched, because zone names may contain spaces.
LIMIT_LINE = re.compile(r"Surface-air passes not converged: (.+?) (\d\d)/(\d\d) hour (\d+) ts (\d+),")


def job(j):
    case, conf, runs = j
    weather = pd.read_csv(RC.RESULTS / "sources.csv").set_index("case").loc[case, "weather"]
    extra = {"SURFACE_AIR_LOG": "1"} if conf == "converged" else {}
    return RC.run_one((case, "base", conf, INPUTS / f"{case}.idf", RC.WEATHER / weather,
                       runs / case / conf, extra))


def meter_series(d):
    """Meter values per zone timestep of the run period [J], indexed by month, day and the minute of
    the day at the end of the timestep."""
    con = sqlite3.connect(d / "eplusout.sql")
    q = """SELECT t.Month AS month, t.Day AS day, t.Hour AS hour, t.Minute AS minute, rdd.Name AS name, rd.Value AS value
            FROM ReportData rd JOIN ReportDataDictionary rdd USING (ReportDataDictionaryIndex)
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE rdd.IsMeter = 1 AND rdd.ReportingFrequency IN ('Zone Timestep', 'Timestep') AND t.WarmupFlag = 0
            AND t.EnvironmentPeriodIndex = (SELECT MAX(EnvironmentPeriodIndex) FROM Time)"""
    df = pd.read_sql(q, con)
    con.close()
    df["minute_of_day"] = df.hour * 60 + df.minute
    return df.pivot_table(index=["month", "day", "minute_of_day"], columns="name", values="value", aggfunc="sum")


def limit_steps(d, n_per_hour):
    """Timesteps of the run period that the converged run reported at its pass limit, with the same
    index as meter_series (hour h, timestep k end at minute (h - 1) * 60 + k * 60 / n_per_hour)."""
    steps = set()
    for line in (d / "eplusout.err").read_text(errors="replace").splitlines():
        m = LIMIT_LINE.search(line)
        # the weather-file run period, as in run_cases.py: not a sizing period or design day
        if m and "SIZING" not in m.group(1).upper() and " DB" not in m.group(1).upper():
            mo, dy, h, k = int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5))
            steps.add((mo, dy, (h - 1) * 60 + k * 60 // n_per_hour))
    return steps


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", nargs="*", default=CASES, choices=CASES)
    ap.add_argument("--no-runs", action="store_true", help="analyze existing runs only")
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder for raw runs")
    a = ap.parse_args()
    runs = a.runs / "pass_limit_share"
    INPUTS.mkdir(parents=True, exist_ok=True)
    for c in a.cases:
        t = (RC.INPUTS / f"{c}_base.idf").read_text(errors="replace")
        (INPUTS / f"{c}.idf").write_text(t + "".join(f"\n  Output:Meter, {m}, Timestep;" for m in METERS) + "\n")
    jobs = sorted([(c, conf, runs) for c in a.cases for conf in CONFIGS], key=lambda j: j[1] != "converged")
    if not a.no_runs:
        with ProcessPoolExecutor(len(jobs)) as ex:
            log = list(ex.map(job, jobs))
        bad = [(r["case"], r["configuration"]) for r in log if not r["completed"]]
        if bad:
            sys.exit(f"not completed: {bad}")
    rows = []
    study = pd.read_csv(RC.RESULTS / "case_metrics.csv").set_index(["case", "variant", "configuration"])
    for c in a.cases:
        conv = runs / c / "converged"
        conv_m = A.run_metrics(conv)
        check = {k: A.pct(conv_m[k], study.loc[(c, "base", "converged"), k])
                 for k in ("heating_GJ", "cooling_GJ", "fans_GJ", "site_GJ")}
        at_limit = limit_steps(conv, STEPS_PER_HOUR)
        reported = int(re.findall(r"not converged (\d+)", (conv / "eplusout.err").read_text(errors="replace"))[-1])
        r_, f_ = meter_series(runs / c / "release"), meter_series(runs / c / "two_passes")
        inL = np.array([k in at_limit for k in r_.index])
        for g, ms in GROUPS.items():
            cols = [m for m in ms if m in r_.columns]
            if not cols:
                continue
            R, F = r_[cols].sum(axis=1).to_numpy(), f_.reindex(r_.index)[cols].sum(axis=1).to_numpy()
            dlt = F - R
            row = {"case": c, "quantity": g, "meters": "+".join(cols), "timesteps": len(R),
                   "timesteps_at_limit": int(inL.sum()), "timesteps_at_limit_reported": reported,
                   "release_GJ": R.sum() / 1e9, "two_passes_GJ": F.sum() / 1e9,
                   "change_pct": 100 * (F.sum() / R.sum() - 1) if R.sum() else np.nan,
                   "change_pct_not_at_limit": 100 * (F[~inL].sum() / R[~inL].sum() - 1) if R[~inL].sum() else np.nan,
                   "change_pct_at_limit": 100 * (F[inL].sum() / R[inL].sum() - 1) if R[inL].sum() else np.nan,
                   "share_of_change_at_limit": dlt[inL].sum() / dlt.sum() if dlt.sum() else np.nan,
                   "share_of_abs_change_at_limit": np.abs(dlt[inL]).sum() / np.abs(dlt).sum() if np.abs(dlt).sum() else np.nan,
                   "share_of_release_at_limit": R[inL].sum() / R.sum() if R.sum() else np.nan}
            if g == "site":
                row["site_meters_vs_tabular_pct_release"] = A.pct(R.sum() / 1e9,
                                                                  A.run_metrics(runs / c / "release")["site_GJ"])
            row |= {f"converged_vs_study_{k}_pct": v for k, v in check.items()}
            rows.append(row)
    df = pd.DataFrame(rows)
    if set(a.cases) == set(CASES):
        df.to_csv(RC.RESULTS / "pass_limit_share.csv", index=False, float_format="%.5g")
    pd.set_option("display.width", 250)
    print(df[["case", "quantity", "timesteps_at_limit", "timesteps_at_limit_reported", "change_pct",
              "change_pct_not_at_limit", "change_pct_at_limit", "share_of_change_at_limit",
              "share_of_abs_change_at_limit", "share_of_release_at_limit"]].to_string(index=False))
    print(df[[c for c in df.columns if c.startswith("converged_vs") or c.startswith("site_meters")]]
          .drop_duplicates().to_string())


if __name__ == "__main__":
    main()
