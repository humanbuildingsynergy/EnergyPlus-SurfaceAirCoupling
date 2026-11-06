"""Two descriptions of the prototype study that read only its results tables.

1. How often the converged configuration ended a timestep at its limit of 50 passes, per case.
2. The three cases with the largest change in an eligible end use from the release to two passes,
   which study/locate_changes.py breaks down by month, hour and component.
Reads results/prototypes/case_metrics.csv and case_deltas.csv. Writes, in results/prototypes/,
converged_pass_limit.csv (case, mean extra passes, timesteps at the pass limit, their share of the
year) and largest_changes.csv (case, end use, absolute change in percent).

Usage (repository root): python3 study/describe_cases.py
"""
import argparse
from pathlib import Path

import pandas as pd

RESULTS = Path(__file__).resolve().parents[1] / "results" / "prototypes"
END_USES = ("heating", "cooling", "fans")


def main():
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args()
    m = pd.read_csv(RESULTS / "case_metrics.csv")
    d = pd.read_csv(RESULTS / "case_deltas.csv")

    conv = m[(m.configuration == "converged") & (m.variant == "base") & m.completed][
        ["case", "mean_passes", "not_converged"]]
    # Every prototype file runs at 6 timesteps per hour (sources.csv), 8760 x 6 timesteps a year.
    conv = conv.assign(share_of_timesteps=conv.not_converged / (8760 * 6))
    conv.to_csv(RESULTS / "converged_pass_limit.csv", index=False, float_format="%.4g")
    print(f"converged configuration, timesteps at the 50-pass limit: median "
          f"{conv.not_converged.median():.0f}, max {conv.not_converged.max():.0f} "
          f"(share {conv.share_of_timesteps.max():.4f}); mean extra passes, median "
          f"{conv.mean_passes.median():.2f}")

    two = d[d.configuration == "two_passes"].copy()

    def top_end_use(r):
        """The eligible end use (at least 5% of site energy) with the largest absolute change."""
        el = [e for e in END_USES if r[f"{e}_eligible"]]
        return max(el, key=lambda e: abs(r[f"{e}_pct"])) if el else ""

    two["end_use"] = two.apply(top_end_use, axis=1)
    two["max_eligible_abs_pct"] = two.apply(lambda r: abs(r[f"{r.end_use}_pct"]) if r.end_use else 0.0,
                                            axis=1)
    top = two.nlargest(3, "max_eligible_abs_pct")[["case", "end_use", "max_eligible_abs_pct"]]
    top.to_csv(RESULTS / "largest_changes.csv", index=False, float_format="%.4g")
    print("\nlargest change in an eligible end use, two passes against the release:\n",
          top.to_string(index=False))


if __name__ == "__main__":
    main()
