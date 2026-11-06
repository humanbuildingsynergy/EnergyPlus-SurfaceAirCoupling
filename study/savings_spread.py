"""Window-upgrade savings of each prototype case against the spread of the savings among the
three corrected configurations (one pass, two passes, converged), which differ only in how far the
surfaces and air are solved to agreement.

Per eligible case: the savings (site energy of the base input minus that of the window input,
in GJ) with each configuration, the change from the release to two passes, and the spread
(largest minus smallest) among the corrected configurations. A change from the release to two
passes that exceeds this spread, with all three corrected configurations on the same side of the
release, is larger than what the depth of the correction alone moves.
The site totals are read from each run's tabular output (0.01 GJ), because case_metrics.csv keeps
six significant digits, too few for differences of about 1 GJ in totals of 10,000 GJ. The savings
of the release and of two passes are checked against case_deltas.csv.
Reads results/prototypes/case_deltas.csv and the runs in <runs>/prototype_cases/. Writes
results/prototypes/window_savings_spread.csv.

Usage (repository root): python3 study/savings_spread.py [--runs DIR]
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analyze_cases as A  # noqa: E402
import run_cases as RC  # noqa: E402

CONFIGS = ("release", "one_pass", "two_passes", "converged")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--runs", type=RC.folder, default=RC.DEFAULT_RUNS, help="folder of the raw runs")
    a = ap.parse_args()
    d = pd.read_csv(RC.RESULTS / "case_deltas.csv")
    rows = []
    for case in d[(d.configuration == "two_passes") & d.window_savings_eligible].case:
        site = {(v, c): A.run_metrics(a.runs / "prototype_cases" / case / f"{v}_{c}")["site_GJ"]
                for v in ("base", "window") for c in CONFIGS}
        s = pd.Series({c: site[("base", c)] - site[("window", c)] for c in CONFIGS})
        corrected = s[["one_pass", "two_passes", "converged"]]
        rows.append({"case": case, "site_release_GJ": site[("base", "release")],
                     "savings_release_GJ": s["release"], "savings_two_passes_GJ": s["two_passes"],
                     "savings_release_share_of_site": s["release"] / site[("base", "release")],
                     "change_release_to_two_passes_GJ": s["two_passes"] - s["release"],
                     "corrected_spread_GJ": corrected.max() - corrected.min(),
                     "change_exceeds_spread": abs(s["two_passes"] - s["release"]) > corrected.max() - corrected.min(),
                     "corrected_same_side_of_release": bool((np.sign(corrected - s["release"])
                                                             == np.sign(s["two_passes"] - s["release"])).all()),
                     "window_savings_material_two_passes":
                         bool(d[(d.case == case) & (d.configuration == "two_passes")].window_savings_material.iloc[0])})
    n = pd.DataFrame(rows).sort_values("savings_release_share_of_site")
    n.to_csv(RC.RESULTS / "window_savings_spread.csv", index=False, float_format="%.6g")

    new = n.set_index("case")
    two = d[d.configuration == "two_passes"].set_index("case")
    assert np.allclose(new.savings_release_GJ, two.loc[new.index, "savings_release_GJ"], atol=1e-6)
    assert np.allclose(new.savings_two_passes_GJ, two.loc[new.index, "savings_corrected_GJ"], atol=1e-6)
    mat = n[n.window_savings_material_two_passes]
    both = mat.change_exceeds_spread & mat.corrected_same_side_of_release
    print(f"window savings material with two passes: {len(mat)}; change exceeds the spread among the "
          f"corrected configurations in {int(mat.change_exceeds_spread.sum())}; all three corrected "
          f"configurations on the same side of the release in "
          f"{int(mat.corrected_same_side_of_release.sum())}; both in {int(both.sum())}")


if __name__ == "__main__":
    main()
