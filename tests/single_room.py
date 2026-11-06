"""Single room on its two Denver design days, swept over timesteps and zone air schemes.

The room is the single-zone example file distributed with EnergyPlus (1ZoneUncontrolled.idf), run
in four cases: free (floating, as distributed), free_nosolar (sky clearness 0), free_nosolar_nomass
(also the concrete floor replaced by a massless layer of equal resistance) and ideal (an ideal air
system holding 21 to 24 C from 08:00 to 18:00 and 15 to 30 C otherwise). Each case runs with the
three zone air schemes at 1 to 60 timesteps per hour for each configuration asked for: the paper
uses the release, converged, and both_faces (surfaces and air solved to agreement with the HVAC
held at its first result; tests/hvac_held_fixed.py).
Writes results/single_room/<configuration>/hour_end_temperatures.csv.gz and run_log.csv; raw runs
go to <runs>/single_room/<configuration>/. The input edits and readers here are reused by the
other scripts in tests/.
Usage (repository root):
  python3 tests/single_room.py [--configurations release converged both_faces] [--cases free ...]
                               [--timesteps 4 30 ...] [--runs runs] [--workers 12]
"""

import argparse
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import configurations as C  # noqa: E402

RESULTS = REPO / "results" / "single_room"
# The paper's sweep. Every timestep in this list divides the hour, so all runs share the 24 hour
# ends, where they are compared.
TIMESTEPS = [1, 2, 3, 4, 5, 6, 10, 12, 15, 20, 30, 60]
ALGOS = ["ThirdOrderBackwardDifference", "AnalyticalSolution", "EulerMethod"]
CASES = ("free", "free_nosolar", "free_nosolar_nomass", "ideal")

# Setpoint band of the "ideal" case, with the ideal air system that holds it.
IDEAL = """
  Schedule:Compact, CoolSP, , Through: 12/31, For: AllDays,
    Until: 08:00, 30, Until: 18:00, 24, Until: 24:00, 30;
  Schedule:Compact, HeatSP, , Through: 12/31, For: AllDays,
    Until: 08:00, 15, Until: 18:00, 21, Until: 24:00, 15;
  HVACTemplate:Thermostat, Stepped, HeatSP, , CoolSP, ;
  HVACTemplate:Zone:IdealLoadsAirSystem, ZONE ONE, Stepped;
  Output:Variable, *, Zone Ideal Loads Zone Sensible Heating Energy, Timestep;
  Output:Variable, *, Zone Ideal Loads Zone Sensible Cooling Energy, Timestep;
"""


def strip_objects(text, cls):
    """Remove every object of class `cls` (case-insensitive) from IDF text."""
    pattern = re.compile(rf"^\s*{re.escape(cls)}\s*,.*?;[^\n]*\n", re.I | re.S | re.M)
    return pattern.sub("", text)


def make_idf(base, case, ts, algo):
    """Input of one run: `base` is the text of 1ZoneUncontrolled.idf."""
    text = strip_objects(base, "RunPeriod")
    text = strip_objects(text, "Timestep")
    text = strip_objects(text, "Output:Variable")
    text = strip_objects(text, "Output:Meter:MeterFileOnly")
    text = strip_objects(text, "SimulationControl")
    # Design days only (SimulationControl: run the sizing periods, not the weather file period).
    text += f"""
  SimulationControl, No, No, No, Yes, No, No, 1;
  Timestep,{ts};
  ZoneAirHeatBalanceAlgorithm,{algo};
  Output:SQLite,Simple;
  Output:Variable, *, Zone Mean Air Temperature, Timestep;
  Output:Variable, *, Surface Inside Face Temperature, Timestep;
"""
    if case == "ideal":
        text += IDEAL
    if case.startswith("free_nosolar"):
        # Sky clearness 0 on both SizingPeriod:DesignDay objects removes the solar gain.
        text = sub_once(r"1\.00;(\s*!- Sky Clearness)", r"0.00;\1", text)
    if case == "free_nosolar_nomass":
        # Same thermal resistance as the 4 in concrete floor (0.1015 m / 1.7296 W/m-K), no mass.
        text = sub_once(r"C5 - 4 IN HW CONCRETE;(\s*!- Outside Layer)", r"FLOOR NOMASS;\1", text)
        text += "\n  Material:NoMass, FLOOR NOMASS, MediumRough, 0.05868, 0.9, 0.65, 0.65;\n"
    return text


def sub_once(pattern, repl, text):
    new, n = re.subn(pattern, repl, text, count=1)
    if n != 1:
        raise ValueError(f"pattern not found: {pattern}")
    return new


def run(job):
    """Run one input. job = (install, idf text, run name, runs folder, expand, patch variables);
    expand runs ExpandObjects first (-x), which HVACTemplate objects need."""
    eplus, idf, name, runs, expand, extra = job
    d = (Path(runs) / name).resolve()  # EnergyPlus runs inside d, so -d must be absolute
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    (d / "in.idf").write_text(idf)
    cmd = [str(Path(eplus) / "energyplus"), "-d", str(d)] + (["-x"] if expand else []) + ["in.idf"]
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=d, env=C.run_environment(extra), capture_output=True, text=True)
    return {"name": name, "returncode": proc.returncode, "wall_s": round(time.time() - t0, 2)}


def hour_end_series(sql):
    """Every reported value after warmup, per environment (design day) and variable key.
    SQL Time: Hour 1-24 and Minute of the end of the interval; an hour end appears as Minute 0 or
    60 depending on the timestep."""
    con = sqlite3.connect(sql)
    q = """SELECT ep.EnvironmentName AS env, t.Hour AS hour, t.Minute AS minute,
                  rdd.Name AS var, rdd.KeyValue AS key, rd.Value AS value
           FROM ReportData rd
           JOIN ReportDataDictionary rdd ON rd.ReportDataDictionaryIndex = rdd.ReportDataDictionaryIndex
           JOIN Time t ON rd.TimeIndex = t.TimeIndex
           JOIN EnvironmentPeriods ep ON t.EnvironmentPeriodIndex = ep.EnvironmentPeriodIndex
           WHERE t.WarmupFlag = 0"""
    df = pd.read_sql(q, con)
    con.close()
    return df


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--configurations", nargs="+", default=["release", "converged", "both_faces"],
                    help="names from configurations.py (default: the three the paper uses)")
    ap.add_argument("--cases", nargs="+", default=list(CASES), choices=CASES)
    ap.add_argument("--timesteps", nargs="+", type=int, default=TIMESTEPS)
    ap.add_argument("--runs", default=str(REPO / "runs"), help="folder for raw runs")
    ap.add_argument("--results", default=str(RESULTS), help="folder for the summaries")
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    for conf in a.configurations:
        eplus, extra = C.program(conf)
        runs = Path(a.runs) / "single_room" / conf
        results = Path(a.results) / conf
        results.mkdir(parents=True, exist_ok=True)
        base = (eplus / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()

        cases = [(c, ts, al) for c in a.cases for al in ALGOS for ts in a.timesteps]
        jobs = [(str(eplus), make_idf(base, c, ts, al), f"{c}_{al}_ts{ts:02d}", str(runs), c == "ideal", extra)
                for c, ts, al in cases]
        with ProcessPoolExecutor(a.workers) as ex:
            log = pd.DataFrame(list(ex.map(run, jobs)))
        log.to_csv(results / "run_log.csv", index=False)
        if (log.returncode != 0).any():
            print(log[log.returncode != 0])

        frames = []
        for (c, ts, al), name in zip(cases, log.name):
            df = hour_end_series(runs / name / "eplusout.sql")
            df["case"], df["ts"], df["algo"] = c, ts, al
            frames.append(df)
        allv = pd.concat(frames)
        # Temperatures at the hour ends [C]; tests/single_room_orders.py and tests/order_estimates.py
        # compute the errors and orders from this file.
        temps = allv[allv["var"].isin(["Zone Mean Air Temperature", "Surface Inside Face Temperature"])]
        temps = temps[(temps.minute == 0) | (temps.minute == 60)]
        temps.to_csv(results / "hour_end_temperatures.csv.gz", index=False)
        print(f"{conf}: {len(log)} runs, {int((log.returncode != 0).sum())} failed; written to {results}")


if __name__ == "__main__":
    main()
