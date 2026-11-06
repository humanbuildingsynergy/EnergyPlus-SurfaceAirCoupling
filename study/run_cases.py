"""Run the prototype study: every case, input variant and configuration, one annual run each.

Reads the case list in results/prototypes/sources.csv and the inputs written by
study/prepare_inputs.py: <PROTOTYPES>/study/<case>_base.idf for all 48 cases and
<case>_window.idf for the cases eligible for the window upgrade. Raw runs go to
<runs>/prototype_cases/<case>/<variant>_<configuration>/. Writes results/prototypes/case_runs.csv,
one row per run with its completion status, warning and severe error counts, and the pass
statistics of the patched program. study/analyze_cases.py extracts the outcomes from the runs.

Usage (repository root):
  python3 study/run_cases.py [--cases CASE ...] [--configurations release two_passes ...]
                             [--workers N] [--runs DIR]
A run restricted to some cases or configurations replaces only those rows of case_runs.csv.
"""

import argparse
import io
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402

RESULTS = REPO / "results" / "prototypes"
DEFAULT_RUNS = REPO / "runs"
INPUTS = C.PROTOTYPES / "study"
WEATHER = C.PROTOTYPES / "weather"
PAPER_CONFIGURATIONS = list(C.CONFIGURATIONS)  # release, one_pass, two_passes, converged
# Row order of the results tables: the corrected configurations by number of passes, then the
# release.
ROW_ORDER = {"one_pass": 0, "two_passes": 1, "converged": 2, "release": 3}


def folder(path):
    """Argument type for --runs: an absolute path, since EnergyPlus runs inside each run folder."""
    return Path(path).resolve()


def sort_key(column):
    """Key for DataFrame.sort_values that puts configurations in ROW_ORDER."""
    return column.map(ROW_ORDER) if column.name == "configuration" else column


def compare_with_published(df, path, keys, float_format):
    """Print how the rows of df differ from the rows of a published table with the same keys.

    Used when a script reruns part of the work: df is formatted exactly as the script would write
    it, numbers are compared as relative differences, other cells as text. Writes nothing.
    """
    new = pd.read_csv(io.StringIO(df.to_csv(index=False, float_format=float_format)), dtype=str,
                      keep_default_na=False)
    old = pd.read_csv(path, dtype=str, keep_default_na=False)
    m = new.merge(old, on=keys, how="left", suffixes=("", "@published"), indicator=True)
    for _, r in m.iterrows():
        who = " ".join(str(r[k]) for k in keys)
        if r["_merge"] != "both":
            print(f"{who}: no published row")
            continue
        same, diffs = 0, []
        for col in new.columns.drop(keys):
            a, b = r[col], r[f"{col}@published"]
            if a == b:
                same += 1
                continue
            try:
                x, y = float(a), float(b)
                diffs.append(f"{col} {a} vs {b}" + (f" (relative {abs(x - y) / abs(y):.1e})" if y else ""))
            except ValueError:
                diffs.append(f"{col} {a!r} vs {b!r}")
        print(f"{who}: {same} of {len(new.columns) - len(keys)} cells equal"
              + ("; differ: " + "; ".join(diffs) if diffs else ""))


def run_one(job):
    """Run one input in its own folder and return its row of the run log.

    job = (case, variant, configuration, idf, epw, folder[, extra environment]). The extra
    environment is added to that of the configuration (pass_limit_share.py adds SURFACE_AIR_LOG).
    """
    case, variant, configuration, idf, epw, d = job[:6]
    extra = job[6] if len(job) > 6 else {}
    install, env = C.program(configuration)
    d = Path(d)
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copy(idf, d / "in.idf")
    args = [str(install / "energyplus"), "-w", str(epw), "-d", str(d)]
    if re.search(r"^\s*HVACTemplate:", (d / "in.idf").read_text(errors="replace"), re.M | re.I):
        args.append("-x")  # expand HVACTemplate objects first
    t0 = time.time()
    p = subprocess.run(args + ["in.idf"], cwd=d, env=C.run_environment(env | extra),
                       capture_output=True, text=True)
    wall = time.time() - t0
    err = (d / "eplusout.err").read_text(errors="replace") if (d / "eplusout.err").exists() else ""
    row = {"case": case, "variant": variant, "configuration": configuration, "returncode": p.returncode,
           "completed": "EnergyPlus Completed Successfully" in err,
           "fatal": "**  Fatal  **" in err or "Terminated--Fatal" in err,
           "n_warning": len(re.findall(r"\*\* Warning \*\*", err)),
           "n_severe": len(re.findall(r"\*\* Severe  \*\*", err)),
           "wall_s_parallel": round(wall, 1)}  # runs share the machine; not a runtime measurement
    # The patched program writes one pass-statistics line per environment. The annual values are
    # those of the weather-file run period, the last environment with timesteps that is neither a
    # sizing period nor a design day. The release writes no such line, so these stay empty.
    stats = [m for m in C.PASS_STATISTICS.finditer(err) if int(m.group(2)) > 0]
    annual = [m for m in stats if "SIZING" not in m.group(1).upper() and " DB" not in m.group(1)]
    m = annual[-1] if annual else None
    row |= {"run_env": m.group(1) if m else "", "timesteps": int(m.group(2)) if m else None,
            "mean_passes": float(m.group(3)) if m else None, "max_passes": int(m.group(4)) if m else None,
            # timesteps that ended at the pass limit without meeting the tolerance
            "not_converged": int(m.group(5)) if m else None,
            # design-day and sizing environments in which the passes ran
            "sizing_envs_with_passes": sum(1 for x in stats if x not in annual)}
    return row


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", nargs="*", help="run only these cases (e.g. RetailStandalone_Denver)")
    ap.add_argument("--configurations", nargs="*", default=PAPER_CONFIGURATIONS,
                    choices=PAPER_CONFIGURATIONS, help="default: all four")
    ap.add_argument("--workers", type=int, default=os.cpu_count(), help="parallel runs")
    ap.add_argument("--runs", type=folder, default=DEFAULT_RUNS, help="folder for raw runs")
    a = ap.parse_args()
    src = pd.read_csv(RESULTS / "sources.csv")
    if a.cases:
        src = src[src.case.isin(a.cases)]
    jobs = []
    for r in src.itertuples():
        epw = WEATHER / r.weather
        variants = ["base"] + (["window"] if r.window_savings_eligible else [])
        for v in variants:
            for conf in a.configurations:
                jobs.append((r.case, v, conf, INPUTS / f"{r.case}_{v}.idf", epw,
                             a.runs / "prototype_cases" / r.case / f"{v}_{conf}"))
    # Longest first (the converged configuration, then the large buildings), so the end of the
    # batch is not one long run on an otherwise idle machine.
    big = ("Hospital", "HotelLarge", "OfficeLarge", "OutPatientHealthCare", "SchoolSecondary")
    jobs.sort(key=lambda j: (j[2] != "converged", not j[0].startswith(big)))
    print(f"{len(jobs)} runs, started {time.strftime('%H:%M %Z')}", flush=True)
    rows = []
    with ProcessPoolExecutor(min(a.workers, len(jobs))) as ex:
        futs = [ex.submit(run_one, j) for j in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            rows.append(f.result())
            if i % 20 == 0 or i == len(jobs):
                print(f"{time.strftime('%H:%M')} {i}/{len(jobs)} done", flush=True)
    df = pd.DataFrame(rows).sort_values(["case", "variant", "configuration"], key=sort_key)
    path = RESULTS / "case_runs.csv"
    if a.cases or set(a.configurations) != set(PAPER_CONFIGURATIONS):  # keep the other rows
        old = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=df.columns)
        key = ["case", "variant", "configuration"]
        old = old.merge(df[key], on=key, how="left", indicator=True)
        old = old[old._merge == "left_only"].drop(columns="_merge")
        df = pd.concat([old, df]).sort_values(key, key=sort_key)
    df.to_csv(path, index=False)
    bad = df[~df.completed.astype(bool)]
    print(f"completed {int(df.completed.astype(bool).sum())}/{len(df)}; not completed:",
          bad[["case", "variant", "configuration"]].values.tolist())


if __name__ == "__main__":
    main()
