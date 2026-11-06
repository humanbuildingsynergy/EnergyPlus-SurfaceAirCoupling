"""Variants of the single room that change one term of the model at a time, to check that the lag,
and no other term, holds the solution at first order (the paper's Table 3).

The room is single_room.py's free_nosolar case (floating, no solar gain, massless walls and roof,
4 in concrete floor) with the third-order scheme, on its summer design day. Variants:
  unchanged      as described
  fixed_h        interior convection coefficients fixed at 3 W/(m2 K)
  no_lw          interior long-wave exchange off (thermal absorptance 1e-4 on every face)
  fixed_h_no_lw  both of the above
  no_substeps    subdivision of the HVAC timestep suppressed (MaxZoneTempDiff raised to 3 C)
  long_warmup    100 warmup days
Configurations: the release; inside_faces (only the inside surfaces calculated again in each
pass); both_faces (outside and inside faces). Errors are RMS differences at the hour ends from the
run with 30 timesteps per hour of the same configuration, which shares the conduction grid with
every coarser timestep, so the fit measures time error only.
Writes results/single_room/room_variants.csv: per configuration, variant and variable, the order
fitted from 2 to 10 per hour and the RMS error at 4 per hour [C] (surface rows: the median over
the inside faces). Raw runs: <runs>/room_variants/<configuration>/<variant>_tsNN/; the runs at 12
and 20 per hour are used only by tests/order_estimates.py.
Usage (repository root):
  python3 tests/room_variants.py [--configurations release inside_faces both_faces] [--runs runs]
"""

import argparse
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402
import single_room as room  # noqa: E402

RESULTS = REPO / "results" / "single_room"
TS = [2, 3, 4, 5, 6, 10, 12, 20, 30]
FIT = [2, 3, 4, 5, 6, 10]
CONFIGURATIONS = ["release", "inside_faces", "both_faces"]

# SurfaceProperty:ConvectionCoefficients:MultipleSurface on every interior face.
FIX_H = "\n  SurfaceProperty:ConvectionCoefficients:MultipleSurface, AllInteriorSurfaces, Inside, Value, 3.0;\n"
# PerformancePrecisionTradeoffs: the fourth field, MaxZoneTempDiff (default 0.3 C), is the change
# in zone air temperature above which the HVAC timestep is subdivided.
NOSUB = "\n  PerformancePrecisionTradeoffs, No, ScriptF, Advanced, 3.0, 0.002;\n"


def no_lw(text):
    return re.sub(r"([0-9.]+)(,\s*!- Thermal Absorptance)", r"0.0001\2", text)


def long_warmup(text):
    """Building object: minimum and maximum number of warmup days set to 100."""
    text = re.sub(r"30,(\s*!- Maximum Number of Warmup Days)", r"100,\1", text)
    return re.sub(r"6;(\s*!- Minimum Number of Warmup Days)", r"100;\1", text)


VARIANTS = {
    "unchanged": lambda t: t,
    "fixed_h": lambda t: t + FIX_H,
    "no_lw": no_lw,
    "fixed_h_no_lw": lambda t: no_lw(t + FIX_H),
    "no_substeps": lambda t: t + NOSUB,
    "long_warmup": long_warmup,
}


def orders(frames, keys):
    v = pd.concat(frames)
    v = v[v.env.str.contains("CLG") | ~v.env.str.contains("HTG")]  # summer design day
    v = v[v.minute.isin([0, 60])]
    k = keys + ["var", "key"]
    ref = v[v.ts == 30].set_index(k + ["hour", "minute"]).value.rename("ref")
    v = v.join(ref, on=k + ["hour", "minute"])
    v["e"] = v.value - v.ref
    rms = v[v.ts < 30].groupby(k + ["ts"]).e.apply(lambda e: float(np.sqrt((e ** 2).mean())))
    rms = rms.reset_index()
    rows = []
    for kk, g in rms[rms.ts.isin(FIT)].groupby(k):
        rows.append(dict(zip(k, kk)) | {
            "order": float(np.polyfit(np.log(60.0 / g.ts), np.log(g.e), 1)[0]),
            "rms_ts04_C": float(g[g.ts == 4].e.iloc[0])})
    # median over surfaces (or the single zone) per variable
    return (pd.DataFrame(rows).groupby(keys + ["var"])[["order", "rms_ts04_C"]].median()
            .reset_index().round({"order": 2}))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--configurations", nargs="+", default=CONFIGURATIONS)
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(RESULTS), help="folder for room_variants.csv")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    runs = Path(a.runs).resolve() / "room_variants"
    out = Path(a.results)
    out.mkdir(parents=True, exist_ok=True)
    base = (C.RELEASE / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()

    jobs, meta = [], []
    for conf in a.configurations:
        eplus, extra = C.program(conf)
        for var, f in VARIANTS.items():
            for ts in TS:
                idf = f(room.make_idf(base, "free_nosolar", ts, "ThirdOrderBackwardDifference"))
                name = f"{conf}/{var}_ts{ts:02d}"
                jobs.append((str(eplus), idf, name, str(runs), False, extra))
                meta.append((conf, var, ts, name))
    with ProcessPoolExecutor(a.workers) as ex:
        log = list(ex.map(room.run, jobs))
    bad = [r for r in log if r["returncode"] != 0]
    if bad:
        sys.exit(f"failed runs: {bad}")

    frames = []
    for conf, var, ts, name in meta:
        df = room.hour_end_series(runs / name / "eplusout.sql")
        df["configuration"], df["variant"], df["ts"] = conf, var, ts
        frames.append(df)
    o = orders(frames, ["configuration", "variant"])
    o = o[o["var"] != "Surface Outside Face Temperature"]
    o.to_csv(out / "room_variants.csv", index=False, float_format="%.4g")
    pd.set_option("display.width", 200)
    print(o.pivot_table(index=["variant", "var"], columns="configuration", values=["order", "rms_ts04_C"])
          .to_string(float_format=lambda x: f"{x:.3g}"))


if __name__ == "__main__":
    main()
