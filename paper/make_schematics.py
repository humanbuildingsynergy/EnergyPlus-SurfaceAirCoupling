"""Schematic figures of the paper (Figures 1 and 2): the three simple models, and the order of calculation within a
zone timestep with the passes of the correction. Drawn, not computed; they use no result files.

Writes paper/figures/fig_calculation_order.pdf and fig_simple_models.pdf.
Usage (repository root): python3 paper/make_schematics.py
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_figures import INK, INK2, OUT, SAVE, TEXTWIDTH_IN  # noqa: E402  (shared style)

BLUE = "#2a78d6"      # the correction, as "two passes" in the result figures
CONCRETE = "#cfcdc6"
AIR = "#eef4fb"


def box(ax, x, y, w, h, text, fc="white", ec=INK2, lw=0.8, size=7.5, weight="normal"):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.01,rounding_size=0.02",
                                fc=fc, ec=ec, lw=lw))
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=size, color=INK,
            weight=weight, linespacing=1.25)


def arrow(ax, p0, p1, color=INK2, ls="-", lw=0.9, rad=0.0, head=7):
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=head, color=color,
                                 lw=lw, ls=ls, connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=0, shrinkB=0))


def room(ax, floor_mass, labels):
    """Section through the room: thin lines for massless walls and roof, the floor below."""
    x0, x1, y0, y1 = 0.12, 0.88, 0.30, 0.78
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fc=AIR, ec="none"))
    ax.plot([x0, x0, x1, x1], [y0, y1, y1, y0], color=INK, lw=1.4, solid_capstyle="butt")
    if floor_mass:
        ax.add_patch(Rectangle((x0, y0 - 0.06), x1 - x0, 0.06, fc=CONCRETE, ec=INK, lw=0.8,
                               hatch="////"))
    else:
        ax.plot([x0, x1], [y0, y0], color=INK, lw=1.4)
        ax.plot([x0, x1], [y0 - 0.012, y0 - 0.012], color=INK2, lw=0.5, ls=(0, (2, 2)))
    for x, y, s, kw in labels:
        ax.text(x, y, s, fontsize=7, color=INK, linespacing=1.25, **kw)


def fig_simple_models():
    fig, axes = plt.subplots(1, 3, figsize=(TEXTWIDTH_IN, 3.0))
    for ax in axes:
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    # (a) conduction through a massive wall
    ax = axes[0]
    ax.add_patch(Rectangle((0.30, 0.30), 0.16, 0.48, fc=CONCRETE, ec=INK, lw=0.8, hatch="////"))
    ax.add_patch(Rectangle((0.46, 0.30), 0.46, 0.48, fc=AIR, ec="none"))
    t = np.linspace(0, 2 * np.pi, 60)
    ax.plot(0.03 + 0.22 * t / (2 * np.pi), 0.54 + 0.06 * np.sin(t), color=BLUE, lw=1.0)
    ax.text(0.0, 0.84, "Outside face:\n$20 + 10\\,\\sin(2\\pi t/24\\,\\mathrm{h})$ °C",
            fontsize=7, color=INK, va="bottom")
    ax.text(0.38, 0.22, "0.1 m concrete", ha="center", fontsize=7, color=INK)
    ax.text(0.71, 0.62, "Air held\nat 20 °C", ha="center", fontsize=7, color=INK)
    arrow(ax, (0.50, 0.53), (0.90, 0.53), lw=0.7, head=6)
    ax.text(0.71, 0.50, "Convection\n8 W/(m²K)", ha="center", va="top", fontsize=7, color=INK)

    # (b) single room on design days
    room(axes[1], True, [
        (0.50, 0.82, "Massless walls and roof", {"ha": "center"}),
        (0.50, 0.54, "Internal gain;\nfree-floating, or\nideal air system",
         {"ha": "center", "va": "center"}),
        (0.50, 0.15, "10 cm concrete floor", {"ha": "center"}),
    ])
    # (c) room with an exact solution
    room(axes[2], False, [
        (0.50, 0.82, "All surfaces massless", {"ha": "center"}),
        (0.50, 0.54, "Fixed convection,\n3 W/(m²K) inside,\n20 W/(m²K) outside;\nno long-wave, solar\nor internal gains",
         {"ha": "center", "va": "center"}),
        (0.50, 0.17, "Floor adiabatic", {"ha": "center"}),
    ])

    panels = [("(a) Massive wall",
               "1 m cube, one concrete wall\nTests: conduction alone\nReference: exact solution"),
              ("(b) Single room",
               "15.24 × 15.24 × 4.57 m\nDenver design days\nTests: whole zone balance\n"
               "Reference: run at 30 per hour"),
              ("(c) Room with an exact solution",
               "Same geometry\nOne year of Denver weather\nTests: whole solution\n"
               "Reference: exact solution")]
    for ax, (title, foot) in zip(axes, panels):
        ax.text(0.5, 1.04, title, fontsize=8, weight="bold", color=INK, ha="center",
                transform=ax.transAxes)
        ax.text(0.5, 0.06, foot, fontsize=7, color=INK2, ha="center", va="top",
                transform=ax.transAxes, linespacing=1.3)
    fig.subplots_adjust(wspace=0.18)
    fig.savefig(OUT / "fig_simple_models.pdf", **SAVE)
    plt.close(fig)


def fig_calculation_order():
    fig, ax = plt.subplots(figsize=(TEXTWIDTH_IN, 2.5))
    ax.set_xlim(0, 10); ax.set_ylim(0, 4.3); ax.axis("off")
    w, h, y = 2.6, 1.25, 1.65
    xs = [0.05, 2.95, 5.85]
    box(ax, xs[0], y, w, h, "Outside surface\nheat balances\n(fast-conducting surfaces:\n"
        "also the inside face)", size=7)
    box(ax, xs[1], y, w, h, "Inside surface\nheat balances, iterated\nagainst each other", size=7)
    box(ax, xs[2], y, w, h, "Zone air balance:\npredictor, HVAC, corrector\n"
        "with the new surface\ntemperatures; gives $T_z^{\\,t}$", size=7)
    box(ax, 8.75, y + 0.3, 1.15, 0.65, "Next\ntimestep", fc="#f6f6f4", size=7)
    for a, b in [(xs[0] + w, xs[1]), (xs[1] + w, xs[2]), (xs[2] + w, 8.75)]:
        arrow(ax, (a + 0.03, y + h / 2), (b - 0.03, y + h / 2))
    # the lag: both surface balances read the air temperature of the previous timestep
    ax.text(2.8, 3.92, "Air temperature of the previous timestep, $T_z^{\\,t-\\delta t}$",
            ha="center", fontsize=7.5, color=INK)
    for x in [xs[0] + w / 2, xs[1] + w / 2]:
        arrow(ax, (2.8, 3.82), (x, y + h + 0.03), lw=0.8)
    # the correction: passes that repeat the calculation with the current air temperature
    yl = y - 0.45
    xr, xl = xs[2] + w / 2, xs[0] + w / 2
    ax.plot([xr, xr, xl], [y, yl, yl], color=BLUE, lw=1.1, ls="--")
    arrow(ax, (xl, yl), (xl, y - 0.02), color=BLUE, lw=1.1, ls="--")
    ax.text((xl + xr) / 2, yl - 0.15,
            "Correction (passes): repeat the three steps with the current $T_z^{\\,t}$, starting "
            "from the air state at the\nbeginning of the timestep, until $T_z^{\\,t}$ changes by "
            "less than the tolerance or the limit on the passes is reached",
            ha="center", va="top", fontsize=7, color=BLUE, linespacing=1.3)
    fig.savefig(OUT / "fig_calculation_order.pdf", **SAVE)
    plt.close(fig)


if __name__ == "__main__":
    fig_simple_models()
    fig_calculation_order()
    print("written: fig_simple_models.pdf, fig_calculation_order.pdf")
