"""Order of accuracy estimated three ways, for the single room, its variants and the room with an
exact solution: the least-squares fit, local orders between neighbouring timesteps, and estimates
that need no reference.

A reference run at a shorter timestep carries an error of its own and biases fitted orders upward
(against the 30/h run, a true first-order method reads about 1.2 from 2 to 10 per hour, a true
second-order one about 2.07). For the same data this script gives:
  lsq          slope of log RMS error against log timestep length, with its standard error and
               R^2. Reference: the 30/h run (same conduction grid as every coarser timestep); for
               the massless room (free_nosolar_nomass, whose grid does not change) also the 60/h
               run; for the exact room the exact solution.
  three_level  p = ln(d(n, 2n) / d(2n, 4n)) / ln 2, with d the RMS difference of two runs at their
               common hour ends; needs no reference. Triplets 1/2/4, 3/6/12 and 5/10/20 per hour,
               and 15/30/60 for massless rooms only (at 60/h the grid of the concrete floor changes).
  local        ln(e_k / e_k+1) / ln(n_k+1 / n_k) between neighbouring timesteps of the sweep,
               against the same references (local_orders.csv).
Sources (column "source"):
  single_room    results/single_room/{release,converged}/hour_end_temperatures.csv.gz; all cases,
                 both design days, all three schemes
  room_variants  the runs of tests/room_variants.py in <runs>/room_variants/ (free_nosolar, third-
                 order scheme, summer day; release, inside_faces, both_faces)
  exact_room     the runs of tests/exact_room_schemes.py in <runs>/exact_room_schemes/ and the exact
                 solution in results/exact_room/; errors at the zone timestep ends from day 3,
                 three-level differences at common hour ends from day 3
Surface rows: the estimate per inside face, then the median over faces. Air rows: the one zone.
Writes results/order_estimates/order_estimates.csv (source, case, day, scheme, configuration,
variable, method, window, reference, order, se, r2, n_levels) and local_orders.csv (errors [C] at
the two timesteps and the local order).
Usage (repository root): python3 tests/order_estimates.py [--runs runs] [--sources ...]
"""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import exact_room as exact
import room_variants as V
import single_room as room

REPO = Path(__file__).resolve().parents[1]
ROOM = REPO / "results" / "single_room"
SINGLE_ROOM_CONFIGURATIONS = ["release", "converged"]
VARIANT_CONFIGURATIONS = ["release", "inside_faces", "both_faces"]
VARIANT_TS = [2, 3, 4, 5, 6, 10, 12, 20, 30]
LSQ_WINDOW = [2, 3, 4, 5, 6, 10]
EXACT_WINDOW = exact.FIT  # 4-20/h, as exact_room.py
TRIPLETS = [(1, 2, 4), (3, 6, 12), (5, 10, 20)]
TRIPLET_MASSLESS = (15, 30, 60)
SOURCES = ["single_room", "room_variants", "exact_room"]


def lsq(ts, e):
    x, y = np.log(60.0 / np.asarray(ts, float)), np.log(np.asarray(e, float))
    if len(x) < 3:
        return np.nan, np.nan, np.nan
    (b, a), cov = np.polyfit(x, y, 1, cov=True)
    r2 = 1 - ((y - (a + b * x)) ** 2).sum() / ((y - y.mean()) ** 2).sum()
    return float(b), float(np.sqrt(cov[0, 0])), float(r2)


def rms(v):
    return float(np.sqrt(np.mean(np.asarray(v, float) ** 2)))


def estimates(series, ref_ts, massless):
    """series: {ts: pd.Series indexed by point}. Returns (order rows, local rows) for one key."""
    rows, loc = [], []
    refs = [(ref_ts, f"{ref_ts}/h")] + ([(60, "60/h")] if massless and ref_ts != 60 else [])
    for rts, rname in refs:
        if rts not in series:
            continue
        e = {n: rms((series[n] - series[rts]).dropna()) for n in sorted(series) if n < rts}
        w = [n for n in LSQ_WINDOW if n in e and e[n] > 0]
        o, se, r2 = lsq(w, [e[n] for n in w])
        rows.append({"method": "lsq", "window": f"{w[0]}-{w[-1]}/h", "reference": rname, "order": o,
                     "se": se, "r2": r2, "n_levels": len(w)})
        ns = sorted(e)
        for a_, b_ in zip(ns[:-1], ns[1:]):
            if e[a_] > 0 and e[b_] > 0:
                loc.append({"reference": rname, "ts_coarse": a_, "ts_fine": b_, "e_coarse_C": e[a_],
                            "e_fine_C": e[b_], "local_order": np.log(e[a_] / e[b_]) / np.log(b_ / a_)})
    for t in TRIPLETS + ([TRIPLET_MASSLESS] if massless else []):
        if all(n in series for n in t):
            d12 = rms((series[t[0]] - series[t[1]]).dropna())
            d23 = rms((series[t[1]] - series[t[2]]).dropna())
            rows.append({"method": "three_level", "window": "/".join(map(str, t)) + "/h", "reference": "none",
                         "order": np.log(d12 / d23) / np.log(2) if d12 > 0 and d23 > 0 else np.nan,
                         "se": np.nan, "r2": np.nan, "n_levels": 3})
    return rows, loc


def collect(frame_by_ts, meta, ref_ts, massless):
    """frame_by_ts: {ts: DataFrame(var, key, point, value)}; per variable, median over surfaces."""
    rows, locs = [], []
    allv = pd.concat([f.assign(ts=n) for n, f in frame_by_ts.items()])
    for var, gv in allv.groupby("var"):
        what = "air" if var.startswith("Zone") else "surface"
        per, perl = [], []
        for key, g in gv.groupby("key"):
            s = {n: x.set_index("point").value for n, x in g.groupby("ts")}
            r, l = estimates(s, ref_ts, massless)
            per += [x | {"key": key} for x in r]
            perl += [x | {"key": key} for x in l]
        if not per:
            continue
        p = pd.DataFrame(per).groupby(["method", "window", "reference"], sort=False)
        agg = p[["order", "se", "r2"]].median().join(p.n_levels.first()).reset_index()
        rows += [meta | {"variable": what} | x for x in agg.to_dict("records")]
        if perl:
            q = pd.DataFrame(perl).groupby(["reference", "ts_coarse", "ts_fine"], sort=False)
            la = q[["e_coarse_C", "e_fine_C", "local_order"]].median().reset_index()
            locs += [meta | {"variable": what} | x for x in la.to_dict("records")]
    return rows, locs


def single_room_rows(runs):
    rows, locs = [], []
    for conf in SINGLE_ROOM_CONFIGURATIONS:
        h = pd.read_csv(ROOM / conf / "hour_end_temperatures.csv.gz")
        h["day"] = np.where(h.env.str.contains("CLG"), "summer", "winter")
        h["point"] = h.hour * 60 + h.minute
        for (case, day, algo), g in h.groupby(["case", "day", "algo"]):
            frames = {n: x[["var", "key", "point", "value"]] for n, x in g.groupby("ts")}
            meta = {"source": "single_room", "case": case, "day": day, "scheme": algo, "configuration": conf}
            r, l = collect(frames, meta, 30, case.endswith("nomass"))
            rows += r
            locs += l
    return rows, locs


def variant_rows(runs):
    rows, locs = [], []
    for conf in VARIANT_CONFIGURATIONS:
        for var in V.VARIANTS:
            frames = {}
            for ts in VARIANT_TS:
                sql = runs / "room_variants" / conf / f"{var}_ts{ts:02d}" / "eplusout.sql"
                if not sql.exists():
                    continue
                df = room.hour_end_series(sql)
                df = df[df.env.str.contains("CLG") & df.minute.isin([0, 60])
                        & (df["var"] != "Surface Outside Face Temperature")]
                df["point"] = df.hour * 60 + df.minute
                frames[ts] = df[["var", "key", "point", "value"]]
            meta = {"source": "room_variants", "case": f"free_nosolar:{var}", "day": "summer",
                    "scheme": "ThirdOrderBackwardDifference", "configuration": conf}
            r, l = collect(frames, meta, 30, False)
            rows += r
            locs += l
    return rows, locs


def exact_room_rows(runs):
    rows, locs = [], []
    ref = pd.read_csv(exact.RESULTS / "exact_solution.csv.gz").T_ref_C.to_numpy()
    for scheme in ("ThirdOrderBackwardDifference", "EulerMethod", "AnalyticalSolution"):
        for conf in exact.CONFIGURATIONS:
            ser, err = {}, {}
            for ts in exact.STEPS:
                d = runs / "exact_room_schemes" / scheme / f"{conf}_ts{ts:02d}"
                z = exact.series(d, "Zone Air Temperature")
                m = exact.minute_of_year(z).to_numpy()
                step = 60 // ts
                keep = (m % step == 0) & (m >= exact.START)
                zz = pd.Series(z.Value.to_numpy()[keep], index=m[keep]).groupby(level=0).last()
                err[ts] = rms(zz.to_numpy() - ref[zz.index.to_numpy()])
                ser[ts] = zz[zz.index % 60 == 0]
            meta = {"source": "exact_room", "case": "exact_room", "day": "annual", "scheme": scheme,
                    "configuration": conf, "variable": "air"}
            for win in (EXACT_WINDOW, LSQ_WINDOW):
                o, se, r2 = lsq(win, [err[n] for n in win])
                rows.append(meta | {"method": "lsq", "window": f"{win[0]}-{win[-1]}/h", "reference": "exact",
                                    "order": o, "se": se, "r2": r2, "n_levels": len(win)})
            for a_, b_ in zip(exact.STEPS[:-1], exact.STEPS[1:]):
                locs.append(meta | {"reference": "exact", "ts_coarse": a_, "ts_fine": b_, "e_coarse_C": err[a_],
                                    "e_fine_C": err[b_], "local_order": np.log(err[a_] / err[b_]) / np.log(b_ / a_)})
            for t in TRIPLETS + [TRIPLET_MASSLESS]:
                d12, d23 = rms((ser[t[0]] - ser[t[1]]).dropna()), rms((ser[t[1]] - ser[t[2]]).dropna())
                rows.append(meta | {"method": "three_level", "window": "/".join(map(str, t)) + "/h",
                                    "reference": "none", "order": np.log(d12 / d23) / np.log(2),
                                    "se": np.nan, "r2": np.nan, "n_levels": 3})
    return rows, locs


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", default=str(REPO / "runs"),
                    help="folder of raw runs holding room_variants/ and exact_room_schemes/")
    ap.add_argument("--sources", nargs="+", default=SOURCES, choices=SOURCES)
    ap.add_argument("--results", default=str(REPO / "results" / "order_estimates"))
    a = ap.parse_args()
    runs = Path(a.runs).resolve()
    rows, locs = [], []
    for name, f in (("single_room", single_room_rows), ("room_variants", variant_rows),
                    ("exact_room", exact_room_rows)):
        if name in a.sources:
            r, l = f(runs)
            rows += r
            locs += l
    out = Path(a.results)
    out.mkdir(parents=True, exist_ok=True)
    cols = ["source", "case", "day", "scheme", "configuration", "variable", "method", "window", "reference",
            "order", "se", "r2", "n_levels"]
    od = pd.DataFrame(rows)[cols]
    od.to_csv(out / "order_estimates.csv", index=False, float_format="%.4g")
    lc = ["source", "case", "day", "scheme", "configuration", "variable", "reference", "ts_coarse", "ts_fine",
          "e_coarse_C", "e_fine_C", "local_order"]
    pd.DataFrame(locs)[lc].to_csv(out / "local_orders.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 400)
    air = od[od.variable == "air"]
    print(air.pivot_table(index=["source", "case", "day", "scheme", "configuration"],
                          columns=["method", "window", "reference"], values="order").round(2).to_string())


if __name__ == "__main__":
    main()
