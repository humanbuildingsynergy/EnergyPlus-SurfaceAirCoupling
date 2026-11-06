"""Helpers shared by the scripts in tests/ and build/compare_programs.py: setpoint schedules for
the single room, a pool runner that stops on any failed run, the daily ideal-load energy of a run,
the order fit, and the annual small office input with its annual results."""

import sqlite3
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

import single_room as room  # also puts the repository root on sys.path
from configurations import PASS_STATISTICS  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"
# Denver TMY3 (WMO 724695), the weather of the small office and of the room with an exact solution.
WEATHER = REPO / "weather" / "USA_CO_Denver-Aurora-Buckley.AFB.724695_TMY3.epw"
FIT = [2, 3, 4, 5, 6, 10]  # timesteps per hour of the order fits against the 30/h run

# The setpoint schedules of single_room.py's "ideal" case, as they appear in its input text.
STEPPED = """  Schedule:Compact, CoolSP, , Through: 12/31, For: AllDays,
    Until: 08:00, 30, Until: 18:00, 24, Until: 24:00, 30;
  Schedule:Compact, HeatSP, , Through: 12/31, For: AllDays,
    Until: 08:00, 15, Until: 18:00, 21, Until: 24:00, 15;
"""

FULL_YEAR = """
  RunPeriod,
    ANNUAL,                  !- Name
    1, 1, , 12, 31, ,        !- Begin Month, Day, Year, End Month, Day, Year
    Sunday,                  !- Day of Week for Start Day
    No, No, No, Yes, Yes;    !- Holidays, DST, Weekend rule, Rain, Snow
"""


def schedules(heat, cool):
    """CoolSP/HeatSP Schedule:Compact text. heat and cool are lists of (until, value)."""
    def one(name, pairs):
        body = ", ".join(f"Until: {u}, {v}" for u, v in pairs)
        return f"  Schedule:Compact, {name}, , Through: 12/31, For: AllDays, {body};\n"
    return one("CoolSP", cool) + one("HeatSP", heat)


def no_solar(idf):
    return room.sub_once(r"1\.00;(\s*!- Sky Clearness)", r"0.00;\1", idf)


def run_all(jobs, workers=12):
    """jobs: list of single_room.run job tuples. Exits on any failed run."""
    with ProcessPoolExecutor(workers) as ex:
        log = list(ex.map(room.run, jobs))
    bad = [r for r in log if r["returncode"] != 0]
    if bad:
        sys.exit(f"failed runs: {bad[:5]} ... ({len(bad)} total)")
    return log


def day(env):
    """Design day of an environment name: CLG (summer, cooling) or HTG (winter, heating)."""
    return "CLG" if "CLG" in env else "HTG"


def daily(sql):
    """Per design day: total ideal-load energy (heating + cooling, kWh), number of timesteps on
    which the ideal loads switch between off and on, and hour-end zone air temperatures."""
    df = room.hour_end_series(sql)
    out = {}
    for env, g in df.groupby("env"):
        loads = g[g["var"].str.startswith("Zone Ideal Loads")]
        per_step = loads.groupby(["hour", "minute"]).value.sum().sort_index()
        on = (per_step > 1e-6).astype(int)
        air = g[g["var"].str.startswith("Zone Mean") & g.minute.isin([0, 60])]
        out[day(env)] = {"kWh": loads.value.sum() / 3.6e6, "switches": int(on.diff().abs().sum()),
                         "air": air.set_index(["hour", "minute"]).value}
    return out


def order(ts, err):
    """Least-squares slope of log error against log timestep length (60/ts minutes), from the
    points with a positive error; NaN with fewer than three."""
    ts, err = np.asarray(ts, float), np.asarray(err, float)
    m = err > 0
    if m.sum() < 3:
        return np.nan
    return round(float(np.polyfit(np.log(60.0 / ts[m]), np.log(err[m]), 1)[0]), 2)


def office_idf(base_text, ts):
    """Annual input of the small office prototype distributed with EnergyPlus
    (ExampleFiles/ASHRAE901_OfficeSmall_STD2019_Denver.idf) at `ts` timesteps per hour, with
    database output."""
    text = room.strip_objects(base_text, "RunPeriod")
    text = room.strip_objects(text, "Timestep")
    text = room.strip_objects(text, "Output:SQLite")
    text += FULL_YEAR
    text += f"\n  Timestep,{ts};\n"
    text += "\n  Output:SQLite,SimpleAndTabular;\n"
    return text


def tabular(con, report, table, row, col):
    q = """SELECT Value FROM TabularDataWithStrings
           WHERE ReportName=? AND TableName=? AND RowName=? AND ColumnName=?
           AND ReportForString='Entire Facility'"""
    r = con.execute(q, (report, table, row, col)).fetchone()
    return float(r[0]) if r and r[0].strip() else float("nan")


def annual_metrics(sql):
    """Annual end uses [GJ], peak electric demand [W] and occupied unmet hours [h] from the
    tabular reports of a run."""
    con = sqlite3.connect(sql)
    m = {}
    for eu in ["Heating", "Cooling", "Interior Lighting", "Interior Equipment", "Fans", "Total End Uses"]:
        m[f"elec_{eu}_GJ"] = tabular(con, "AnnualBuildingUtilityPerformanceSummary", "End Uses", eu, "Electricity")
        m[f"gas_{eu}_GJ"] = tabular(con, "AnnualBuildingUtilityPerformanceSummary", "End Uses", eu, "Natural Gas")
    m["peak_elec_W"] = tabular(con, "DemandEndUseComponentsSummary", "End Uses", "Total End Uses", "Electricity")
    m["unmet_heat_occ_h"] = tabular(con, "SystemSummary", "Time Setpoint Not Met", "Facility", "During Occupied Heating")
    m["unmet_cool_occ_h"] = tabular(con, "SystemSummary", "Time Setpoint Not Met", "Facility", "During Occupied Cooling")
    con.close()
    return m


def pass_statistics(err_file, env_substring):
    """Mean extra passes, largest number of passes and timesteps that ended at the pass limit,
    from the line the patched program writes to eplusout.err for the first environment whose name
    contains env_substring. NaN for the release, which writes no such line."""
    for line in Path(err_file).read_text(errors="replace").splitlines():
        m = PASS_STATISTICS.search(line)
        if m and env_substring in m.group(1) and int(m.group(2)) > 0:
            return float(m.group(3)), int(m.group(4)), int(m.group(5))
    return np.nan, np.nan, np.nan

