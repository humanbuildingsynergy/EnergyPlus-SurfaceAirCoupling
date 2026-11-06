"""Result figures of the paper (Figures 3 to 7), built from the summary files in results/.

Writes paper/figures/fig_room_order.pdf, fig_exact_room.pdf, fig_case_heatmap.pdf,
fig_window_savings.pdf and fig_accuracy_runtime.pdf. Rebuilding with unchanged data gives
identical files.
Usage (repository root): python3 paper/make_figures.py
"""
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
OUT = Path(__file__).resolve().parent / "figures"
RES = REPO / "results"

INK = "#0b0b0b"
INK2 = "#52514e"
GRID = "#e4e3df"
SCHEME = {
    "ThirdOrderBackwardDifference": ("#2a78d6", "o", "Third-order (default)"),
    "AnalyticalSolution": ("#eb6834", "s", "Analytical"),
    "EulerMethod": ("#1baf7a", "^", "Euler"),
}
CONFIG = {  # release in gray, then darker blue with more passes
    "release": ("#52514e", "o", "Release"),
    "one_pass": ("#86b6ef", "v", "One pass"),
    "two_passes": ("#2a78d6", "s", "Two passes"),
    "converged": ("#104281", "D", "Converged"),
}
TEXTWIDTH_IN = 6.5

plt.rcParams.update({
    "font.size": 8, "axes.labelsize": 8, "axes.titlesize": 8, "xtick.labelsize": 7.5,
    "ytick.labelsize": 7.5, "legend.fontsize": 7.5, "axes.edgecolor": INK2, "axes.labelcolor": INK,
    "xtick.color": INK2, "ytick.color": INK2, "axes.linewidth": 0.6, "lines.linewidth": 1.4,
    "lines.markersize": 4, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False,
    "pdf.fonttype": 42, "savefig.bbox": "tight", "savefig.pad_inches": 0.02,
})
# Fixed metadata, so a rebuild with unchanged data gives identical files.
plt.rcParams["pdf.compression"] = 6
SAVE = {"metadata": {"CreationDate": None, "ModDate": None}}


def slope_guides(ax, x, y_anchor, orders=(1, 2, 3)):
    """Gray reference lines with the slopes of orders 1, 2 and 3, through the coarsest point.

    Call after the data are plotted: the lines are clipped to the data's range and each is labeled
    where it leaves the plot at the bottom (or at its left end)."""
    x = np.asarray(sorted(x))
    ymin, ymax = ax.get_ylim()
    for p in orders:
        y = y_anchor * (x / x[-1]) ** p
        ax.plot(x, y, "-", color="#b8b7b2", lw=0.9, zorder=1)
        if y[0] >= ymin:
            xl, yl = x[0], y[0]
        else:
            yl = ymin * 1.15
            xl = x[-1] * (yl / y_anchor) ** (1 / p)
        ax.annotate(f"order {p}", (xl, yl), xytext=(2, 1), textcoords="offset points",
                    fontsize=7, color=INK2, va="bottom")
    ax.set_ylim(ymin, ymax)



def room_errors(config_dir, case="free", env_key="CLG", ref_ts=30):
    """RMS of hour-end zone air temperature against the same configuration's run with ref_ts per hour."""
    d = pd.read_csv(RES / "single_room" / config_dir / "hour_end_temperatures.csv.gz")
    d = d[(d["case"] == case) & (d["var"] == "Zone Mean Air Temperature") & d["env"].str.contains(env_key)]
    rows = []
    for algo, g in d.groupby("algo"):
        ref = g[g["ts"] == ref_ts].set_index("hour")["value"]
        for ts, h in g.groupby("ts"):
            if ts >= ref_ts:
                continue
            e = h.set_index("hour")["value"] - ref
            rows.append({"algo": algo, "ts": ts, "minutes": 60 / ts, "rms": float(np.sqrt((e ** 2).mean()))})
    return pd.DataFrame(rows)


def fig_room():
    """Single room, summer design day, free-floating: error against timestep for the three schemes."""
    panels = [("release", "(a) Release"),
              ("converged", "(b) Converged")]
    fig, axes = plt.subplots(1, 2, figsize=(TEXTWIDTH_IN, 2.6), sharey=True)
    for ax, (eng, title) in zip(axes, panels):
        e = room_errors(eng)
        for algo, (c, m, lab) in SCHEME.items():
            g = e[e["algo"] == algo].sort_values("minutes")
            ax.plot(g["minutes"], g["rms"], marker=m, color=c, label=lab, zorder=3)
        ax.set_xscale("log"); ax.set_yscale("log")
        ax.set_ylim(2e-4, 1.0)
        third = e[e["algo"] == "ThirdOrderBackwardDifference"].sort_values("minutes")
        slope_guides(ax, third["minutes"], third["rms"].iloc[-1] * 1.6)
        ax.set_xticks([3, 6, 10, 20, 30, 60]); ax.set_xticklabels(["3", "6", "10", "20", "30", "60"])
        ax.set_xlabel("Timestep (min)")
        ax.set_title(title, loc="left", color=INK)
    axes[0].set_ylabel("RMS error (°C)")
    axes[0].legend(loc="lower right")
    fig.savefig(OUT / "fig_room_order.pdf", **SAVE)
    plt.close(fig)


def fig_exact_room():
    """Room with an exact solution: error against timestep for the four configurations."""
    d = pd.read_csv(RES / "exact_room/errors.csv")
    d["minutes"] = 60 / d["ts"]
    fig, ax = plt.subplots(figsize=(TEXTWIDTH_IN * 0.55, 2.7))
    for cfg, (c, m, lab) in CONFIG.items():
        g = d[d["configuration"] == cfg].sort_values("minutes")
        ax.plot(g["minutes"], g["rms_C"], marker=m, color=c, label=lab, zorder=3)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_ylim(1e-4, 8)
    r = d[d["configuration"] == "release"].sort_values("minutes")
    slope_guides(ax, r["minutes"], r["rms_C"].iloc[-1] * 0.25)
    ax.set_xticks([1, 3, 6, 10, 20, 60]); ax.set_xticklabels(["1", "3", "6", "10", "20", "60"])
    ax.set_xlabel("Timestep (min)")
    ax.set_ylabel("RMS error (°C)")
    ax.legend(loc="lower right")
    fig.savefig(OUT / "fig_exact_room.pdf", **SAVE)
    plt.close(fig)


def fig_window_savings():
    """Window-upgrade savings: size of the savings against how much two passes change them."""
    d = pd.read_csv(RES / "prototypes/case_deltas.csv")
    m = pd.read_csv(RES / "prototypes/case_metrics.csv")
    site = m[(m["configuration"] == "release") & (m["variant"] == "base")].set_index("case")["site_GJ"]
    s = d[(d["configuration"] == "two_passes") & d["window_savings_eligible"].astype(bool)].copy()
    s["size"] = 100 * s["savings_release_GJ"].abs() / s["case"].map(site)
    s["change"] = s["savings_pct"].abs()
    sign = np.sign(s["savings_release_GJ"]) != np.sign(s["savings_corrected_GJ"])
    mat = s["window_savings_material"].astype(bool)
    fig, ax = plt.subplots(figsize=(TEXTWIDTH_IN * 0.62, 3.0))
    ax.axhline(10, color=INK2, ls="--", lw=0.8, zorder=1)
    ax.text(0.98, 10 * 1.15, "threshold, 10%", transform=ax.get_yaxis_transform(), ha="right",
            va="bottom", fontsize=7, color=INK2)
    groups = [
        (~mat, "#9e9d98", "o", "Below threshold"),
        (mat & ~sign, "#2a78d6", "o", "Material change"),
        (sign, "#2a78d6", "^", "Sign of the savings changes"),
    ]
    for g, c, mk, lab in groups:
        pos = g & (s["savings_release_GJ"] > 0)
        neg = g & (s["savings_release_GJ"] <= 0)
        ax.scatter(s.loc[pos, "size"], s.loc[pos, "change"], s=22, color=c, marker=mk, lw=0, zorder=3,
                   label=lab)
        ax.scatter(s.loc[neg, "size"], s.loc[neg, "change"], s=22, facecolor="none", edgecolor=c,
                   marker=mk, lw=1.0, zorder=3)
    ax.scatter([], [], s=22, facecolor="none", edgecolor=INK2, lw=1.0,
               label="Upgrade increases site energy")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("Size of the savings with the release (% of site energy)")
    ax.set_ylabel("Change from release to two passes (%)")
    ax.legend(loc="upper right", fontsize=7)
    fig.savefig(OUT / "fig_window_savings.pdf", **SAVE)
    plt.close(fig)


def fig_accuracy_runtime():
    """Three prototype buildings: error against timestep (top) and runtime relative to the release
    (bottom), for the release and the corrected configurations."""
    d = pd.read_csv(RES / "prototypes/accuracy_runtime_errors.csv")
    names = {"OfficeMedium_Denver": "(a) Medium office", "SchoolPrimary_Denver": "(b) Primary school",
             "RetailStandalone_Denver": "(c) Standalone retail"}
    dodge = {"release": 0.97, "one_pass": 1.0, "two_passes": 1.03}
    fig, axes = plt.subplots(2, 3, figsize=(TEXTWIDTH_IN, 4.2), sharex=True,
                             gridspec_kw={"height_ratios": [1.5, 1]})
    for j, (case, title) in enumerate(names.items()):
        g = d[d["case"] == case]
        ax, bx = axes[0, j], axes[1, j]
        ref30 = g[(g["configuration"] == "converged") & (g["ts"] == 30)]["air_rms_C"]
        if len(ref30):
            ax.axhline(float(ref30.iloc[0]), color=INK2, ls="--", lw=0.8, zorder=1)
        rel = g[g["configuration"] == "release"].set_index("ts")["wall_s_median"]
        for eng in ("release", "one_pass", "two_passes"):
            c, m, lab = CONFIG[eng]
            h = g[g["configuration"] == eng].dropna(subset=["wall_s_median"]).sort_values("ts")
            ax.plot(h["ts"] * dodge[eng], h["air_rms_C"], marker=m, color=c, label=lab, zorder=3,
                    markerfacecolor="none", markeredgewidth=1.0, lw=1.0)
            if eng != "release":
                ratio = h.set_index("ts")["wall_s_median"] / rel
                bx.plot(ratio.index * dodge[eng], ratio.values, marker=m, color=c, zorder=3,
                        markerfacecolor="none", markeredgewidth=1.0, lw=1.0)
        bx.axhline(1, color=CONFIG["release"][0], lw=1.0, zorder=1)
        ax.set_yscale("log"); ax.set_xscale("log")
        ax.set_title(title, loc="left", color=INK)
        bx.set_ylim(0.8, 2.3)
        bx.set_xticks([4, 6, 10, 20, 30, 60]); bx.set_xticklabels(["4", "6", "10", "20", "30", "60"])
        bx.minorticks_off(); ax.minorticks_off()
        bx.set_xlabel("Timesteps per hour")
    axes[0, 0].set_ylabel("RMS error (°C)")
    axes[1, 0].set_ylabel("Runtime ÷ release")
    axes[0, 0].plot([], [], ls="--", color=INK2, lw=0.8, label="Reference at\n30 per hour")
    axes[0, 0].legend(loc="lower left", fontsize=7)
    fig.tight_layout(h_pad=0.6, w_pad=1.0)
    fig.savefig(OUT / "fig_accuracy_runtime.pdf", **SAVE)
    plt.close(fig)


BUILDING_NAMES = {
    "ApartmentHighRise": "High-rise apartment", "ApartmentMidRise": "Mid-rise apartment",
    "Hospital": "Hospital", "HotelLarge": "Large hotel", "HotelSmall": "Small hotel",
    "OfficeLarge": "Large office", "OfficeMedium": "Medium office",
    "OutPatientHealthCare": "Outpatient health care", "RestaurantFastFood": "Fast-food restaurant",
    "RestaurantSitDown": "Sit-down restaurant", "RetailStandalone": "Standalone retail",
    "RetailStripmall": "Strip mall", "SchoolPrimary": "Primary school",
    "SchoolSecondary": "Secondary school", "Warehouse": "Warehouse",
}


def fig_case_heatmap():
    """Every prototype case: change from the release to two passes, as a multiple of its threshold."""
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.patches import Rectangle

    d = pd.read_csv(RES / "prototypes/case_deltas.csv")
    d = d[d["configuration"] == "two_passes"].copy()
    d[["bldg", "city"]] = d["case"].str.split("_", n=1, expand=True)
    outcomes = [  # label, column, eligibility column, threshold (%)
        ("Heating\nenergy", "heating_pct", "heating_eligible", 1),
        ("Cooling\nenergy", "cooling_pct", "cooling_eligible", 1),
        ("Fan\nenergy", "fans_pct", "fans_eligible", 1),
        ("Peak\ndemand", "peak_pct", None, 2),
        ("Cooling\ncapacity", "cool_cap_W_pct", None, 2),
        ("Heating\ncapacity", "heat_cap_W_pct", None, 2),
        ("Supply\nfan flow", "fan_flow_m3s_pct", None, 2),
    ]
    cities = [("Miami", "1A"), ("Denver", "5B"), ("InternationalFalls", "7")]
    bldgs = sorted(d["bldg"].unique())
    cmap = LinearSegmentedColormap.from_list("div", ["#2a78d6", "#f0efec", "#e34948"])
    gap = 0.6
    fig, ax = plt.subplots(figsize=(TEXTWIDTH_IN, 4.1))
    for j, (lab, col, elig, thr) in enumerate(outcomes):
        x0 = j * (3 + gap)
        for k, (city, code) in enumerate(cities):
            for i, b in enumerate(bldgs):
                r = d[(d["bldg"] == b) & (d["city"] == city)]
                if r.empty:
                    continue
                r = r.iloc[0]
                x, y = x0 + k, i
                if (elig is not None and not bool(r[elig])) or pd.isna(r[col]):
                    ax.add_patch(Rectangle((x, y), 1, 1, facecolor="#fcfcfb", edgecolor=GRID,
                                           hatch="////", lw=0.3))
                    continue
                v = float(r[col]) / thr
                ax.add_patch(Rectangle((x, y), 1, 1, facecolor=cmap((np.clip(v, -2, 2) + 2) / 4),
                                       edgecolor="#fcfcfb", lw=0.6))
                if abs(v) >= 1:
                    ax.add_patch(Rectangle((x + 0.06, y + 0.06), 0.88, 0.88, fill=False,
                                           edgecolor=INK, lw=1.0))
            ax.text(x0 + k + 0.5, len(bldgs) + 0.25, code, ha="center", va="top", fontsize=6.5,
                    color=INK2)
        ax.text(x0 + 1.5, -0.3, lab.replace("\\n", "\n"), ha="center", va="bottom", fontsize=7,
                color=INK)
    ax.set_xlim(-0.2, len(outcomes) * (3 + gap) - gap + 0.2)
    ax.set_ylim(len(bldgs) + 2.3, -1.6)
    ax.set_yticks([i + 0.5 for i in range(len(bldgs))])
    ax.set_yticklabels([BUILDING_NAMES[b] for b in bldgs])
    ax.set_xticks([])
    ax.tick_params(axis="y", length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    ax.grid(False)
    key_y = len(bldgs) + 1.25
    ax.add_patch(Rectangle((0, key_y), 1, 0.8, facecolor="#f0efec", edgecolor=INK, lw=1.0,
                           clip_on=False))
    ax.text(1.3, key_y + 0.4, "Material change", va="center", fontsize=7, color=INK)
    ax.add_patch(Rectangle((7.2, key_y), 1, 0.8, facecolor="#fcfcfb", edgecolor=GRID, hatch="////",
                           lw=0.3, clip_on=False))
    ax.text(8.5, key_y + 0.4, "Not counted: end use below 5% of site energy, or no autosized "
            "equipment of that kind", va="center", fontsize=7, color=INK)
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(-2, 2))
    cb = fig.colorbar(sm, ax=ax, fraction=0.025, pad=0.01, ticks=[-2, -1, 0, 1, 2])
    cb.set_label("Change ÷ threshold", fontsize=7)
    cb.ax.tick_params(labelsize=6.5)
    cb.outline.set_visible(False)
    fig.savefig(OUT / "fig_case_heatmap.pdf", **SAVE)
    plt.close(fig)


if __name__ == "__main__":
    fig_room()
    fig_exact_room()
    fig_window_savings()
    fig_accuracy_runtime()
    fig_case_heatmap()
    print("written:", ", ".join(sorted(p.name for p in OUT.glob("fig_*.pdf"))))
