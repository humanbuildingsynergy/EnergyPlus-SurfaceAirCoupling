"""Direction of the changes from the release to two passes across the prototype cases: one
Wilcoxon signed-rank test per outcome, used descriptively after the verdicts.

For each outcome, the per-case percent change from the release to two passes (case_deltas.csv) is
tested against zero with scipy.stats.wilcoxon (two-sided, default method: exact for these sample
sizes without ties or zeros). Heating, cooling and fan energy use the cases where the end use is at
least 5% of the release's site energy; peak demand and the three autosized capacities use every
case with a value (cooling capacity: cases with autosized cooling coils). Bonferroni correction
over the 7 tests: alpha 0.05 / 7.
Reads results/prototypes/case_deltas.csv. Writes results/prototypes/direction_tests.csv.

Usage (repository root): python3 study/direction_tests.py
"""
import argparse
from pathlib import Path

import pandas as pd
import scipy
from scipy import stats

RESULTS = Path(__file__).resolve().parents[1] / "results" / "prototypes"
# (outcome, column of case_deltas.csv, eligibility column or None for every case with a value)
TESTS = [("heating energy", "heating_pct", "heating_eligible"), ("cooling energy", "cooling_pct", "cooling_eligible"),
         ("fan energy", "fans_pct", "fans_eligible"), ("peak electric demand", "peak_pct", None),
         ("cooling capacity", "cool_cap_W_pct", None), ("heating capacity", "heat_cap_W_pct", None),
         ("supply fan flow", "fan_flow_m3s_pct", None)]
ALPHA = 0.05


def main():
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args()
    d = pd.read_csv(RESULTS / "case_deltas.csv")
    d = d[(d.configuration == "two_passes") & d.corrected_completed]
    rows = []
    for name, col, elig in TESTS:
        x = (d[d[elig].astype(bool)] if elig else d)[col].dropna()
        t = stats.wilcoxon(x)
        rows.append({"quantity": name, "column": col, "cases": len(x), "n_increase": int((x > 0).sum()),
                     "n_decrease": int((x < 0).sum()), "n_zero": int((x == 0).sum()), "median_pct": x.median(),
                     "W": t.statistic, "p": t.pvalue, "bonferroni_alpha": ALPHA / len(TESTS),
                     "significant_bonferroni": bool(t.pvalue < ALPHA / len(TESTS)),
                     "significant_unadjusted": bool(t.pvalue < ALPHA)})
    df = pd.DataFrame(rows)
    df.to_csv(RESULTS / "direction_tests.csv", index=False, float_format="%.4g")
    print(f"scipy {scipy.__version__}")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
