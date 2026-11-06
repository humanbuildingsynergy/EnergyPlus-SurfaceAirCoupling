"""Accuracy and runtime of each limit on the passes (the paper's Table 4).

Settings of the patched program, all with both faces calculated again in each pass:
  converged               up to 50 passes, stop when the air changes by less than 1e-9 C, inside
                          surface tolerance 1e-8 C (the reference)
  tol_1e-2, tol_1e-3      up to 50 passes, stop below 1e-2 or 1e-3 C; inside tolerance 0.002 C
  tol_1e-3_inside_1e-4    stop below 1e-3 C, inside surface tolerance 1e-4 C
  tol_1e-4_inside_1e-5    stop below 1e-4 C, inside surface tolerance 1e-5 C
  passes_1, passes_2      exactly one or two extra passes per timestep (the 1e-9 C stop is never
                          reached); inside tolerance 0.002 C. With the HVAC in the loop these are
                          the one_pass and two_passes configurations.
Room part: single_room.py's free and free_nosolar cases, summer design day, third-order scheme,
at 4 per hour. The floating room has no HVAC, so the HVAC switch is left off there. Writes
results/passes/pass_limits_room.csv: per case and setting, the RMS difference of the hour-end air
temperature from the converged run at 4/h [C]; the timestep error left with the converged
setting (its 4/h run against its 30/h run) [C]; the release's error against the converged 30/h
run [C]; and the mean and largest number of extra passes and the timesteps that ended at the limit.
Office part: the annual small office (build/compare_programs.py writes its input to
<runs>/release_check/release/office_ts04/in.idf) with the HVAC also in the loop, every setting
and the release started together, one sample each. Writes results/passes/pass_limits_office.csv:
wall time [s], annual gas heating [GJ], occupied heating unmet hours [h], pass statistics and the
gas heating relative to the converged setting [%]. Runtimes depend on the machine; keep the
machine otherwise idle.
Usage (repository root): python3 tests/pass_limits.py [--runs runs] [--settings ...] [--part room office]
"""

import argparse
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

import _common as common
import single_room as room

sys.path.insert(0, str(common.REPO))
import configurations as C  # noqa: E402

UP_TO_50 = {"SURFACE_AIR_PASSES": "50"}
SETTINGS = {
    "converged": UP_TO_50 | {"SURFACE_AIR_TOL": "1e-9", "INSIDE_SURFACE_TOL": "1e-8"},
    "tol_1e-2": UP_TO_50 | {"SURFACE_AIR_TOL": "1e-2"},
    "tol_1e-3": UP_TO_50 | {"SURFACE_AIR_TOL": "1e-3"},
    "tol_1e-3_inside_1e-4": UP_TO_50 | {"SURFACE_AIR_TOL": "1e-3", "INSIDE_SURFACE_TOL": "1e-4"},
    "tol_1e-4_inside_1e-5": UP_TO_50 | {"SURFACE_AIR_TOL": "1e-4", "INSIDE_SURFACE_TOL": "1e-5"},
    # Fixed number of passes: the default stop at 1e-9 C is not reached in one or two passes.
    "passes_1": {"SURFACE_AIR_PASSES": "1"},
    "passes_2": {"SURFACE_AIR_PASSES": "2"},
}
OUTSIDE = {"SURFACE_AIR_OUTSIDE": "1"}
HVAC = {"SURFACE_AIR_HVAC": "1"}


def run_office(job):
    eplus, epw, idf, d, extra = job
    t0 = time.time()
    p = subprocess.run([f"{eplus}/energyplus", "-w", epw, "-d", d, idf], env=C.run_environment(extra),
                       capture_output=True, text=True)
    return {"returncode": p.returncode, "wall_s": round(time.time() - t0, 1)}


def room_part(runs, results, workers):
    base = (C.RELEASE / "ExampleFiles" / "1ZoneUncontrolled.idf").read_text()
    jobs, meta = [], []
    for case in ("free", "free_nosolar"):
        for ts in (4, 30):
            idf = room.make_idf(base, case, ts, "ThirdOrderBackwardDifference")
            conds = {"release": (C.RELEASE, {})} | {k: (C.PATCHED, OUTSIDE | v) for k, v in SETTINGS.items()}
            for cond, (eplus, env) in conds.items():
                name = f"room/{case}/{cond}/ts{ts:02d}"
                jobs.append((str(eplus), idf, name, str(runs), False, env))
                meta.append((case, cond, ts, name))
    common.run_all(jobs, workers)
    air = {}
    for case, cond, ts, name in meta:
        df = room.hour_end_series(runs / name / "eplusout.sql")
        df = df[df.env.str.contains("CLG") & df["var"].str.startswith("Zone Mean") & df.minute.isin([0, 60])]
        air[(case, cond, ts)] = df.set_index(["hour", "minute"]).value

    def rms(x, y):
        return float(np.sqrt(((x - y) ** 2).mean()))

    rows = []
    for case in ("free", "free_nosolar"):
        conv4, conv30 = air[(case, "converged", 4)], air[(case, "converged", 30)]
        for cond in SETTINGS:
            mp, mx, nc = common.pass_statistics(runs / f"room/{case}/{cond}/ts04/eplusout.err", "CLG")
            rows.append({"case": case, "setting": cond,
                         "iteration_error_C": rms(air[(case, cond, 4)], conv4),
                         "timestep_error_converged_C": rms(conv4, conv30),
                         "release_error_C": rms(air[(case, "release", 4)], conv30),
                         "mean_passes": mp, "max_passes": mx, "not_converged": nc})
    acc = pd.DataFrame(rows)
    acc.to_csv(results / "pass_limits_room.csv", index=False, float_format="%.4g")
    print(acc.to_string(index=False, float_format=lambda x: f"{x:.3g}"), "\n")


def office_part(runs, results, workers):
    office = runs.parent / "release_check" / "release" / "office_ts04" / "in.idf"
    if not office.exists():
        sys.exit(f"missing {office}; run build/compare_programs.py first")
    ojobs, ometa = [], []
    conds = {"release": (C.RELEASE, {})} | {k: (C.PATCHED, OUTSIDE | HVAC | v) for k, v in SETTINGS.items()}
    for cond, (eplus, env) in conds.items():
        d = runs / "office" / cond
        d.mkdir(parents=True, exist_ok=True)
        ojobs.append((str(eplus), str(common.WEATHER), str(office), str(d), env))
        ometa.append((cond, d))
    # All runs start together, as in the paper (one worker each, 8 in all).
    with ProcessPoolExecutor(workers or len(ojobs)) as ex:
        logs = list(ex.map(run_office, ojobs))
    rows = []
    for (cond, d), lg in zip(ometa, logs):
        if lg["returncode"] != 0:
            sys.exit(f"office run failed: {cond}")
        m = common.annual_metrics(d / "eplusout.sql")
        # The office input names its run period ANNUAL.
        mp, mx, nc = common.pass_statistics(d / "eplusout.err", "ANNUAL") if cond != "release" else (np.nan,) * 3
        rows.append({"setting": cond, "wall_s": lg["wall_s"], "gas_heating_GJ": m["gas_Heating_GJ"],
                     "unmet_heat_occ_h": m["unmet_heat_occ_h"], "mean_passes": mp, "max_passes": mx,
                     "not_converged": nc})
    off = pd.DataFrame(rows)
    conv = off.set_index("setting").loc["converged"]
    off["gas_heating_vs_converged_pct"] = 100 * (off.gas_heating_GJ / conv.gas_heating_GJ - 1)
    off.to_csv(results / "pass_limits_office.csv", index=False, float_format="%.4g")
    print(off.to_string(index=False, float_format=lambda x: f"{x:.3g}"))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--part", nargs="+", default=["room", "office"], choices=["room", "office"])
    ap.add_argument("--runs", default=str(common.REPO / "runs"),
                    help="folder for raw runs; must hold release_check/ for the office part")
    ap.add_argument("--results", default=str(common.RESULTS / "passes"), help="folder for the two tables")
    ap.add_argument("--workers", type=int, default=12, help="room part only")
    ap.add_argument("--office-workers", type=int, default=0,
                    help="office part; 0 (default) starts all eight runs at once")
    a = ap.parse_args()
    runs = Path(a.runs).resolve() / "pass_limits"
    results = Path(a.results)
    results.mkdir(parents=True, exist_ok=True)
    if "room" in a.part:
        room_part(runs, results, a.workers)
    if "office" in a.part:
        office_part(runs, results, a.office_workers)


if __name__ == "__main__":
    main()
