"""Conduction through one massive wall against its exact steady periodic solution, to show that
conduction alone converges at second order.

Model: a 1 m cube. One wall (TEST WALL) is a single 0.1 m concrete-like layer. Its outside face
temperature is imposed as 20 + 10 sin(2 pi t / 24 h) C through SurfaceProperty:OtherSideCoefficients
(no film coefficient, so the face temperature itself is set). Its inside face convects with a fixed
coefficient of 8 W/(m2 K) to zone air held at 20 C by an ideal air system. Long-wave and solar
exchange are negligible (thermal and solar absorptance 1e-4, sky clearness 0, no windows, no
gains). The other five surfaces are massless and adiabatic. Values are compared at the 24 hour
ends of the design day after warmup. The paper reports the default conduction method (CTF rows);
the two finite-difference schemes (CondFD) are run for comparison.
Writes results/massive_wall/run_log.csv, hour_end_values.csv.gz (value and exact solution [C]),
errors.csv (RMS and largest error against the exact solution, RMS difference from the 60/h and
30/h runs [C]) and observed_order.csv (orders fitted from 2 to 15 per hour against each of the
three references). Raw runs: <runs>/massive_wall/<method>_tsNN/.
Usage (repository root):
  python3 tests/massive_wall.py [--configuration release] [--runs runs] [--workers 12]
"""

import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402
import single_room as room  # noqa: E402

TIMESTEPS = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]
FIT_TS = [2, 3, 4, 5, 6, 10, 12, 15]
METHODS = {
    "CTF": "ConductionTransferFunction",
    "CondFD_CrankNicholson": "CrankNicholsonSecondOrder",
    "CondFD_FullyImplicit": "FullyImplicitFirstOrder",
}
WALL = {"L": 0.1, "k": 1.7, "rho": 2240.0, "cp": 840.0}  # m, W/m-K, kg/m3, J/kg-K
H_IN = 8.0     # W/m2-K, inside convection coefficient (fixed)
T_MEAN = 20.0  # C, zone air setpoint and mean outside face temperature
AMP = 10.0     # C, amplitude of the outside face temperature
PERIOD_H = 24.0

IDF = """
  Version,26.2;
  SimulationControl, No, No, No, Yes, No, No, 1;
  Building, MASSIVE WALL, 0, Suburbs, 0.04, 0.4, MinimalShadowing, 50, 20;
  Timestep,{ts};
  HeatBalanceAlgorithm,{hb};
  {condfd}
  ZoneAirHeatBalanceAlgorithm,ThirdOrderBackwardDifference;
  GlobalGeometryRules, UpperLeftCorner, Counterclockwise, Relative;
  Site:Location, Denver, 39.74, -105.18, -7.0, 1829.0;
  SizingPeriod:DesignDay, WINTER, 12, 21, WinterDesignDay, -15.5, 0.0, , , Wetbulb, -15.5, , , , ,
    81198., 3, 340, No, No, No, ASHRAEClearSky, , , , , 0.00;
  Site:GroundTemperature:BuildingSurface, {t0}, {t0}, {t0}, {t0}, {t0}, {t0}, {t0}, {t0}, {t0}, {t0}, {t0}, {t0};

  Material, SLAB, Smooth, {L}, {k}, {rho}, {cp}, 0.0001, 0.0001, 0.0001;
  Material:NoMass, ADIABATIC LAYER, Smooth, 1.0, 0.0001, 0.0001, 0.0001;
  Construction, TEST WALL CONSTRUCTION, SLAB;
  Construction, ADIABATIC CONSTRUCTION, ADIABATIC LAYER;

  SurfaceProperty:OtherSideCoefficients, SINE FACE, 0, {amp}, 1, 0, 1, 0, 0, , Yes, {period};
  SurfaceProperty:ConvectionCoefficients, TEST WALL, Inside, Value, {h_in};

  Zone, ZONE ONE;
  BuildingSurface:Detailed, TEST WALL, Wall, TEST WALL CONSTRUCTION, ZONE ONE, , OtherSideCoefficients,
    SINE FACE, NoSun, NoWind, , 4, 0,0,1, 0,0,0, 1,0,0, 1,0,1;
  BuildingSurface:Detailed, NORTH, Wall, ADIABATIC CONSTRUCTION, ZONE ONE, , Adiabatic, , NoSun, NoWind, , 4,
    1,1,1, 1,1,0, 0,1,0, 0,1,1;
  BuildingSurface:Detailed, EAST, Wall, ADIABATIC CONSTRUCTION, ZONE ONE, , Adiabatic, , NoSun, NoWind, , 4,
    1,0,1, 1,0,0, 1,1,0, 1,1,1;
  BuildingSurface:Detailed, WEST, Wall, ADIABATIC CONSTRUCTION, ZONE ONE, , Adiabatic, , NoSun, NoWind, , 4,
    0,1,1, 0,1,0, 0,0,0, 0,0,1;
  BuildingSurface:Detailed, FLOOR, Floor, ADIABATIC CONSTRUCTION, ZONE ONE, , Adiabatic, , NoSun, NoWind, , 4,
    0,0,0, 0,1,0, 1,1,0, 1,0,0;
  BuildingSurface:Detailed, ROOF, Roof, ADIABATIC CONSTRUCTION, ZONE ONE, , Adiabatic, , NoSun, NoWind, , 4,
    0,1,1, 0,0,1, 1,0,1, 1,1,1;

  HVACTemplate:Thermostat, CONSTANT, , {t0}, , {t0};
  HVACTemplate:Zone:IdealLoadsAirSystem, ZONE ONE, CONSTANT;

  Output:SQLite,Simple;
  Output:Variable, TEST WALL, Surface Inside Face Temperature, Timestep;
  Output:Variable, TEST WALL, Surface Outside Face Temperature, Timestep;
  Output:Variable, *, Zone Mean Air Temperature, Timestep;
"""

CONDFD = "HeatBalanceSettings:ConductionFiniteDifference, {scheme}, 3, 1.0, 0.002;"


def make_idf(method, ts):
    scheme = METHODS[method]
    hb = "ConductionTransferFunction" if method == "CTF" else "ConductionFiniteDifference"
    condfd = "" if method == "CTF" else CONDFD.format(scheme=scheme)
    return IDF.format(ts=ts, hb=hb, condfd=condfd, t0=T_MEAN, amp=AMP, period=PERIOD_H, h_in=H_IN,
                      **WALL)


H_OUT_CONDFD = 1000.0  # W/m2-K. CondFD applies this boundary through HighHConvLimit, not as a set face
                       # temperature (HeatBalanceSurfaceManager.cc, OtherSideCoefNoCalcExt branch).


def exact(t_h, h_out=None):
    """Steady-periodic outside and inside face temperatures of the slab at times t_h (hours).
    Boundary temperature T_b = T_MEAN + AMP sin(w t). Outside face (x=0): T = T_b if h_out is None,
    else -k dT/dx = h_out (T_b - T). Inside face (x=L): -k dT/dx = H_IN (T - T_MEAN)."""
    L, k = WALL["L"], WALL["k"]
    alpha = k / (WALL["rho"] * WALL["cp"])
    w = 2 * np.pi / (PERIOD_H * 3600.0)
    lam = np.sqrt(1j * w / alpha)
    tb = -1j * AMP  # AMP sin(wt) = Re[-i AMP exp(iwt)]
    ch, sh = np.cosh(lam * L), np.sinh(lam * L)
    # theta(x) = c1 cosh(lam x) + c2 sinh(lam x); inside condition gives c2 = -c1 * r
    r = (H_IN * ch + k * lam * sh) / (k * lam * ch + H_IN * sh)
    if h_out is None:
        c1 = tb
    else:  # -k theta'(0) = h_out (tb - theta(0)), with theta'(0) = lam c2 = -lam r c1
        c1 = h_out * tb / (h_out + k * lam * r)
    c2 = -c1 * r
    theta_in = c1 * ch + c2 * sh
    phase = np.exp(1j * w * np.asarray(t_h) * 3600.0)
    return T_MEAN + np.real(c1 * phase), T_MEAN + np.real(theta_in * phase)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--configuration", default="release", help="name from configurations.py")
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(REPO / "results" / "massive_wall"))
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    eplus, extra = C.program(a.configuration)
    runs = Path(a.runs) / "massive_wall"
    results = Path(a.results)
    results.mkdir(parents=True, exist_ok=True)

    cases = [(m, ts) for m in METHODS for ts in TIMESTEPS]
    # The ideal air system is an HVACTemplate object, so ExpandObjects runs first (-x).
    jobs = [(str(eplus), make_idf(m, ts), f"{m}_ts{ts:02d}", str(runs), True, extra) for m, ts in cases]
    with ProcessPoolExecutor(a.workers) as ex:
        log = pd.DataFrame(list(ex.map(room.run, jobs)))
    for i, (m, ts) in enumerate(cases):
        err = (runs / log.name[i] / "eplusout.err").read_text(errors="replace")
        log.loc[i, "n_severe"] = err.count("** Severe  **")
        log.loc[i, "n_warning"] = err.count("** Warning **")
    log.to_csv(results / "run_log.csv", index=False)
    if (log.returncode != 0).any():
        print(log[log.returncode != 0])
        sys.exit(1)

    frames = []
    for (m, ts), name in zip(cases, log.name):
        df = room.hour_end_series(runs / name / "eplusout.sql")
        df["t_h"] = df.hour + df.minute / 60.0  # SQL Time: Hour=1, Minute=0 is the end of hour 1
        df = df[np.isclose(df.t_h, df.t_h.round())].copy()
        df["t_h"] = df.t_h.round().astype(int)
        df["method"], df["ts"] = m, ts
        frames.append(df)
    v = pd.concat(frames)
    t_out, t_in = exact(v.t_h.to_numpy())
    f_out, f_in = exact(v.t_h.to_numpy(), H_OUT_CONDFD)
    fd = v.method.str.startswith("CondFD").to_numpy()
    t_out, t_in = np.where(fd, f_out, t_out), np.where(fd, f_in, t_in)
    v["exact"] = np.where(v["var"] == "Surface Outside Face Temperature", t_out,
                          np.where(v["var"] == "Surface Inside Face Temperature", t_in, T_MEAN))
    v["e"] = v.value - v.exact
    v[["method", "ts", "var", "t_h", "value", "exact"]].to_csv(results / "hour_end_values.csv.gz", index=False)

    # The CTF grid has 6 nodes per layer up to 30/h and 9 at 60/h for this slab (node spacing
    # sqrt(2 alpha dt), 6 to 19 nodes; Construction.cc). Errors against the 30/h run therefore
    # measure the time error on a fixed grid.
    keys = ["method", "var"]
    for rts in (60, 30):
        ref = v[v.ts == rts].set_index(keys + ["t_h"]).value.rename(f"ref{rts}")
        v = v.join(ref, on=keys + ["t_h"])
        v[f"e{rts}"] = v.value - v[f"ref{rts}"]
    g = v.groupby(keys + ["ts"])
    err = pd.DataFrame({
        "n": g.e.size(),
        "rms_err_exact_C": g.e.apply(lambda e: float(np.sqrt((e ** 2).mean()))),
        "max_abs_err_exact_C": g.e.apply(lambda e: float(e.abs().max())),
        "rms_err_vs_ts60_C": g.e60.apply(lambda e: float(np.sqrt((e ** 2).mean()))),
        "rms_err_vs_ts30_C": g.e30.apply(lambda e: float(np.sqrt((e ** 2).mean()))),
    }).reset_index()
    err.to_csv(results / "errors.csv", index=False, float_format="%.6g")

    orders = []
    for (m, var), d in err[err.ts.isin(FIT_TS)].groupby(keys):
        row = {"method": m, "var": var}
        for col, lab in (("rms_err_exact_C", "order_vs_exact"), ("rms_err_vs_ts60_C", "order_vs_ts60"),
                         ("rms_err_vs_ts30_C", "order_vs_ts30")):
            dd = d[d[col] > 0]
            row[lab] = (round(float(np.polyfit(np.log(60.0 / dd.ts), np.log(dd[col]), 1)[0]), 2)
                        if len(dd) >= 3 else np.nan)
        orders.append(row)
    orders = pd.DataFrame(orders)
    orders.to_csv(results / "observed_order.csv", index=False)

    pd.set_option("display.width", 220)
    for var in ("Surface Inside Face Temperature", "Surface Outside Face Temperature",
                "Zone Mean Air Temperature"):
        print(f"\n{var}: RMS error vs exact [C]")
        print(err[err["var"] == var].pivot_table(index="method", columns="ts", values="rms_err_exact_C")
              .to_string(float_format=lambda x: f"{x:.2e}"))
    print("\nObserved order:")
    print(orders.to_string(index=False))
    print(f"\nWarnings/severe: {log[['n_warning', 'n_severe']].sum().to_dict()}")


if __name__ == "__main__":
    main()
