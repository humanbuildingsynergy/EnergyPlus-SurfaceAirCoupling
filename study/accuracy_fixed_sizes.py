"""Accuracy against timestep in the three Denver buildings of accuracy_runtime.py, with the
equipment sizes fixed, so that no run sizes its equipment at its own timestep.

Sizes: those of the study's release run at 6 per hour (<runs>/prototype_cases/<case>/base_release).
Every field of the study input whose value is Autosize is replaced by the value of the eplusout.eio
"Component Sizing Information" line of the same object type and name whose description, without
"Design Size" and the unit, equals the field name (the IDF field comment without the unit; ALIAS
maps the two names that differ). Autosize fields with no such line are left as they are and listed
in accuracy_fixed_sizes_unmatched.csv; EnergyPlus does not size fields it does not use, such as
the hot-water flow of a terminal with electric reheat. Each hard-sized input is then changed only
in its timestep and by one hourly output, Zone Mean Air Temperature (as in accuracy_runtime.py).
Runs: release, two passes and converged at 4, 6, 10, 20 and 30 per hour, and converged at 60 per
hour, in parallel (no wall times are used).
Checks: the hard-sized release run at 6 per hour against the autosized study run (annual heating,
cooling and site energy; the capacity columns read -100% because a hard-sized run reports no
"Design Size" values), and, for every run, the number of sizes used (the User-Specified value,
else the Design Size value, per component and quantity) that differ from those of the hard-sized
release run at 6 per hour.
Errors: RMS difference of hourly zone mean air temperature over the conditioned zones against the
converged configuration at 30 and at 60 per hour (hard-sized), and the percent change of annual
heating and cooling energy against each; timesteps at the pass limit for every run.
Inputs written to <PROTOTYPES>/accuracy_fixed_sizes/. Raw runs:
<runs>/accuracy_fixed_sizes/<case>/<configuration>_tsNN/. Writes, in results/prototypes/:
accuracy_fixed_sizes_unmatched.csv, accuracy_fixed_sizes_runs.csv, accuracy_fixed_sizes_check.csv
and accuracy_fixed_sizes.csv.

Usage (repository root):
  python3 study/accuracy_fixed_sizes.py prepare [--cases ...]
  python3 study/accuracy_fixed_sizes.py run [--cases ...] [--configurations ...] [--timesteps ...]
  python3 study/accuracy_fixed_sizes.py analyze [--cases ...]
With a subset, "prepare" and "run" replace only those rows, and "analyze" compares the check rows
of the chosen cases with accuracy_fixed_sizes_check.csv (and the error rows, when the converged
reference runs exist) with the published files and writes nothing.
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
import accuracy_runtime as AR  # noqa: E402
import analyze_cases as A  # noqa: E402
import run_cases as RC  # noqa: E402

BUILDINGS = AR.BUILDINGS
STEPS = [4, 6, 10, 20, 30]
JOBS = [(conf, ts) for conf in ("release", "two_passes", "converged") for ts in STEPS] + [("converged", 60)]
INPUTS = RC.C.PROTOTYPES / "accuracy_fixed_sizes"
# Fields whose .eio description differs from the IDF field name.
ALIAS = {("AIRTERMINAL:SINGLEDUCT:VAV:REHEAT", "maximum hot water or steam flow rate"): "maximum reheat water flow rate",
         ("PUMP:VARIABLESPEED", "design maximum flow rate"): "design flow rate"}
LINE = re.compile(r"^ Component Sizing Information, ([^,]+), (.+), ([^,]+), ([-\d.Ee+]+)\s*$")


def norm(s):
    """Field name or sizing description without units, "Design Size" and case."""
    s = re.sub(r"\[.*?\]|\{.*?\}", "", s)
    s = re.sub(r"^\s*design size\s+", "", s, flags=re.I)
    return re.sub(r"\s+", " ", s).strip().lower()


def sized_values(case, runs):
    """Value text of every autosized quantity of the study's release run at 6 per hour."""
    vals = {}
    eio = runs / "prototype_cases" / case / "base_release" / "eplusout.eio"
    for line in eio.read_text(errors="replace").splitlines():
        m = LINE.match(line)
        if m and not m.group(3).strip().startswith("User-Specified"):
            vals[(m.group(1).strip().upper(), m.group(2).strip().upper(), norm(m.group(3)))] = m.group(4)
    return vals


def hard_size(case, runs):
    """Return (input text with Autosize replaced, replaced fields, unmatched fields)."""
    vals = sized_values(case, runs)
    out, done, miss = [], [], []
    otype, name, nfield = None, None, 0
    # Walk the IDF line by line, one field per line as the prototype files are written: an object
    # starts with "Type," on its own line and ends at the field that ends with ";".
    for line in (RC.INPUTS / f"{case}_base.idf").read_text(errors="replace").splitlines(keepends=True):
        code = line.split("!")[0]
        if otype is None:
            m = re.match(r"^\s*([A-Za-z][\w:\-]*)\s*,\s*$", code)
            if m:
                otype, name, nfield = m.group(1), None, 0
            out.append(line)
            continue
        fm = re.match(r"^(\s*)([^,;]*?)(\s*)([,;])", code)
        if fm:
            nfield += 1
            value = fm.group(2).strip()
            if nfield == 1:
                name = value
            comment = line.split("!-", 1)[1].strip() if "!-" in line else ""
            if value.lower() == "autosize":
                f = norm(comment)
                f = ALIAS.get((otype.upper(), f), f)
                key = (otype.upper(), (name or "").upper(), f)
                if key in vals:
                    line = line.replace(fm.group(2), vals[key], 1)
                    done.append({"case": case, "type": otype, "name": name, "field": comment, "value": vals[key]})
                else:
                    miss.append({"case": case, "type": otype, "name": name, "field": comment})
            if fm.group(4) == ";":
                otype = None
        out.append(line)
    return "".join(out), done, miss


def make_idf(text, ts):
    n = len(re.findall(r"^\s*Timestep,\s*\d+\s*;", text, re.M | re.I))
    if n != 1:
        sys.exit(f"{n} Timestep objects")
    text = re.sub(r"^(\s*Timestep,\s*)\d+(\s*;)", rf"\g<1>{ts}\2", text, flags=re.M | re.I)
    return text + "\n  Output:Variable,*,Zone Mean Air Temperature,Hourly;\n"


def cmd_prepare(a):
    INPUTS.mkdir(parents=True, exist_ok=True)
    done, miss = [], []
    for c in a.cases:
        t, d, m = hard_size(c, a.runs)
        (INPUTS / f"{c}_hardsized.idf").write_text(t)
        done += d
        miss += m
        left = len(re.findall(r"^\s*autosize\s*[,;]", t, re.M | re.I))
        print(f"{c}: {len(d)} fields hard-sized, {len(m)} unmatched, {left} Autosize left")
    path = RC.RESULTS / "accuracy_fixed_sizes_unmatched.csv"
    df = pd.DataFrame(miss)
    if set(a.cases) != set(BUILDINGS) and path.exists():  # keep the other buildings' rows
        old = pd.read_csv(path)
        df = pd.concat([old[~old.case.isin(a.cases)], df])
    df.to_csv(path, index=False)
    pd.DataFrame(done).to_csv(INPUTS / "hardsized_fields.csv", index=False)  # every replaced field
    if miss:
        print(pd.DataFrame(miss).groupby(["type", "field"]).size().to_string())


def job(j):
    c, conf, ts, runs = j
    idf = INPUTS / f"{c}_ts{ts:02d}.idf"
    idf.write_text(make_idf((INPUTS / f"{c}_hardsized.idf").read_text(), ts))
    return RC.run_one((c, f"ts{ts:02d}", conf, idf, AR.EPW,
                       runs / "accuracy_fixed_sizes" / c / f"{conf}_ts{ts:02d}")) | {"ts": ts}


def cmd_run(a):
    jobs = [(c, conf, ts, a.runs) for c in a.cases for conf, ts in JOBS
            if conf in a.configurations and ts in a.timesteps]
    # Longest first: runtime grows with the timesteps per hour, and the converged configuration
    # takes several times as long as the others.
    jobs.sort(key=lambda j: (-(j[2] * (5 if j[1] == "converged" else 1))))
    print(f"{len(jobs)} runs, started {time.strftime('%H:%M %Z')}", flush=True)
    rows = []
    with ProcessPoolExecutor(min(a.workers, len(jobs))) as ex:
        for i, f in enumerate(as_completed([ex.submit(job, j) for j in jobs]), 1):
            r = f.result()
            rows.append(r)
            print(f"{time.strftime('%H:%M')} {i}/{len(jobs)} {r['case']} {r['configuration']} {r['ts']}/h "
                  f"completed={r['completed']} not_converged={r['not_converged']}", flush=True)
    df = pd.DataFrame(rows).drop(columns="variant")
    key = ["case", "configuration", "ts"]
    path = RC.RESULTS / "accuracy_fixed_sizes_runs.csv"
    if len(jobs) < len(BUILDINGS) * len(JOBS) and path.exists():  # keep the rows not rerun
        old = pd.read_csv(path).merge(df[key], on=key, how="left", indicator=True)
        df = pd.concat([old[old._merge == "left_only"].drop(columns="_merge"), df])
    df.sort_values(key, key=RC.sort_key).to_csv(path, index=False)


def used_sizes(d):
    """Size used per component and quantity: the User-Specified value where there is one, else the
    Design Size value (quantities derived from hard-sized fields, such as a terminal's minimum flow)."""
    lines = A.sizing_lines(d)
    used = {(t.upper(), n.upper(), norm(desc.replace("User-Specified", ""))): v
            for t, n, desc, v in lines if desc.startswith("User-Specified")}
    for t, n, desc, v in lines:
        k = (t.upper(), n.upper(), norm(desc))
        if desc.startswith("Design Size") and k not in used:
            used[k] = v
    return used


def sizes_differing(d, ref):
    u = used_sizes(d)
    return sum(1 for k in set(u) | set(ref) if u.get(k) != ref.get(k))


def cmd_analyze(a):
    root = a.runs / "accuracy_fixed_sizes"
    runs = pd.read_csv(RC.RESULTS / "accuracy_fixed_sizes_runs.csv")
    subset = set(a.cases) != set(BUILDINGS)
    chk, rows = [], []
    for c in a.cases:
        zones = AR.conditioned_zones(c)
        d6 = root / c / "release_ts06"
        auto = A.run_metrics(a.runs / "prototype_cases" / c / "base_release")
        hard = A.run_metrics(d6)
        sizes6 = used_sizes(d6)
        chk.append({"case": c, "check": "release 6/h hard-sized vs autosized study run"}
                   | {f"{k}_pct": A.pct(hard[k], auto[k]) for k in ("heating_GJ", "cooling_GJ", "site_GJ")}
                   | {f"{q}_pct": A.pct(hard[q], auto[q]) if auto[q] else np.nan
                      for q in ("cool_cap_W", "heat_cap_W", "fan_flow_m3s")})
        if subset and not all((root / c / f"converged_ts{ts:02d}" / "eplusout.sql").exists() for ts in (30, 60)):
            continue  # a partial check without the converged reference runs: check rows only
        refs = {}
        for ts in (30, 60):
            d = root / c / f"converged_ts{ts:02d}"
            refs[ts] = (AR.air(d, zones), A.run_metrics(d))
        for r in runs[runs.case == c].itertuples():
            d = root / c / f"{r.configuration}_ts{r.ts:02d}"
            row = {"case": c, "configuration": r.configuration, "ts": r.ts, "completed": r.completed,
                   "not_converged": r.not_converged, "timesteps": r.timesteps, "mean_passes": r.mean_passes,
                   "n_warning": r.n_warning, "n_severe": r.n_severe}
            if r.completed:
                m = A.run_metrics(d)
                a_ = AR.air(d, zones)
                row |= {"heating_GJ": m["heating_GJ"], "cooling_GJ": m["cooling_GJ"], "site_GJ": m["site_GJ"],
                        "sizes_differing_from_release_ts06": sizes_differing(d, sizes6)}
                for ts, (ra, rm) in refs.items():
                    j = pd.concat([a_, ra], axis=1, keys=["x", "ref"]).dropna()
                    row[f"air_rms_vs_converged_ts{ts:02d}_C"] = float(np.sqrt(((j.x - j.ref) ** 2).mean()))
                    row[f"heating_pct_vs_converged_ts{ts:02d}"] = A.pct(m["heating_GJ"], rm["heating_GJ"])
                    row[f"cooling_pct_vs_converged_ts{ts:02d}"] = A.pct(m["cooling_GJ"], rm["cooling_GJ"])
            rows.append(row)
    chk, df = pd.DataFrame(chk), pd.DataFrame(rows)
    if subset:
        RC.compare_with_published(chk, RC.RESULTS / "accuracy_fixed_sizes_check.csv", ["case"], "%.6g")
        if len(df):
            RC.compare_with_published(df, RC.RESULTS / "accuracy_fixed_sizes.csv",
                                      ["case", "configuration", "ts"], "%.6g")
        return
    chk.to_csv(RC.RESULTS / "accuracy_fixed_sizes_check.csv", index=False, float_format="%.6g")
    df.to_csv(RC.RESULTS / "accuracy_fixed_sizes.csv", index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    print(chk.to_string(index=False))
    print(df[["case", "configuration", "ts", "not_converged", "sizes_differing_from_release_ts06",
              "air_rms_vs_converged_ts30_C", "air_rms_vs_converged_ts60_C", "heating_pct_vs_converged_ts60",
              "cooling_pct_vs_converged_ts60"]].to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("phase", choices=["prepare", "run", "analyze"])
    ap.add_argument("--cases", nargs="*", default=BUILDINGS, choices=BUILDINGS)
    ap.add_argument("--configurations", nargs="*", default=["release", "two_passes", "converged"],
                    choices=["release", "two_passes", "converged"], help="run phase only")
    ap.add_argument("--timesteps", nargs="*", type=int, default=STEPS + [60], choices=STEPS + [60],
                    help="run phase only")
    ap.add_argument("--workers", type=int, default=os.cpu_count(), help="parallel runs")
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder of the raw runs")
    a = ap.parse_args()
    {"prepare": cmd_prepare, "run": cmd_run, "analyze": cmd_analyze}[a.phase](a)


if __name__ == "__main__":
    main()
