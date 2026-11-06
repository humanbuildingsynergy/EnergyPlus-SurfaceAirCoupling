"""How much the window-upgrade savings move when the release runs at an ordinary other timestep,
for comparison with the change that two passes make.

Cases: the 34 prototype cases eligible for the window upgrade (sources.csv; the small office is
excluded as in the study). Inputs: the study's <case>_base.idf and <case>_window.idf, changed only
in the Timestep object, to 4 and 10 per hour (the files ship with 6). Runs use run_cases.run_one,
and site energy uses analyze_cases.run_metrics; the 6-per-hour values are those of the study runs.
Savings = site energy of the base input minus that of the window input [GJ]. A change counts as
material by the study's rule for the window savings (at least 10%, or a change of sign), applied to
each configuration and timestep against the release at 6 per hour, and for two passes also against
the release at the same timestep.
Inputs written to <PROTOTYPES>/savings_timestep/. Raw runs: <runs>/savings_timestep/<case>/
<variant>_<configuration>_tsNN/. Writes, in results/prototypes/: window_savings_timestep_runs.csv
(run log) and window_savings_timestep.csv (one row per case, configuration and timestep).

Usage (repository root):
  python3 study/savings_timestep.py run [--configurations release two_passes] [--cases ...]
                                        [--workers N] [--runs DIR]
  python3 study/savings_timestep.py analyze [--cases ...] [--runs DIR]
With --cases, "run" replaces only those rows of the run log, and "analyze" compares the rows of
those cases (and --configurations) with the published window_savings_timestep.csv and writes
nothing.
"""

import argparse
import os
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_cases as A  # noqa: E402
import run_cases as RC  # noqa: E402

STEPS = [4, 10]  # timesteps per hour besides the shipped 6
INPUTS = RC.C.PROTOTYPES / "savings_timestep"


def cases(subset=None):
    src = pd.read_csv(RC.RESULTS / "sources.csv")
    src = src[src.window_savings_eligible.astype(bool) & ~src.case.str.startswith("OfficeSmall")]
    assert len(src) == 34, len(src)
    return src[src.case.isin(subset)] if subset else src


def make_idf(case, variant, ts):
    t = (RC.INPUTS / f"{case}_{variant}.idf").read_text(errors="replace")
    n = len(re.findall(r"^\s*Timestep,\s*\d+\s*;", t, re.M | re.I))
    if n != 1:
        sys.exit(f"{case} {variant}: {n} Timestep objects")
    t = re.sub(r"^(\s*Timestep,\s*)\d+(\s*;)", rf"\g<1>{ts}\2", t, flags=re.M | re.I)
    p = INPUTS / f"{case}_{variant}_ts{ts:02d}.idf"
    p.write_text(t)
    return p


def cmd_run(a):
    INPUTS.mkdir(parents=True, exist_ok=True)
    runs = a.runs / "savings_timestep"
    jobs = []
    for r in cases(a.cases).itertuples():
        epw = RC.WEATHER / r.weather
        for v in ("base", "window"):
            for ts in STEPS:
                idf = make_idf(r.case, v, ts)
                for conf in a.configurations:
                    jobs.append((r.case, f"{v}_ts{ts:02d}", conf, idf, epw,
                                 runs / r.case / f"{v}_{conf}_ts{ts:02d}"))
    big = ("Hospital", "HotelLarge", "OfficeLarge", "OutPatientHealthCare", "SchoolSecondary")
    jobs.sort(key=lambda j: (j[2] != "two_passes", not j[1].endswith("10"), not j[0].startswith(big)))
    print(f"{len(jobs)} runs, started {time.strftime('%H:%M %Z')}", flush=True)
    path = RC.RESULTS / "window_savings_timestep_runs.csv"
    rows = []
    with ProcessPoolExecutor(min(a.workers, len(jobs))) as ex:
        futs = [ex.submit(RC.run_one, j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            rows.append(f.result())
            if i % 10 == 0 or i == len(jobs):
                print(f"{time.strftime('%H:%M')} {i}/{len(jobs)} done", flush=True)
    df = pd.DataFrame(rows)
    df[["variant", "ts"]] = df.variant.str.extract(r"(\w+)_ts(\d+)")
    df["ts"] = df.ts.astype(int)
    key = ["case", "configuration", "ts", "variant"]
    if path.exists():  # keep the rows of runs not repeated now
        old = pd.read_csv(path)
        old = old.merge(df[key], on=key, how="left", indicator=True)
        df = pd.concat([old[old._merge == "left_only"].drop(columns="_merge"), df])
    df = df.sort_values(key, key=RC.sort_key)
    df.to_csv(path, index=False)
    bad = df[~df.completed.astype(bool)]
    print(f"completed {int(df.completed.astype(bool).sum())}/{len(df)}; not completed:",
          bad[["case", "variant", "configuration", "ts"]].values.tolist())


def site(d):
    return A.run_metrics(d)["site_GJ"]


def cmd_analyze(a):
    runs = pd.read_csv(RC.RESULTS / "window_savings_timestep_runs.csv")
    ok = {(r.case, r.variant, r.configuration, int(r.ts)) for r in runs.itertuples() if r.completed}
    study = pd.read_csv(RC.RESULTS / "case_runs.csv")
    ok |= {(r.case, r.variant, r.configuration, 6) for r in study.itertuples() if r.completed}

    def path(case, v, conf, ts):
        return (a.runs / "prototype_cases" / case / f"{v}_{conf}" if ts == 6
                else a.runs / "savings_timestep" / case / f"{v}_{conf}_ts{ts:02d}")

    rows = []
    for case in cases(a.cases).case:
        if not all((case, v, "release", 6) in ok for v in ("base", "window")):
            continue
        base6 = site(path(case, "base", "release", 6))
        s6 = base6 - site(path(case, "window", "release", 6))
        for conf in sorted((set(runs.configuration) | {"release"}) & set(a.configurations), key=RC.ROW_ORDER.get):
            for ts in [4, 6, 10]:
                if not all((case, v, conf, ts) in ok for v in ("base", "window")):
                    continue
                b = site(path(case, "base", conf, ts))
                s = b - site(path(case, "window", conf, ts))
                row = {"case": case, "configuration": conf, "ts": ts, "site_base_GJ": b, "savings_GJ": s,
                       "savings_release_ts06_GJ": s6, "site_base_release_ts06_GJ": base6,
                       "change_from_release_ts06_GJ": s - s6, "change_from_release_ts06_pct": A.pct(s, s6),
                       "change_from_release_ts06_pct_of_site": 100 * (s - s6) / base6}
                row["material_vs_release_ts06"] = bool(abs(row["change_from_release_ts06_pct"]) >= 10
                                                      or np.sign(s) != np.sign(s6))
                if conf != "release" and all((case, v, "release", ts) in ok for v in ("base", "window")):
                    sr = site(path(case, "base", "release", ts)) - site(path(case, "window", "release", ts))
                    row["savings_release_same_ts_GJ"] = sr
                    row["change_from_release_same_ts_pct"] = A.pct(s, sr)
                    row["material_vs_release_same_ts"] = bool(abs(row["change_from_release_same_ts_pct"]) >= 10
                                                              or np.sign(s) != np.sign(sr))
                rows.append(row)
    df = pd.DataFrame(rows)
    if a.cases:
        RC.compare_with_published(df, RC.RESULTS / "window_savings_timestep.csv",
                                  ["case", "configuration", "ts"], "%.6g")
        return
    df.to_csv(RC.RESULTS / "window_savings_timestep.csv", index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    r = df[df.configuration == "release"]
    for ts in (4, 10):
        g = r[r.ts == ts]
        print(f"release {ts}/h against release 6/h: {int(g.material_vs_release_ts06.sum())} of {len(g)} "
              f"material; median |change| {g.change_from_release_ts06_pct.abs().median():.1f}%")
    both = r[r.ts != 6].groupby("case").material_vs_release_ts06.any()
    print(f"release 4/h or 10/h against release 6/h: {int(both.sum())} of {len(both)} material")
    two = df[df.configuration == "two_passes"]
    for ts in sorted(two.ts.unique()):
        g = two[two.ts == ts]
        if "material_vs_release_same_ts" in g:
            print(f"two passes against the release at {ts}/h: {int(g.material_vs_release_same_ts.sum())} "
                  f"of {len(g)} material")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("phase", choices=["run", "analyze"])
    ap.add_argument("--configurations", nargs="*", default=["release", "two_passes"],
                    choices=RC.PAPER_CONFIGURATIONS, help="default: release two_passes")
    ap.add_argument("--cases", nargs="*", help="only these cases")
    ap.add_argument("--workers", type=int, default=os.cpu_count(), help="parallel runs")
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder for raw runs")
    a = ap.parse_args()
    {"run": cmd_run, "analyze": cmd_analyze}[a.phase](a)


if __name__ == "__main__":
    main()
