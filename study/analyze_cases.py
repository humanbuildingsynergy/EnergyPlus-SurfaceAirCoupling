"""Outcomes of the prototype study, the change from the release in each case, and the counts of
cases that change materially, from the runs of study/run_cases.py.

Outcomes per run (definitions fixed before the study; docs/analysis_plan.md):
  energy               annual site energy from the End Uses table [GJ]: heating = Heating,
                       electricity + natural gas; cooling = Cooling, electricity + natural gas;
                       fans = Fans, electricity; site = Total Site Energy. An end use counts in a
                       case when the release's value is at least 5% of the release's site energy.
  peak_demand          annual peak electric demand [W]: Demand End Use Components Summary,
                       Total End Uses, Electricity.
  unmet_hours          occupied unmet hours of the facility [h]: System Summary, Time Setpoint
                       Not Met, During Occupied Heating and During Occupied Cooling.
  autosized_capacities from the Component Sizing Information lines of eplusout.eio: "Design
                       Size" values only, none for a component and quantity that also has a
                       "User-Specified" value. Per component the largest value counts once
                       (multi-speed coils report one value per speed). Cooling = Coil:Cooling:*
                       total cooling capacity or design coil load [W]; heating = Coil:Heating:*
                       capacity [W]; supply fan flow = Fan:* except Fan:ZoneExhaust, maximum flow
                       rate [m3/s]. Summed per building.
  window_savings       site energy of the base input minus that of the window input [GJ].
Reads results/prototypes/case_runs.csv and the runs in <runs>/prototype_cases/. Writes, in
results/prototypes/: case_metrics.csv (one row per case, variant and configuration),
case_deltas.csv (each corrected configuration against the release, per case, with the
materiality flags) and outcome_counts.csv (eligible and material cases per outcome and
configuration; "supported" = material in at least a quarter of the eligible cases).

Usage (repository root):
  python3 study/analyze_cases.py [--runs DIR]
  python3 study/analyze_cases.py --cases CASE ... [--configurations ...]   (check part of the runs)
With --cases or --configurations, the outcomes of those runs are compared with the published
rows of case_metrics.csv and nothing is written.
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_cases as RC  # noqa: E402

SIZE = re.compile(r"^ Component Sizing Information, ([^,]+), (.+), ([^,]+), ([-\d.Ee+]+)\s*$")
COOL = re.compile(r"(Total Cooling Capacity|Design Coil Load).*\[W\]", re.I)
HEAT = re.compile(r"(Capacity).*\[W\]", re.I)
FAN = re.compile(r"Maximum (Air )?Flow Rate.*\[m3/s\]", re.I)
END_USES = ("heating", "cooling", "fans")
CORRECTED = ("one_pass", "two_passes", "converged")


def tab(con, report, table, row, col):
    """One value of a tabular report for the entire facility (0 when blank or absent)."""
    q = """SELECT Value FROM TabularDataWithStrings WHERE ReportName=? AND TableName=? AND RowName=?
           AND ColumnName=? AND ReportForString='Entire Facility'"""
    r = con.execute(q, (report, table, row, col)).fetchone()
    return float(r[0]) if r and r[0].strip() else 0.0


def sizing_lines(d):
    """(object type, name, description, value) of every Component Sizing Information line."""
    out = []
    for line in (Path(d) / "eplusout.eio").read_text(errors="replace").splitlines():
        m = SIZE.match(line)
        if m:
            out.append((m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), float(m.group(4))))
    return out


def quantity(ctype, desc):
    if ctype.upper().startswith("COIL:COOLING") and COOL.search(desc):
        return "cool_cap_W"
    if ctype.upper().startswith("COIL:HEATING") and HEAT.search(desc):
        return "heat_cap_W"
    if ctype.upper().startswith("FAN:") and ctype.upper() != "FAN:ZONEEXHAUST" and FAN.search(desc):
        return "fan_flow_m3s"
    return None


def capacities(d):
    lines = sizing_lines(d)
    # A component and quantity with a User-Specified value is hard-sized: its Design Size value is
    # reported but not used, so it is left out.
    hard = {(t.upper(), n.upper(), quantity(t, desc)) for t, n, desc, _ in lines
            if desc.startswith("User-Specified") and quantity(t, desc)}
    per = {}
    for t, n, desc, v in lines:
        q = quantity(t, desc)
        if q and desc.startswith("Design Size") and (t.upper(), n.upper(), q) not in hard:
            k = (t.upper(), n.upper(), q)
            per[k] = max(per.get(k, -np.inf), v)
    out = {"cool_cap_W": 0.0, "heat_cap_W": 0.0, "fan_flow_m3s": 0.0}
    for (_, _, q), v in per.items():
        out[q] += v
    out["n_sized_components"] = len(per)
    return out


def run_metrics(d):
    """Annual outcomes of one run folder (units in the column names)."""
    d = Path(d)
    con = sqlite3.connect(d / "eplusout.sql")
    B, E = "AnnualBuildingUtilityPerformanceSummary", "End Uses"
    m = {"heating_GJ": tab(con, B, E, "Heating", "Electricity") + tab(con, B, E, "Heating", "Natural Gas"),
         "cooling_GJ": tab(con, B, E, "Cooling", "Electricity") + tab(con, B, E, "Cooling", "Natural Gas"),
         "fans_GJ": tab(con, B, E, "Fans", "Electricity"),
         "site_GJ": tab(con, B, "Site and Source Energy", "Total Site Energy", "Total Energy"),
         "peak_elec_W": tab(con, "DemandEndUseComponentsSummary", E, "Total End Uses", "Electricity"),
         "unmet_heat_occ_h": tab(con, "SystemSummary", "Time Setpoint Not Met", "Facility",
                                 "During Occupied Heating"),
         "unmet_cool_occ_h": tab(con, "SystemSummary", "Time Setpoint Not Met", "Facility",
                                 "During Occupied Cooling")}
    con.close()
    return m | capacities(d)


def pct(x, r):
    """Percent change of x against the reference r."""
    return 100 * (x / r - 1) if r else (0.0 if x == r else np.inf)


def unmet_material(r, f):
    """Unmet hours of heating or of cooling: a change of at least 10% of the release and 5 h."""
    rel = abs(f - r) >= 0.10 * r and abs(f - r) >= 5
    return bool(rel)


def metrics_table(runs, root):
    rows = []
    for r in runs.itertuples():
        row = {"case": r.case, "variant": r.variant, "configuration": r.configuration,
               "completed": bool(r.completed), "fatal": bool(r.fatal), "n_warning": r.n_warning,
               "n_severe": r.n_severe, "mean_passes": r.mean_passes, "not_converged": r.not_converged,
               "sizing_envs_with_passes": r.sizing_envs_with_passes}
        if r.completed:
            row |= run_metrics(root / r.case / f"{r.variant}_{r.configuration}")
        rows.append(row)
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--cases", nargs="*", help="check only these cases against case_metrics.csv")
    ap.add_argument("--configurations", nargs="*", choices=RC.PAPER_CONFIGURATIONS,
                    help="check only these configurations against case_metrics.csv")
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder of the raw runs")
    a = ap.parse_args()
    runs = pd.read_csv(RC.RESULTS / "case_runs.csv")
    root = a.runs / "prototype_cases"

    if a.cases or a.configurations:
        if a.cases:
            runs = runs[runs.case.isin(a.cases)]
        if a.configurations:
            runs = runs[runs.configuration.isin(a.configurations)]
        RC.compare_with_published(metrics_table(runs, root), RC.RESULTS / "case_metrics.csv",
                                  ["case", "variant", "configuration"], "%.6g")
        return

    met = metrics_table(runs, root)
    met.to_csv(RC.RESULTS / "case_metrics.csv", index=False, float_format="%.6g")

    k = met.set_index(["case", "variant", "configuration"])
    # A case where the release ends in a fatal error is excluded (the small office).
    excluded = sorted(c for c in met.case.unique() if not k.loc[(c, "base", "release"), "completed"])
    pass_limit = {c for c in met.case.unique()
                  if (c, "base", "converged") in k.index
                  and (k.loc[(c, "base", "converged"), "not_converged"] or 0) > 0}
    deltas = []
    for case in sorted(set(met.case) - set(excluded)):
        R = k.loc[(case, "base", "release")]
        for conf in CORRECTED:
            F = k.loc[(case, "base", conf)]
            row = {"case": case, "configuration": conf, "corrected_completed": bool(F.completed),
                   "converged_reached_pass_limit": case in pass_limit}
            if not F.completed:
                deltas.append(row)
                continue
            for eu in END_USES:
                row[f"{eu}_share_release"] = R[f"{eu}_GJ"] / R.site_GJ
                row[f"{eu}_eligible"] = row[f"{eu}_share_release"] >= 0.05
                row[f"{eu}_pct"] = pct(F[f"{eu}_GJ"], R[f"{eu}_GJ"])
                row[f"{eu}_material"] = bool(row[f"{eu}_eligible"] and abs(row[f"{eu}_pct"]) >= 1)
            row["site_pct"] = pct(F.site_GJ, R.site_GJ)
            row["energy_material"] = any(row[f"{eu}_material"] for eu in END_USES)
            row["energy_eligible"] = any(row[f"{eu}_eligible"] for eu in END_USES)
            row["peak_pct"] = pct(F.peak_elec_W, R.peak_elec_W)
            row["peak_demand_material"] = abs(row["peak_pct"]) >= 2
            for u in ("heat", "cool"):
                row[f"unmet_{u}_release"] = R[f"unmet_{u}_occ_h"]
                row[f"unmet_{u}_corrected"] = F[f"unmet_{u}_occ_h"]
            tot_r = R.unmet_heat_occ_h + R.unmet_cool_occ_h
            tot_f = F.unmet_heat_occ_h + F.unmet_cool_occ_h
            # 300 h: the limit on the total in the performance rating method of Standard 90.1
            row["unmet_hours_material"] = (unmet_material(R.unmet_heat_occ_h, F.unmet_heat_occ_h)
                                           or unmet_material(R.unmet_cool_occ_h, F.unmet_cool_occ_h)
                                           or ((tot_r > 300) != (tot_f > 300)))
            caps = []
            for q in ("cool_cap_W", "heat_cap_W", "fan_flow_m3s"):
                row[f"{q}_pct"] = pct(F[q], R[q]) if R[q] > 0 else np.nan
                if R[q] > 0:
                    caps.append(abs(row[f"{q}_pct"]) >= 2)
            row["autosized_capacities_eligible"] = bool(caps)
            row["autosized_capacities_material"] = any(caps)
            if (case, "window", "release") in k.index and (case, "window", conf) in k.index:
                Rw, Fw = k.loc[(case, "window", "release")], k.loc[(case, "window", conf)]
                if Rw.completed and Fw.completed:
                    s_r, s_f = R.site_GJ - Rw.site_GJ, F.site_GJ - Fw.site_GJ
                    row["savings_release_GJ"], row["savings_corrected_GJ"] = s_r, s_f
                    row["savings_pct"] = pct(s_f, s_r)
                    row["window_savings_eligible"] = True
                    row["window_savings_material"] = bool(abs(row["savings_pct"]) >= 10
                                                          or np.sign(s_f) != np.sign(s_r))
            row.setdefault("window_savings_eligible", False)
            row["mean_passes"] = F.mean_passes
            row["converged_timesteps_at_pass_limit"] = (k.loc[(case, "base", "converged"), "not_converged"]
                                                        if conf == "converged" else np.nan)
            deltas.append(row)
    dl = pd.DataFrame(deltas)
    dl.to_csv(RC.RESULTS / "case_deltas.csv", index=False, float_format="%.5g")

    # Cases that change materially. Two passes is the primary configuration. A case enters an
    # outcome's count only where both the release and the configuration completed.
    counts = []
    for conf in ("two_passes", "one_pass", "converged"):
        g = dl[(dl.configuration == conf) & dl.corrected_completed]
        for outcome, elig in (("energy", "energy_eligible"), ("peak_demand", None), ("unmet_hours", None),
                              ("autosized_capacities", "autosized_capacities_eligible"),
                              ("window_savings", "window_savings_eligible")):
            e = g[g[elig].astype(bool)] if elig else g
            n, nm = len(e), int(e[f"{outcome}_material"].astype(bool).sum())
            counts.append({"configuration": conf, "outcome": outcome, "eligible_cases": n,
                           "material_cases": nm, "share": nm / n if n else np.nan,
                           "supported": bool(n and nm / n >= 0.25)})
    oc = pd.DataFrame(counts)
    oc.to_csv(RC.RESULTS / "outcome_counts.csv", index=False, float_format="%.3g")
    print("excluded (release ends in a fatal error):", excluded)
    print("corrected configuration failed:",
          dl.loc[~dl.corrected_completed, ["case", "configuration"]].values.tolist())
    print("converged configuration reached its pass limit:", sorted(pass_limit))
    print(oc.to_string(index=False))


if __name__ == "__main__":
    main()
