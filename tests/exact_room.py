"""Room with an exact solution: the zone air temperature of each configuration against a reference
computed outside EnergyPlus, over a year of Denver weather (the paper's Figure 2).

Room: the single-zone example file (1ZoneUncontrolled.idf; 15.24 x 15.24 x 4.572 m, four walls and
a roof to outdoors, adiabatic floor, no windows, no infiltration), made exactly solvable:
  - no internal gains: the file's two OtherEquipment objects are removed;
  - massless surfaces: walls R13LAYER and roof R31LAYER are already Material:NoMass; the 4 in
    concrete floor is replaced by a NoMass layer of the same resistance (it is adiabatic);
  - fixed convection: inside 3.0 W/(m2 K) on every surface, outside 20.0 W/(m2 K) on walls and roof
    (SurfaceProperty:ConvectionCoefficients, Value);
  - no long-wave exchange: thermal absorptance 1e-5 on every face; no solar: solar and visible
    absorptance 0;
  - outdoor air temperature equal at every height (Site:HeightVariation gradient 0) and no rain or
    snow indicators (rain sets wet exterior faces to the wet-bulb temperature);
  - weather file period only, third-order scheme stated explicitly.
Each surface temperature is then algebraic in the air and outdoor temperatures, and the zone air
obeys V rho cp dT/dt = UA (To(t) - T), with rho = Pb / (287 (T + 273.15) (1 + 1.6077687 w)) and
cp = 1004.84 + 1858.95 w as in EnergyPlus (Psychrometrics.hh). To and Pb are the hourly weather
values interpolated linearly between hour ends, as EnergyPlus forms its timestep values
(WeatherManager.cc); the script checks this against the values EnergyPlus reports. Nothing adds
moisture, but EnergyPlus caps the humidity ratio w at saturation, so w falls in a few steps over the
year; the reference takes the converged configuration's 60/h history of w as an input (it enters
only rho cp, a 0.06% effect). Areas, volume and resistances come from the input file.
The equation is integrated hour by hour with DOP853 at rtol = atol = 1e-12, and again with Radau as
a check; the first day is repeated until periodic, as EnergyPlus's warmup does, then the year runs.
EnergyPlus may subdivide its HVAC timestep; the comparison uses "Zone Air Temperature" at the end of
each zone timestep (Detailed output, last value in each zone step). Days 1-2 are excluded
(start-up; the room's time constant is about 2 h).
Writes results/exact_room/: run_log.csv, surface_constants.csv (area [m2], R [m2 K/W] and U
[W/(m2 K)] per surface), forcing_check.csv (largest difference between the reported and the
interpolated weather, from day 2), solution_checks.csv (zone volume, UA, largest difference
between the DOP853 and Radau solutions, and how much the humidity ratio moves rho cp over the
year; with --reference only the first two), exact_solution.csv.gz (T_ref_C at each
minute of the year), errors.csv (per configuration and timestep: RMS, largest and mean error at zone timestep ends;
RMS error of the reported hourly mean; the RMS error that averaging the exact solution at the
timestep ends would give, which isolates the hourly reporting rule; all [C]) and order.csv (order
fitted from 4 to 20 per hour). Raw runs: <runs>/exact_room/<configuration>_tsNN/.
Usage (repository root):
  python3 tests/exact_room.py [--configurations release ...] [--timesteps 4 6 ...] [--runs runs]
                              [--no-runs] [--reference results/exact_room/exact_solution.csv.gz]
"""

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402

RESULTS = REPO / "results" / "exact_room"
EPW = REPO / "weather" / "USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw"
BASE = C.RELEASE / "ExampleFiles" / "1ZoneUncontrolled.idf"
STEPS = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]
CONFIGURATIONS = ["release", "one_pass", "two_passes", "converged"]
HI, HO, ABS_T = 3.0, 20.0, 1e-5  # W/(m2 K) inside and outside; thermal absorptance
FIT = [4, 5, 6, 10, 12, 15, 20]  # 15 to 3 min
START = 2880  # first compared minute of the year: day 3


def strip(text, cls):
    return re.sub(rf"^\s*{re.escape(cls)},[^;]*;", "", text, flags=re.M | re.I)


def sub1(pat, rep, text):
    new, n = re.subn(pat, rep, text, count=1, flags=re.M)
    if n != 1:
        raise ValueError(pat)
    return new


def surfaces(text):
    """(name, type, boundary, area, construction) for every BuildingSurface:Detailed, area from its
    vertices."""
    out = []
    for body in re.findall(r"^\s*BuildingSurface:Detailed,([^;]*);", text, re.M | re.I):
        vals = [v.strip() for v in re.sub(r"!.*", "", body).split(",")]
        # Name, Type, Construction, Zone, Space, Boundary, Boundary object, Sun, Wind, VF, N, vertices
        name, typ, bc = vals[0], vals[1], vals[5]
        nv = int(vals[10]) if vals[10] else None
        xyz = np.array([float(v) for v in vals[11:11 + 3 * nv]]).reshape(nv, 3)
        a = 0.5 * np.linalg.norm(sum(np.cross(xyz[k], xyz[(k + 1) % nv]) for k in range(nv)))
        out.append((name, typ, bc, a, vals[2]))
    return out


def make_idf(ts):
    t = BASE.read_text()
    for cls in ("Output:Variable", "Output:Meter:MeterFileOnly", "Output:Meter", "SimulationControl",
                "Timestep", "SizingPeriod:DesignDay", "OtherEquipment"):
        t = strip(t, cls)
    t = sub1(r"Yes,(\s*!- Use Weather File Rain Indicators)", r"No,\1", t)
    t = sub1(r"Yes;(\s*!- Use Weather File Snow Indicators)", r"No;\1", t)
    t = sub1(r"C5 - 4 IN HW CONCRETE;(\s*!- Outside Layer)", r"FLOOR NOMASS;\1", t)
    t = re.sub(r"[0-9.]+(,\s*!- Thermal Absorptance)", rf"{ABS_T}\1", t)
    t = re.sub(r"[0-9.]+(,\s*!- Solar Absorptance)", r"0.0\1", t)
    t = re.sub(r"[0-9.]+(;\s*!- Visible Absorptance)", r"0.0\1", t)
    conv = "".join(
        f"\n  SurfaceProperty:ConvectionCoefficients, {n}, Inside, Value, {HI}, , "
        + (f", Outside, Value, {HO}, , ;" if bc.lower() == "outdoors" else ";")
        for n, _, bc, _, _ in surfaces(t))
    # Site:HeightVariation: wind exponent and boundary layer as default, temperature gradient 0.
    return t + f"""
  SimulationControl, No, No, No, No, Yes, No, 1;
  Timestep,{ts};
  ZoneAirHeatBalanceAlgorithm,ThirdOrderBackwardDifference;
  Material:NoMass, FLOOR NOMASS, MediumRough, 0.05868, {ABS_T}, 0.0, 0.0;
  Site:HeightVariation, 0.22, 370.0, 0.0;{conv}
  Output:SQLite,Simple;
  Output:Variable, *, Zone Air Temperature, Detailed;
  Output:Variable, *, Zone Mean Air Temperature, Hourly;
  Output:Variable, *, Zone Air Humidity Ratio, Timestep;
  Output:Variable, *, Site Outdoor Air Drybulb Temperature, Timestep;
  Output:Variable, *, Site Outdoor Air Barometric Pressure, Timestep;
  Output:Variable, *, Surface Inside Face Convection Heat Transfer Coefficient, Timestep;
  Output:Variable, *, Surface Outside Face Convection Heat Transfer Coefficient, Timestep;
"""


def run(job):
    conf, ts, runs = job
    d = Path(runs) / f"{conf}_ts{ts:02d}"
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(make_idf(ts))
    eplus, extra = C.program(conf)
    p = subprocess.run([str(eplus / "energyplus"), "-w", str(EPW), "-d", str(d), "in.idf"], cwd=d,
                       env=C.run_environment(extra), capture_output=True, text=True)
    err = (d / "eplusout.err").read_text(errors="replace")
    return {"configuration": conf, "ts": ts, "completed": "EnergyPlus Completed Successfully" in err,
            "n_warning": len(re.findall(r"\*\* Warning \*\*", err)), "returncode": p.returncode}


def series(d, var, freq=None):
    con = sqlite3.connect(d / "eplusout.sql")
    q = f"""SELECT t.Month, t.Day, t.Hour, t.Minute, t.Interval, k.KeyValue, r.Value
            FROM ReportData r JOIN ReportDataDictionary k ON r.ReportDataDictionaryIndex=k.ReportDataDictionaryIndex
            JOIN Time t ON r.TimeIndex=t.TimeIndex
            WHERE k.Name='{var}' AND t.WarmupFlag=0
            {"AND k.ReportingFrequency='" + freq + "'" if freq else ""}
            ORDER BY t.TimeIndex"""
    df = pd.read_sql(q, con)
    con.close()
    return df


def minute_of_year(df):
    doy = pd.to_datetime(dict(year=2001, month=df.Month, day=df.Day)).dt.dayofyear
    return (doy - 1) * 1440 + df.Hour * 60 + df.Minute  # SQL Time: Hour 0-24 and Minute 0-59 of the end time


def epw():
    w = pd.read_csv(EPW, skiprows=8, header=None)
    return w[6].to_numpy(float), w[9].to_numpy(float)  # dry bulb C, pressure Pa (hour ends 1..8760)


def forcing(vals):
    """Value at minute m of the year (m = 0 .. 525600), linear between hour ends; hour 0 = hour 24 of
    day 1 (EnergyPlus's previous hour on the first day)."""
    v = np.concatenate([[vals[23]], vals])
    return lambda m: np.interp(m / 60.0, np.arange(len(v)), v)


def reference(ua, vol, w, method="DOP853"):
    """w: zone humidity ratio per minute of the year (w[m] holds over minute m-1 to m)."""
    tdb, pb = epw()
    To, Pb = forcing(tdb), forcing(pb)
    w = np.maximum(np.asarray(w, float), 1e-5)
    cp = 1.00484e3 + w * 1.85895e3
    k = 1.0 + 1.6077687 * w

    def f(t, T):  # t in minutes
        i = min(max(int(np.ceil(t)), 1), len(w) - 1)
        rho = Pb(t) / (287.0 * (T + 273.15) * k[i])
        return 60.0 * ua * (To(t) - T) / (vol * rho * cp[i])

    def integrate(T0, h0, h1):
        # Hour by hour: the forcing is smooth within an hour and has a kink at each hour end.
        out = [np.array([T0])]
        for h in range(h0, h1):
            s = solve_ivp(f, (60 * h, 60 * h + 60), [out[-1][-1]], method=method, rtol=1e-12, atol=1e-12,
                          t_eval=np.arange(60 * h + 1, 60 * h + 61))
            out.append(s.y[0])
        return np.concatenate(out)

    T0 = float(To(0))
    for _ in range(25):  # warmup: repeat day 1 until periodic
        day = integrate(T0, 0, 24)
        if abs(day[-1] - T0) < 1e-10:
            break
        T0 = day[-1]
    return integrate(T0, 0, 8760)  # index m = minute of year


def room_constants():
    """UA [W/K] and volume [m3] of the room, and one row per surface, from the input file only."""
    t = make_idf(4)
    surf = surfaces(t)
    cons = {}
    for body in re.findall(r"^\s*Construction,([^;]*);", t, re.M | re.I):
        f = [re.sub(r"!.*", "", x).strip().rstrip(",") for x in body.split("\n") if re.sub(r"!.*", "", x).strip()]
        cons[f[0].upper()] = f[1:]
    rmat = {}
    for body in re.findall(r"^\s*Material:NoMass,([^;]*);", t, re.M | re.I):
        f = [x.strip() for x in re.sub(r"!.*", "", body).replace("\n", " ").split(",")]
        rmat[f[0].upper()] = float(f[2])
    ua, rows = 0.0, []
    for name, typ, bc, a, c in surf:
        r = sum(rmat[m.upper()] for m in cons[c.upper()])
        u = 1.0 / (1.0 / HO + r + 1.0 / HI) if bc.lower() == "outdoors" else 0.0
        ua += u * a
        rows.append({"surface": name, "type": typ, "boundary": bc, "area_m2": a, "R": r, "U": u})
    floor = sum(a for _, typ, _, a, _ in surf if typ.lower() == "floor")
    zmax = max(float(z) for z in re.findall(r"[-\d.]+,[-\d.]+,([-\d.]+);?\s*!- X,Y,Z", t))
    return ua, floor * zmax, rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--configurations", nargs="+", default=CONFIGURATIONS)
    ap.add_argument("--timesteps", nargs="+", type=int, default=STEPS)
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--workers", type=int, default=0, help="0 (default): one per run")
    ap.add_argument("--no-runs", action="store_true", help="reuse the EnergyPlus runs in --runs")
    ap.add_argument("--reference", help="reuse this exact solution (exact_solution.csv.gz) instead of "
                                        "integrating; needed when the converged 60/h run is absent")
    a = ap.parse_args()
    runs = Path(a.runs).resolve() / "exact_room"
    out = Path(a.results)
    out.mkdir(parents=True, exist_ok=True)
    if not a.no_runs:
        jobs = [(e, ts, str(runs)) for e in a.configurations for ts in a.timesteps]
        with ProcessPoolExecutor(a.workers or len(jobs)) as ex:
            log = pd.DataFrame(list(ex.map(run, jobs)))
        log.to_csv(out / "run_log.csv", index=False)
        print(log[~log.completed])

    ua, vol, rows = room_constants()
    print(f"UA {ua:.3f} W/K, volume {vol:.2f} m3")
    d0 = runs / "release_ts60"
    if d0.exists():
        hc = series(d0, "Surface Inside Face Convection Heat Transfer Coefficient").Value
        ho = series(d0, "Surface Outside Face Convection Heat Transfer Coefficient")
        print(f"inside h {hc.min()}..{hc.max()}, outside h (exterior faces) "
              f"{ho[ho.Value > 0].Value.min()}..{ho.Value.max()}")

    # Forcing check: EnergyPlus's timestep values against the interpolated weather file.
    tdb, pb = epw()
    chk = []
    for ts in (1, 4, 60):
        if not (runs / f"release_ts{ts:02d}").exists():
            continue
        for var, v in (("Site Outdoor Air Drybulb Temperature", tdb), ("Site Outdoor Air Barometric Pressure", pb)):
            s = series(runs / f"release_ts{ts:02d}", var)
            m = minute_of_year(s).to_numpy()
            k = m >= 1440  # day 1: EnergyPlus starts its interpolation from its own initial value
            chk.append({"ts": ts, "var": var,
                        "max_abs_diff": float(np.abs(s.Value.to_numpy()[k] - forcing(v)(m[k])).max())})
    pd.DataFrame(chk).to_csv(out / "forcing_check.csv", index=False)
    print(pd.DataFrame(chk).to_string(index=False))

    # Numbers quoted in the paper's description of the reference (quantity, value, unit).
    checks = [("zone_volume", vol, "m3"), ("UA", ua, "W/K")]
    if a.reference:
        ref = pd.read_csv(a.reference).T_ref_C.to_numpy()
    else:
        # Zone humidity ratio of the converged configuration at 60/h, per minute of the year.
        hs = series(runs / "converged_ts60", "Zone Air Humidity Ratio")
        w = np.empty(525601)
        w[minute_of_year(hs).to_numpy()] = hs.Value.to_numpy()
        w[0] = w[1]
        print(f"humidity ratio {w.max():.6g} to {w.min():.6g}, {int((np.diff(w) != 0).sum())} changes")
        ref = reference(ua, vol, w)
        ref2 = reference(ua, vol, w, "Radau")
        print(f"reference: DOP853 vs Radau max difference {np.abs(ref - ref2).max():.2e} C")
        # How much the humidity ratio moves rho cp over the year: rho cp relative to dry air at the
        # same T and Pb is cp(w) / (1 + 1.6077687 w) / cp(0); its spread between the highest and
        # lowest w, with w as the reference uses it.
        wc = np.maximum(w, 1e-5)
        effect = 100 * ((1.00484e3 + wc * 1.85895e3) / (1.0 + 1.6077687 * wc) / 1.00484e3 - 1)
        checks += [("max_abs_DOP853_minus_Radau", float(np.abs(ref - ref2).max()), "C"),
                   ("humidity_effect_on_rho_cp_range", float(effect.max() - effect.min()), "%")]
        pd.DataFrame({"minute": np.arange(len(ref)), "T_ref_C": ref}).to_csv(out / "exact_solution.csv.gz",
                                                                              index=False, float_format="%.10g")
    pd.DataFrame(rows).to_csv(out / "surface_constants.csv", index=False)
    pd.DataFrame(checks, columns=["quantity", "value", "unit"]).to_csv(out / "solution_checks.csv", index=False,
                                                                        float_format="%.6g")
    # True hourly mean (trapezoid on the 1-min grid; the solution is smooth within the minute).
    trapz = getattr(np, "trapezoid", None) or np.trapz  # np.trapz is deprecated from NumPy 2.0
    hourly_ref = np.array([trapz(ref[60 * h: 60 * h + 61]) / 60.0 for h in range(8760)])

    errs = []
    for e in a.configurations:
        for ts in a.timesteps:
            d = runs / f"{e}_ts{ts:02d}"
            z = series(d, "Zone Air Temperature")
            m = minute_of_year(z).to_numpy()
            step = 60 // ts
            keep = (m % step == 0) & (m >= START)
            # last value at each zone-step end (subdivided HVAC steps report their own end times)
            zz = pd.Series(z.Value.to_numpy()[keep], index=m[keep]).groupby(level=0).last()
            dev = zz.to_numpy() - ref[zz.index.to_numpy()]
            hm = series(d, "Zone Mean Air Temperature", "Hourly")
            hidx = (minute_of_year(hm).to_numpy() // 60) - 1
            ok = hidx >= START // 60
            dh = hm.Value.to_numpy()[ok] - hourly_ref[hidx[ok]]
            # What averaging the exact solution at this timestep's step ends gives (reporting rule).
            rule = np.array([ref[60 * h + step: 60 * h + 61: step].mean() for h in range(8760)])
            errs.append({"configuration": e, "ts": ts, "n_points": len(zz), "n_substep_values": int((~keep).sum()),
                         "rms_hourly_rule_C": float(np.sqrt(np.mean((rule - hourly_ref)[START // 60:] ** 2))),
                         "rms_C": float(np.sqrt(np.mean(dev ** 2))), "max_abs_C": float(np.abs(dev).max()),
                         "mean_C": float(dev.mean()), "rms_hourly_mean_C": float(np.sqrt(np.mean(dh ** 2)))})
    er = pd.DataFrame(errs)
    er.to_csv(out / "errors.csv", index=False, float_format="%.6g")
    orders = []
    for e, g in er.groupby("configuration"):
        g = g[g.ts.isin(FIT)]
        if len(g) < len(FIT):  # a partial rerun without the whole fit window
            continue
        for meas in ("rms_C", "rms_hourly_mean_C"):
            orders.append({"configuration": e, "measure": meas,
                           "order": np.polyfit(np.log(60.0 / g.ts), np.log(g[meas]), 1)[0]})
    od = pd.DataFrame(orders, columns=["configuration", "measure", "order"])
    od.to_csv(out / "order.csv", index=False, float_format="%.3g")
    pd.set_option("display.width", 200)
    print(er.pivot(index="ts", columns="configuration", values="rms_C").to_string())
    print(er.pivot(index="ts", columns="configuration", values="n_substep_values").to_string())
    print(od.to_string(index=False))


if __name__ == "__main__":
    main()
