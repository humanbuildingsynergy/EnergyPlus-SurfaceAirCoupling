"""Per-case tables of the prototype study of the paper (its supplementary material).

Reads results/prototypes/case_deltas.csv (one row per case and configuration) and writes
four LaTeX longtables, each with booktabs rules, caption and label, ready for \\input:
  paper/tables/case_energy.tex    change from the release to two passes in annual heating, cooling, fan
                            and site energy
  paper/tables/case_limits.tex    change in peak electric demand and autosized capacity, and the
                            timesteps at the converged configuration's pass limit
  paper/tables/case_unmet.tex     occupied unmet heating and cooling hours, release and two passes
  paper/tables/case_window.tex    site energy savings of the window upgrade, release and two passes
Two passes against the release is the comparison the analysis plan tests. The plan also flags, in
every table, each case whose converged run reached its pass limit; that is every case, so each
table's note says so and refers to case_limits.tex for the counts. The tables set no font size;
the paper sets it. Needs the longtable and booktabs packages.
Usage (repository root): python3 paper/make_case_tables.py
"""
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "results" / "prototypes" / "case_deltas.csv"
OUT = Path(__file__).resolve().parent / "tables"

BUILDINGS = {
    "ApartmentHighRise": "High-rise apartment", "ApartmentMidRise": "Mid-rise apartment",
    "Hospital": "Hospital", "HotelLarge": "Large hotel", "HotelSmall": "Small hotel",
    "OfficeLarge": "Large office", "OfficeMedium": "Medium office",
    "OutPatientHealthCare": "Outpatient health care", "RestaurantFastFood": "Fast-food restaurant",
    "RestaurantSitDown": "Sit-down restaurant", "RetailStandalone": "Standalone retail",
    "RetailStripmall": "Strip mall", "SchoolPrimary": "Primary school",
    "SchoolSecondary": "Secondary school", "Warehouse": "Warehouse",
}
CLIMATES = {"Miami": "1A", "Denver": "5B", "InternationalFalls": "7"}
CITIES = " Climate zones: 1A Miami, 5B Denver, 7 International Falls."
CLIMATE_ORDER = {"Miami": 0, "Denver": 1, "InternationalFalls": 2}


def signed(x, digits=2, eligible=True, bold=False):
    s = f"{x:+.{digits}f}".replace("-", "$-$")
    if not eligible:
        s = f"({s})"
    return f"\\textbf{{{s}}}" if bold else s


def plain(x, digits=1, bold=False):
    s = f"{x:.{digits}f}".replace("-", "$-$")
    return f"\\textbf{{{s}}}" if bold else s


def longtable(colspec, caption, label, header, rows, note):
    """A longtable with booktabs rules and the header repeated on every page; the note follows it
    as a paragraph, so it does not widen the last column."""
    n = colspec.count("l") + colspec.count("r")
    lines = ["{\\setlength{\\tabcolsep}{4pt}\\setlength{\\LTpost}{0pt}",
             f"\\begin{{longtable}}{{{colspec}}}",
             f"  \\caption{{{caption}}}\\label{{{label}}} \\\\",
             "  \\toprule", *[f"  {h} \\\\" for h in header], "  \\midrule", "  \\endfirsthead",
             f"  \\multicolumn{{{n}}}{{@{{}}l}}{{\\emph{{(continued)}}}} \\\\", "  \\toprule",
             *[f"  {h} \\\\" for h in header], "  \\midrule", "  \\endhead",
             "  \\bottomrule", "  \\endfoot", "  \\bottomrule", "  \\endlastfoot"]
    lines += [f"  {r} \\\\" for r in rows]
    lines += ["\\end{longtable}", f"\\noindent {note}{CITIES}\\par\\bigskip", "}"]
    return "\n".join(lines) + "\n"


def main():
    d = pd.read_csv(SRC)
    d[["bldg", "city"]] = d.case.str.split("_", n=1, expand=True)
    d = d.assign(order=d.city.map(CLIMATE_ORDER)).sort_values(["bldg", "order"])
    two = d[d.configuration == "two_passes"].set_index("case", drop=False)
    conv = d[d.configuration == "converged"].set_index("case")
    assert len(two) == 45 and len(conv) == 45, (len(two), len(conv))

    def who(r):
        return f"{BUILDINGS[r.bldg]} & {CLIMATES[r.city]}"

    # The analysis plan flags every case whose converged run has timesteps at the pass limit, in
    # every table. That is every case, so each table says so; the counts are in case_limits.tex.
    flag = (" Every case has timesteps in which the converged configuration reached its limit of 50"
            " passes (Table~\\ref{tab:case-limits}).")

    rows = []
    for _, r in two.iterrows():
        rows.append(" & ".join([
            who(r),
            signed(r.heating_pct, eligible=r.heating_eligible, bold=r.heating_material),
            signed(r.cooling_pct, eligible=r.cooling_eligible, bold=r.cooling_material),
            signed(r.fans_pct, eligible=r.fans_eligible, bold=r.fans_material),
            signed(r.site_pct),
        ]))
    energy = longtable(
        "@{}llrrrr@{}",
        "Change in annual energy from the release to two passes in each prototype case (\\%).",
        "tab:case-energy",
        ["& Climate & Heating & Cooling & Fan & Site", "Building & zone & energy & energy & energy & energy"],
        rows,
        "Bold: material change (at least 1\\%). Parentheses: end use below 5\\% of the release's "
        "annual site energy, not counted." + flag)

    rows = []
    for c, r in two.iterrows():
        cap = max((r.cool_cap_W_pct, r.heat_cap_W_pct, r.fan_flow_m3s_pct),
                  key=lambda v: abs(v) if pd.notna(v) else -1)
        rows.append(" & ".join([
            who(r),
            signed(r.peak_pct, bold=r.peak_demand_material),
            signed(cap, bold=r.autosized_capacities_material),
            f"{int(conv.loc[c, 'converged_timesteps_at_pass_limit']):,}",
        ]))
    limits = longtable(
        "@{}llrrr@{}",
        "Change in annual peak electric demand and autosized capacity from the release to two passes "
        "(\\%), and timesteps at the pass limit of the converged configuration, in each prototype "
        "case.",
        "tab:case-limits",
        ["& Climate & Peak electric & Autosized & Timesteps at",
         "Building & zone & demand (\\%) & capacity (\\%) & pass limit"],
        rows,
        "Bold: material change (at least 2\\%). Autosized capacity: the largest change among the sums "
        "of cooling coil, heating coil and supply fan capacities. Timesteps at pass limit: timesteps "
        "of the year, out of 52,560, in which the converged configuration reached its limit of 50 "
        "passes.")

    rows = []
    def material(rel, two_):  # the rule of study/analyze_cases.py for unmet hours
        return abs(two_ - rel) >= 0.10 * rel and abs(two_ - rel) >= 5

    for _, r in two.iterrows():
        cross = (r.unmet_heat_release + r.unmet_cool_release > 300) != (r.unmet_heat_corrected + r.unmet_cool_corrected > 300)
        bh = cross or material(r.unmet_heat_release, r.unmet_heat_corrected)
        bc = cross or material(r.unmet_cool_release, r.unmet_cool_corrected)
        assert (bh or bc) == bool(r.unmet_hours_material), r.case
        rows.append(" & ".join([who(r), plain(r.unmet_heat_release, bold=bh), plain(r.unmet_heat_corrected, bold=bh),
                                plain(r.unmet_cool_release, bold=bc), plain(r.unmet_cool_corrected, bold=bc)]))
    unmet = longtable(
        "@{}llrrrr@{}",
        "Occupied unmet heating and cooling hours in each prototype case, release and two passes.",
        "tab:case-unmet",
        ["& Climate & \\multicolumn{2}{c}{Heating (h)} & \\multicolumn{2}{c}{Cooling (h)}",
         "\\cmidrule(lr){3-4}\\cmidrule(l){5-6}",
         "Building & zone & Release & Two passes & Release & Two passes"],
        rows,
        "Bold: material change (at least 10\\% and 5 h for heating or cooling, or the total "
        "crossing 300 h)." + flag)
    unmet = unmet.replace("\\cmidrule(lr){3-4}\\cmidrule(l){5-6} \\\\", "\\cmidrule(lr){3-4}\\cmidrule(l){5-6}")

    rows = []
    for _, r in two[two.window_savings_eligible].iterrows():
        rows.append(" & ".join([who(r), plain(r.savings_release_GJ), plain(r.savings_corrected_GJ),
                                signed(r.savings_pct, digits=1, bold=r.window_savings_material)]))
    window = longtable(
        "@{}llrrr@{}",
        "Annual site energy savings of the window upgrade in each eligible prototype case, release "
        "and two passes.",
        "tab:case-window",
        ["& Climate & \\multicolumn{2}{c}{Savings (GJ)} & Change",
         "\\cmidrule(lr){3-4}",
         "Building & zone & Release & Two passes & (\\%)"],
        rows,
        "Bold: material change (at least 10\\%, or a change of sign). Negative savings: the upgrade "
        "increases annual site energy. Change: (two passes $-$ release) $\\div$ release. Where the "
        "release's savings are negative, a positive change means the increase in energy use grew."
        + flag)
    window = window.replace("\\cmidrule(lr){3-4} \\\\", "\\cmidrule(lr){3-4}")

    stamp = "% Generated by make_case_tables.py from results/prototypes/case_deltas.csv. Do not edit.\n"
    files = {"case_energy.tex": energy, "case_limits.tex": limits, "case_unmet.tex": unmet,
             "case_window.tex": window}
    for name, body in files.items():
        (OUT / name).write_text(stamp + body)
    print(f"{len(two)} cases, {int(two.window_savings_eligible.sum())} window cases -> {', '.join(files)} in {OUT}")


if __name__ == "__main__":
    main()
