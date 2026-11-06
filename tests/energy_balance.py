"""Zone air energy balance and fan meter with the passes on, against the release.

Runs:
  room      single_room.py's "ideal" case, both design days, 4 per hour, all three zone air
            schemes; release, two_passes and converged.
  office    medium office prototype, Denver, annual, 6 per hour as distributed; zone
            PERIMETER_BOT_ZN_1; release and two_passes.
  hospital  hospital prototype, Denver, annual, 6 per hour; zone ICU_FLR_2; release and two_passes.
Inputs are the room input of single_room.py and the prototype study inputs
(<PROTOTYPES>/study/<case>_base.idf from study/prepare_inputs.py), plus output requests only. The
surfaces of each prototype zone are read from the study's release run of the same input
(<runs>/prototype_cases/<case>/base_release/eplusout.sql, from study/run_cases.py).
Per zone timestep (Timestep frequency, so subdivided HVAC steps are averaged), from the zone air
heat balance report (ZoneTempPredictorCorrector.cc, CalcZoneComponentLoadSums), all in W:
  residual  internal convective gains + surface convection + interzone air + outdoor air
            (infiltration and ventilation) + system air + system convective gains - air energy
            storage. "Zone Air Heat Balance Deviation Rate" is filled only with the developer
            diagnostic DisplayZoneAirHeatBalanceOffBalance and reads 0 otherwise, so it is not used.
            The storage term is the scheme's own: third-order (MAT - ZTM1) C / dt, Euler
            (MAT - T1) C / dt, analytical (TempIndCoef - TempDepCoef MAT), so the third-order
            residual is not zero even in the release.
  HVAC load = system air + system convective gains.
  surface-air mismatch = air-side surface convection (sum hA (Ts - Tz_new)) + surface-side
            convection ("Surface Inside Face Convection Heat Gain Rate" summed over the zone's
            surfaces, positive into the face, = -hA (Ts - Tz used by the surface balance))
            = sum hA (Tz_used - Tz_new): heat that leaves the surfaces in one balance and does not
            arrive in the other. It is the lag itself, and zero when surfaces and air agree.
Fan meter: per timestep, the Fans:Electricity meter against the sum of "Fan Electricity Energy" over
all fans (office and hospital); a meter that accumulated once per pass would exceed the sum.
Writes results/passes/energy_balance.csv (one row per run, environment and zone; columns ending
_W in W, ratios dimensionless) and energy_balance_meters.csv (energies in J). Raw runs:
<runs>/energy_balance/.
Usage (repository root):
  python3 tests/energy_balance.py [--cases room office hospital] [--runs runs] [--no-runs]
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

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402
import single_room as room  # noqa: E402

RESULTS = REPO / "results" / "passes"
HB = ["Internal Convective Heat Gain Rate", "Surface Convection Rate", "Interzone Air Transfer Rate",
      "Outdoor Air Transfer Rate", "System Air Transfer Rate", "System Convective Heat Gain Rate",
      "Air Energy Storage Rate", "Deviation Rate"]
PROTO = {"office": ("OfficeMedium_Denver", "PERIMETER_BOT_ZN_1"), "hospital": ("Hospital_Denver", "ICU_FLR_2")}
ROOM_CONFIGURATIONS = ["release", "two_passes", "converged"]
PROTO_CONFIGURATIONS = ["release", "two_passes"]


def outputs(zone, surfaces, meters):
    t = "".join(f"\n  Output:Variable, {zone}, Zone Air Heat Balance {v}, Timestep;" for v in HB)
    t += "".join(f"\n  Output:Variable, {s}, Surface Inside Face Convection Heat Gain Rate, Timestep;" for s in surfaces)
    if meters:
        t += "\n  Output:Meter, Fans:Electricity, Timestep;\n  Output:Variable, *, Fan Electricity Energy, Timestep;"
    return t + "\n"


def zone_surfaces(runs, case, zone):
    sql = runs / "prototype_cases" / case / "base_release" / "eplusout.sql"
    if not sql.exists():
        sys.exit(f"missing {sql}; run study/run_cases.py --cases {case} --configurations release first")
    con = sqlite3.connect(sql)
    s = [r[0] for r in con.execute("SELECT s.SurfaceName FROM Surfaces s JOIN Zones z ON s.ZoneIndex = z.ZoneIndex "
                                   "WHERE z.ZoneName = ? AND s.ClassName != 'Shading'", (zone,))]
    con.close()
    return s


def room_job(j):
    algo, conf, out = j
    eplus, extra = C.program(conf)
    base = (C.RELEASE / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()
    idf = room.make_idf(base, "ideal", 4, algo) + outputs("ZONE ONE", ["*"], False)
    r = room.run((str(eplus), idf, f"room/{algo}_{conf}", str(out), True, extra))
    return r | {"run": f"room/{algo}_{conf}"}


def proto_job(j):
    """Annual run of a prototype input; ExpandObjects first if it holds HVACTemplate objects."""
    key, conf, out, weather = j
    case, _ = PROTO[key]
    eplus, extra = C.program(conf)
    d = Path(out) / key / conf
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    shutil.copy(Path(out) / "inputs" / f"{case}.idf", d / "in.idf")
    args = [str(eplus / "energyplus"), "-w", str(weather), "-d", str(d)]
    if re.search(r"^\s*HVACTemplate:", (d / "in.idf").read_text(errors="replace"), re.M | re.I):
        args.append("-x")
    subprocess.run(args + ["in.idf"], cwd=d, env=C.run_environment(extra), capture_output=True, text=True)
    err = (d / "eplusout.err").read_text(errors="replace") if (d / "eplusout.err").exists() else ""
    return {"run": f"{key}/{conf}", "completed": "EnergyPlus Completed Successfully" in err}


def read(d, names):
    con = sqlite3.connect(d / "eplusout.sql")
    q = f"""SELECT ep.EnvironmentName AS env, rd.TimeIndex AS t, rdd.Name AS var, rdd.KeyValue AS key, rd.Value AS value
            FROM ReportData rd JOIN ReportDataDictionary rdd USING (ReportDataDictionaryIndex)
            JOIN Time ti ON rd.TimeIndex = ti.TimeIndex
            JOIN EnvironmentPeriods ep ON ti.EnvironmentPeriodIndex = ep.EnvironmentPeriodIndex
            WHERE ti.WarmupFlag = 0 AND rdd.ReportingFrequency IN ('Zone Timestep', 'Timestep')
            AND ({' OR '.join(f"rdd.Name LIKE '{n}'" for n in names)})"""
    df = pd.read_sql(q, con)
    con.close()
    return df


def closure(d, zone):
    df = read(d, ["Zone Air Heat Balance %", "Surface Inside Face Convection Heat Gain Rate"])
    rows = []
    for env, g in df.groupby("env"):
        hb = g[g["var"].str.startswith("Zone Air Heat Balance") & (g.key.str.upper() == zone.upper())]
        w = hb.pivot_table(index="t", columns="var", values="value")
        w.columns = [c.replace("Zone Air Heat Balance ", "") for c in w.columns]
        res = (w["Internal Convective Heat Gain Rate"] + w["Surface Convection Rate"] + w["Interzone Air Transfer Rate"]
               + w["Outdoor Air Transfer Rate"] + w["System Air Transfer Rate"] + w["System Convective Heat Gain Rate"]
               - w["Air Energy Storage Rate"])
        hvac = w["System Air Transfer Rate"] + w["System Convective Heat Gain Rate"]
        sf = g[g["var"] == "Surface Inside Face Convection Heat Gain Rate"].groupby("t").value.sum()
        mis = (w["Surface Convection Rate"] + sf.reindex(w.index)).dropna()
        # Timesteps with the HVAC on: at least a tenth of the largest HVAC load.
        on = hvac.abs() >= 0.1 * hvac.abs().max() if hvac.abs().max() > 0 else hvac.abs() > np.inf
        rows.append({"env": env, "timesteps": len(w), "hvac_mean_abs_W": hvac.abs().mean(),
                     "hvac_max_abs_W": hvac.abs().max(),
                     "residual_max_abs_W": res.abs().max(), "residual_mean_abs_W": res.abs().mean(),
                     "residual_mean_abs_over_hvac_mean_abs": res.abs().mean() / hvac.abs().mean() if hvac.abs().mean() else np.nan,
                     "residual_max_over_hvac_when_on": (res.abs()[on] / hvac.abs()[on]).max() if on.any() else np.nan,
                     "mismatch_max_abs_W": mis.abs().max(), "mismatch_mean_abs_W": mis.abs().mean(),
                     "mismatch_mean_abs_over_hvac_mean_abs": mis.abs().mean() / hvac.abs().mean() if hvac.abs().mean() else np.nan,
                     "mismatch_sum_over_hvac_sum": mis.sum() / hvac.abs().sum() if hvac.abs().sum() else np.nan,
                     "surface_convection_mean_abs_W": w["Surface Convection Rate"].abs().mean()})
    return rows


def meters(d):
    df = read(d, ["Fans:Electricity", "Fan Electricity Energy"])
    out = []
    for env, g in df.groupby("env"):
        m = g[g["var"] == "Fans:Electricity"].groupby("t").value.sum()
        f = g[g["var"] == "Fan Electricity Energy"].groupby("t").value.sum()
        j = pd.concat([m, f], axis=1, keys=["meter", "sum"]).dropna()
        j = j[j["sum"] > 0]
        out.append({"env": env, "timesteps": len(j), "meter_J": j.meter.sum(), "sum_of_fans_J": j["sum"].sum(),
                    "max_rel_diff": float(((j.meter - j["sum"]).abs() / j["sum"]).max())})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--cases", nargs="+", default=["room", *PROTO], choices=["room", *PROTO])
    ap.add_argument("--configurations", nargs="+", default=ROOM_CONFIGURATIONS,
                    help="subset of release two_passes converged (the prototypes use the first two)")
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--no-runs", action="store_true", help="reuse the runs in <runs>/energy_balance")
    ap.add_argument("--workers", type=int, default=0, help="0 (default): one per run")
    a = ap.parse_args()
    runs = Path(a.runs).resolve()
    out = runs / "energy_balance"
    (out / "inputs").mkdir(parents=True, exist_ok=True)
    keys = [k for k in PROTO if k in a.cases]
    if keys:  # weather file of each prototype case, as listed by the study
        weather = pd.read_csv(REPO / "results" / "prototypes" / "sources.csv").set_index("case").weather
    for key in keys:
        case, zone = PROTO[key]
        t = (C.PROTOTYPES / "study" / f"{case}_base.idf").read_text(errors="replace")
        (out / "inputs" / f"{case}.idf").write_text(t + outputs(zone, zone_surfaces(runs, case, zone), True))
    room_cases = [(al, e) for al in room.ALGOS for e in ROOM_CONFIGURATIONS if e in a.configurations] \
        if "room" in a.cases else []
    proto = [(k, e) for k in keys for e in PROTO_CONFIGURATIONS if e in a.configurations]
    if not a.no_runs:
        with ProcessPoolExecutor(a.workers or len(room_cases) + len(proto)) as ex:
            fp = [ex.submit(proto_job, (k, e, str(out), C.PROTOTYPES / "weather" / weather[PROTO[k][0]]))
                  for k, e in proto]
            fr = [ex.submit(room_job, (al, e, str(out))) for al, e in room_cases]
            log = [f.result() for f in fp + fr]
        bad = [r for r in log if not (r.get("completed", r.get("returncode") == 0))]
        if bad:
            print("failed:", bad)
    rows, mrows = [], []
    for al, e in room_cases:
        rows += [{"run": "room", "scheme": al, "configuration": e, "zone": "ZONE ONE"} | r
                 for r in closure(out / "room" / f"{al}_{e}", "ZONE ONE")]
    for k, e in proto:
        case, zone = PROTO[k]
        d = out / k / e
        rows += [{"run": k, "scheme": "ThirdOrderBackwardDifference", "configuration": e, "zone": zone} | r
                 for r in closure(d, zone)]
        mrows += [{"run": k, "configuration": e} | r for r in meters(d)]
    res = Path(a.results)
    res.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(res / "energy_balance.csv", index=False, float_format="%.5g")
    pd.DataFrame(mrows).to_csv(res / "energy_balance_meters.csv", index=False, float_format="%.6g")
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 30)
    print(df.drop(columns=["zone"]).to_string(index=False))
    print(pd.DataFrame(mrows).to_string(index=False))


if __name__ == "__main__":
    main()
